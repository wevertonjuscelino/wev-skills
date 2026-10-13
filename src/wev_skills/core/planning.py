"""Planning: load and validate a plan, assign agents and models, pick tasks, build contracts."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from wev_skills import i18n, schema
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import DEFAULT_AGENT_ID, TIER_NAMES, ModelsConfig, read_json_object
from wev_skills.core import agent_rules, progress
from wev_skills.core.contracts import (
    Classification,
    Complexity,
    Mode,
    ModelChoice,
    Plan,
    PlanTask,
    RiskLevel,
    TaskStatus,
)
from wev_skills.core.discovery import default_check
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.core.steps import DISCOVERY_CHECKS_KEY, suggestions_of
from wev_skills.core.task_contract import build_contract
from wev_skills.core.wiring import AgentCatalog
from wev_skills.decisions import DecisionProvider, lexicon
from wev_skills.models.router import ModelRouter
from wev_skills.security.redact import redact_mapping
from wev_skills.state.model import RunState

__all__ = ["DISCOVERY_CHECKS_KEY", "build_contract", "suggestions_of"]

SYNTHETIC_TASK_ID = "task-1"
TITLE_MAX_CHARS = 80
SOURCE_HINT = "agent_hint"
CHECKS_KEY, LINKS_KEY, CRITERIA_KEY = "checks", "check_links", "acceptance_criteria"

AttemptLimit = Callable[[str], int]


@dataclass(frozen=True)
class Assignment:
    """Who runs a task and on which model, with the reasons for both choices."""

    task_id: str
    agent_id: str
    agent_source: str
    model: ModelChoice


def _criterion_text(task: Mapping[str, Any], reference: object) -> str:
    """A criterion named by zero-based index or by its exact text; anything else is refused."""
    criteria = list(task.get(CRITERIA_KEY, []))
    index = reference if isinstance(reference, int) and not isinstance(reference, bool) else -1
    if 0 <= index < len(criteria):
        return str(criteria[index])
    if isinstance(reference, str) and reference in criteria:
        return reference
    message = i18n.t("orch.error.check_criterion", task=task.get("id", "?"), reference=reference)
    raise ValidationError("invalid_plan", message, {"task_id": task.get("id"), "ref": reference})


def _normalized_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Split ``checks`` into command strings plus the links of those given as objects."""
    commands: list[str] = []
    links: list[dict[str, Any]] = []
    given = [*task.get(CHECKS_KEY, []), *task.get(LINKS_KEY, [])]
    for check in given:
        if isinstance(check, str):
            commands.append(check)
            continue
        criteria = [_criterion_text(task, reference) for reference in check["criteria"]]
        commands.append(check["command"])
        links.append({"command": check["command"], "criteria": list(dict.fromkeys(criteria))})
    normalized = {key: value for key, value in task.items() if key != LINKS_KEY}
    normalized[CHECKS_KEY] = list(dict.fromkeys(commands))
    return {**normalized, LINKS_KEY: links} if links else normalized


def load_plan(path: str) -> Plan:
    """Read, schema-validate and structurally validate a plan file; text is redacted.

    A check is a command string, or ``{"command", "criteria"}`` tying the command to the
    acceptance criteria it is evidence for (by zero-based index or exact text).
    """
    data = read_json_object(path)
    errors = schema.validate(data, schema.load("plan"))
    if errors:
        raise ValidationError(
            "invalid_plan", i18n.t("orch.error.invalid_plan", error=errors[0]), {"errors": errors}
        )
    clean = redact_mapping(data)
    tasks = [_normalized_task(task) for task in clean.get("tasks", [])]
    plan = Plan.from_dict({**clean, "tasks": tasks})
    plan.validate()
    if not plan.tasks:
        raise ValidationError("invalid_plan", i18n.t("orch.error.empty_plan"))
    return plan


def synthesize_plan(state: RunState) -> Plan:
    """One task made from the objective, for runs whose strategy needs no plan."""
    title = state.objective.strip().splitlines()[0][:TITLE_MAX_CHARS]
    task = PlanTask(
        id=SYNTHETIC_TASK_ID,
        title=title,
        objective=state.objective,
        acceptance_criteria=(i18n.t("orch.contract.default_criterion", objective=title),),
        checks=default_check(suggestions_of(state)),
    )
    return Plan(state.objective, (task,))


def dropped_with_history(state: RunState, plan: Plan) -> list[str]:
    """Ids the new plan drops although they already ran; replacing them would lose history."""
    kept = {task.id for task in plan.tasks}
    return sorted(
        task_id
        for task_id, record in state.tasks.items()
        if task_id not in kept and record.status not in progress.WAITING
    )


def task_classification(state: RunState, task: PlanTask) -> Classification:
    base = state.classification or Classification(
        Complexity.SIMPLE, RiskLevel.LOW, 0.0, False, (), ""
    )
    return replace(base, risk=progress.task_risk(state, task))


def model_settings(spec: AgentSpec) -> tuple[str | None, tuple[str, str] | None]:
    """``(pinned model, tier bounds)`` from an agent's ``model`` and ``model_policy``.

    ``model`` is either a concrete model id (pinned) or a tier name, which becomes the
    lowest tier the agent may be given.
    """
    policy = spec.model_policy
    low = (policy.min_tier if policy else None) or TIER_NAMES[0]
    high = (policy.max_tier if policy else None) or TIER_NAMES[-1]
    if spec.model in TIER_NAMES:
        floor = max(TIER_NAMES.index(low), TIER_NAMES.index(spec.model))
        low = TIER_NAMES[min(floor, TIER_NAMES.index(high))]
        return None, (low, high)
    bounds = (low, high) if policy and (policy.min_tier or policy.max_tier) else None
    return spec.model, bounds


def select_model(
    router: ModelRouter, state: RunState, task: PlanTask, spec: AgentSpec, failures: int = 0
) -> ModelChoice:
    pinned, bounds = model_settings(spec)
    policy = spec.model_policy
    escalates = policy is None or policy.escalate_on_failure is not False
    return router.select(
        task_classification(state, task),
        agent_model=pinned,
        agent_tier_bounds=bounds,
        attempt=failures if escalates else 0,
    )


def escalated_model(
    router: ModelRouter,
    models: ModelsConfig,
    state: RunState,
    task: PlanTask,
    spec: AgentSpec,
    current: str,
    failures: int,
) -> ModelChoice:
    """The model for the next attempt after an escalation: one tier above ``current``,
    within the agent's bounds. A pinned model or ``escalate_on_failure: false`` stays put."""
    pinned, bounds = model_settings(spec)
    policy = spec.model_policy
    if pinned or (policy is not None and policy.escalate_on_failure is False):
        return select_model(router, state, task, spec, failures)
    low, high = bounds or (TIER_NAMES[0], TIER_NAMES[-1])
    held = next((i for i, name in enumerate(TIER_NAMES) if current in models.tier(name)), -1)
    floor = min(max(held + 1, TIER_NAMES.index(low)), TIER_NAMES.index(high))
    return router.select(
        task_classification(state, task),
        agent_tier_bounds=(TIER_NAMES[floor], high),
        attempt=failures,
    )


def _task_text(task: PlanTask) -> str:
    return f"{task.title} {task.objective}"


def candidates(state: RunState, task: PlanTask, agents: AgentCatalog) -> tuple[AgentSpec, ...]:
    """Agents the provider may choose from.

    Only agents whose permissions cover the run's mode and the task's risk qualify; when
    none does, the task cannot be assigned and the error says why. Outside plan mode a task
    is work to carry out, so only agents allowed to change files qualify; a read-only persona
    (reviewer, researcher) is reachable by naming it in ``agent_hint`` or by marking the
    task ``read_only``. A task about remote systems also keeps the agents allowed to use them.
    """
    risk = progress.task_risk(state, task)
    resolved = tuple(agents.factory.resolve(spec) for spec in agents.routable())
    pool = tuple(s for s in resolved if agent_rules.refusal(s, state.mode, risk) is None)
    if not pool:
        message = i18n.t(
            "orch.error.no_agent",
            task=task.id,
            mode=agent_rules.working_mode(state.mode).value,
            risk=risk.value,
        )
        raise ValidationError("no_eligible_agent", message, {"task_id": task.id})
    if state.mode is Mode.PLAN or task.read_only:
        return pool
    remote = lexicon.mentions(_task_text(task), lexicon.REMOTE)
    doers = tuple(
        s
        for s in pool
        if agent_rules.permissions_of(s).may_mutate
        or (remote and agent_rules.permissions_of(s).may_use_remote)
    )
    if not doers:
        message = i18n.t("orch.error.no_doer", task=task.id, risk=risk.value)
        raise ValidationError("no_eligible_agent", message, {"task_id": task.id})
    return doers


def default_agent(pool: Sequence[AgentSpec], configured: str = DEFAULT_AGENT_ID) -> str:
    """Who takes a task that matches nobody: ``configured`` when it is a candidate that may
    change files, else the first candidate (by id) that may. ``""`` when none may."""
    doers = sorted(s.id for s in pool if s.permissions and s.permissions.may_mutate)
    if configured in doers:
        return configured
    return doers[0] if doers else ""


def _hinted(state: RunState, task: PlanTask, agents: AgentCatalog) -> str:
    """The hinted agent, refused when its permissions do not cover the mode or the risk."""
    spec = agents.resolved(task.agent_hint)
    problem = agent_rules.refusal(spec, state.mode, progress.task_risk(state, task))
    if problem is not None:
        details = {"task_id": task.id, "agent_id": task.agent_hint}
        raise PermissionDenied("agent_not_permitted", problem, details)
    return task.agent_hint


def assign(
    state: RunState,
    task: PlanTask,
    agents: AgentCatalog,
    provider: DecisionProvider,
    router: ModelRouter,
    configured_default: str = DEFAULT_AGENT_ID,
) -> Assignment:
    """``agent_hint`` wins when it names a known agent that may take the task; otherwise
    the provider routes among the agents whose permissions cover it."""
    if task.agent_hint and task.agent_hint in agents.registry:
        agent_id, source = _hinted(state, task, agents), SOURCE_HINT
    else:
        pool = candidates(state, task, agents)
        fallback = default_agent(pool, configured_default)
        agent_id = provider.route_agent(replace(task, agent_hint=""), pool, fallback)
        source = provider.provider_id
    model = select_model(router, state, task, agents.resolved(agent_id))
    return Assignment(task.id, agent_id, source, model)


def _parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in os.path.normpath(path).split(os.sep) if part not in ("", "."))


def files_overlap(first: Sequence[str], second: Sequence[str]) -> bool:
    """True when two tasks may touch the same file. A task that lists no files may touch any."""
    if not first or not second:
        return True
    for one in map(_parts, first):
        for other in map(_parts, second):
            shorter = min(len(one), len(other))
            if one[:shorter] == other[:shorter]:
                return True
    return False


def _default_limit(state: RunState) -> AttemptLimit:
    limit = state.strategy.max_attempts if state.strategy else 1
    return lambda _task_id: limit


def startable_problem(
    state: RunState,
    task: PlanTask,
    busy: Sequence[PlanTask],
    explicit: bool = False,
    attempt_limit: AttemptLimit | None = None,
) -> str | None:
    """Why ``task`` may not start now (``None`` when it may). ``busy`` tasks hold their files.

    Every start counts against the attempt limit, whatever the previous outcome was. A
    blocked task is never offered; it starts only on an ``explicit`` request, which is how
    a person says the blocker is gone, and never once its attempts are used up.
    """
    record = state.tasks[task.id]
    limit = (attempt_limit or _default_limit(state))(task.id)
    allowed = (*progress.WAITING, *progress.RETRYABLE, *((TaskStatus.BLOCKED,) if explicit else ()))
    if record.starts >= limit and record.status not in progress.WAITING:
        return i18n.t("orch.defer.attempts", task=task.id, limit=limit)
    if record.status not in allowed:
        return i18n.t("orch.defer.status", task=task.id, status=record.status.value)
    unmet = progress.unresolved_dependencies(state, task)
    if unmet:
        return i18n.t("orch.defer.dependencies", task=task.id, deps=", ".join(unmet))
    limit_parallel = max(1, state.strategy.max_parallel if state.strategy else 1)
    if len(busy) >= limit_parallel:
        return i18n.t("orch.defer.parallel", task=task.id, limit=limit_parallel)
    clash = next((other.id for other in busy if files_overlap(task.files, other.files)), None)
    if clash is not None:
        return i18n.t("orch.defer.overlap", task=task.id, other=clash)
    return None


def running_tasks(state: RunState) -> list[PlanTask]:
    tasks = state.plan.tasks if state.plan else ()
    return [t for t in tasks if state.tasks[t.id].status is TaskStatus.RUNNING]


def select_startable(
    state: RunState,
    approved: Callable[[PlanTask], bool],
    attempt_limit: AttemptLimit | None = None,
) -> tuple[list[PlanTask], list[PlanTask], dict[str, str]]:
    """``(offered, awaiting approval, deferred reasons)`` in plan order.

    A task awaiting approval holds no slot, so it never keeps an independent task waiting.
    """
    busy = running_tasks(state)
    offered: list[PlanTask] = []
    awaiting: list[PlanTask] = []
    deferred: dict[str, str] = {}
    for task in state.plan.tasks if state.plan else ():
        if state.tasks[task.id].status in (*progress.SETTLED, TaskStatus.RUNNING):
            continue
        problem = startable_problem(state, task, [*busy, *offered], attempt_limit=attempt_limit)
        if problem is not None:
            deferred[task.id] = problem
        elif progress.needs_approval(state, task) and not approved(task):
            awaiting.append(task)
        else:
            offered.append(task)
    return offered, awaiting, deferred
