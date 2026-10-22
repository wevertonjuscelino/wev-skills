"""The contract of one task: everything the agent that takes it is told and held to."""

from __future__ import annotations

import shlex
from collections.abc import Sequence

from wev_skills import i18n
from wev_skills.agents.experience import check_key, lead_line, rendered_lessons, shown_lesson_ids
from wev_skills.agents.spec import AgentSpec
from wev_skills.agents.tool_profile import STRUCTURED, apply_profile
from wev_skills.core import agent_rules, progress
from wev_skills.core.contracts import (
    CheckLink,
    PlanTask,
    TaskContract,
    TaskStatus,
    ToolSelection,
)
from wev_skills.core.discovery import default_check
from wev_skills.core.steps import suggestions_of
from wev_skills.state.model import RunState

CONSTRAINT_KEYS = ("scope", "exec", "report", "simplicity")
NONE_MARK = "-"


def _tools_note(task: PlanTask, selection: ToolSelection) -> str:
    """Which tools the agent has for this task, and what to do when one is missing."""
    selected = ", ".join(selection.selected) or NONE_MARK
    if not selection.dropped:
        return i18n.t("decisions.tools.contract_all", selected=selected)
    dropped = ", ".join(selection.dropped)
    return i18n.t("decisions.tools.contract", selected=selected, dropped=dropped, task=task.id)


def _context(state: RunState, task: PlanTask, selection: ToolSelection | None = None) -> str:
    lines = [i18n.t("orch.contract.context", objective=state.objective, mode=state.mode.value)]
    if selection is not None:
        lines.append(_tools_note(task, selection))
    review = progress.latest_review(state, task.id)
    if review is not None and not review.accepted:
        lines.append(
            i18n.t("orch.contract.review_note", reviewer=review.reviewer, summary=review.summary)
        )
    previous = state.tasks[task.id].result
    if previous is not None and previous.status is not TaskStatus.VERIFIED:
        lines.append(i18n.t("orch.contract.previous", summary=previous.summary))
    return "\n".join(lines)


def _exclusions(state: RunState, task: PlanTask, protected: Sequence[str]) -> tuple[str, ...]:
    others = [
        path
        for other in (state.plan.tasks if state.plan else ())
        if other.id != task.id
        for path in other.files
        if path not in task.files
    ]
    return tuple(dict.fromkeys([*others, *protected]))


def _checks(state: RunState, task: PlanTask, spec: AgentSpec) -> tuple[str, ...]:
    """The task's own checks (or the discovered default), then the agent's required ones."""
    own = task.checks or default_check(suggestions_of(state))
    return tuple(dict.fromkeys([*own, *spec.required_checks]))


contract_checks = _checks
"""Public name: tool selection keeps the shell when these are not empty."""


def _links(task: PlanTask, criteria: Sequence[str]) -> tuple[CheckLink, ...]:
    known = set(criteria)
    return tuple(
        CheckLink(link.command, tuple(c for c in link.criteria if c in known))
        for link in task.check_links
    )


def _escalation(spec: AgentSpec) -> str:
    rule = spec.escalation
    if rule is None or rule.on_failure is None:
        return ""
    target = rule.to or "-"
    return i18n.t("orch.contract.escalation", action=rule.on_failure.value, to=target)


def _granted(spec: AgentSpec, profile: str, selection: ToolSelection | None) -> tuple[str, ...]:
    """The tools the contract grants: the selection's when one ran (already inside the
    allow list, the deny list and the profile), else the allow list under the profile."""
    if selection is not None:
        return selection.selected
    tools = apply_profile(spec.tools, spec.permissions, profile)
    return tuple(tools.allow) if tools else ()


def build_contract(
    state: RunState,
    task: PlanTask,
    spec: AgentSpec,
    protected: Sequence[str] = (),
    tool_profile: str = STRUCTURED,
    selection: ToolSelection | None = None,
) -> TaskContract:
    """The full contract for one task. ``spec`` is the resolved agent assigned to it.

    ``tool_profile`` is already resolved (``structured`` or ``lean``); it can only shorten
    the tool list the contract grants, never extend it. The agent's required checks are
    appended to the checks. Its success criteria, stop conditions and escalation rule are
    carried as text for the agent; the engine does not enforce those three. ``selection``
    is the per-task tool selection, when one ran (see ``_granted``).
    """
    record = state.tasks[task.id]
    criteria = task.acceptance_criteria or (
        i18n.t("orch.contract.default_criterion", objective=task.title or task.id),
    )
    constraints = tuple(i18n.t(f"orch.contract.constraint.{n}") for n in CONSTRAINT_KEYS)
    view = spec.localized()
    allowed = agent_rules.permissions_of(spec)
    return TaskContract(
        task_id=task.id,
        objective=task.objective or task.title,
        context=_with_experience(_context(state, task, selection), state, task, spec),
        scope=task.files,
        exclusions=_exclusions(state, task, protected),
        constraints=constraints,
        acceptance_criteria=criteria,
        checks=_checks(state, task, spec),
        response_format=view.output_format or i18n.t("orch.contract.response_format"),
        permissions=_granted(spec, tool_profile, selection),
        agent_id=record.agent_id or spec.id,
        model=record.model,
        risk=progress.task_risk(state, task),
        check_links=_links(task, criteria),
        required_checks=spec.required_checks,
        read_only=task.read_only,
        may_mutate=allowed.may_mutate,
        may_use_remote=allowed.may_use_remote,
        max_attempts=agent_rules.attempt_limit(state, spec),
        timeout_seconds=spec.timeout_seconds,
        budget_units=spec.budget.max_units if spec.budget else None,
        success_criteria=view.success_criteria,
        stop_conditions=view.stop_conditions,
        escalation=_escalation(spec),
    )


def _lesson_limit(state: RunState) -> int:
    from wev_skills.config import parse_config

    return parse_config(overrides=state.config).specialists.max_lessons_rendered


def _relevant(state: RunState, task: PlanTask, spec: AgentSpec) -> frozenset[tuple[str, ...]]:
    """Keys of the lessons about the checks this task will run. A check that does not parse
    is skipped here; verification refuses it with its own error."""
    keys: set[tuple[str, ...]] = set()
    for command in _checks(state, task, spec):
        try:
            keys.add(check_key(shlex.split(command)))
        except ValueError:
            continue
    return frozenset(keys)


def lessons_shown(state: RunState, task: PlanTask, spec: AgentSpec) -> tuple[str, ...]:
    """Ids of the lessons the contract of ``task``, assigned to ``spec``, shows."""
    relevant = _relevant(state, task, spec)
    return shown_lesson_ids(spec.experience, _lesson_limit(state), relevant=relevant)


def _with_experience(context: str, state: RunState, task: PlanTask, spec: AgentSpec) -> str:
    relevant = _relevant(state, task, spec)
    lessons = rendered_lessons(spec.experience, _lesson_limit(state), relevant=relevant)
    return "\n".join((context, lead_line(), *lessons)) if lessons else context
