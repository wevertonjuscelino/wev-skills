"""Deterministic evaluation harness: every task under every configuration, no model involved.

Durations are simulated units (scripted steps), never wall-clock time, and nothing is random,
so two runs over the same fixtures produce identical reports.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

from wev_skills import i18n
from wev_skills.core.contracts import TaskStatus
from wev_skills.core.errors import ValidationError
from wev_skills.evaluation.agent import ScriptedAgent
from wev_skills.evaluation.configs import PLAN_DURATION_UNITS, HarnessConfig
from wev_skills.evaluation.metrics import (
    DONE_STATUSES,
    EvalReport,
    RunResult,
    SubtaskOutcome,
    aggregate,
    judge_criteria,
    run_counts,
    summarize_subtask,
)
from wev_skills.evaluation.tasks import EvalTask, Subtask
from wev_skills.verification import CriterionStatus

MECHANICS_LANGUAGE = "en"
"""Component messages (elision stubs) are sized in one fixed language so counts never vary."""
FAILURE_DEPENDENCY_FAILED = "dependency_failed"
FAILURE_DEPENDENCY_UNMET = "dependency_unmet"

Execute = Callable[[Subtask], SubtaskOutcome]


class EvalAgent(Protocol):
    planned: bool
    max_parallel: int
    policy_flow: str
    executor_tier: str
    tool_profile: str
    tools: tuple[str, ...]

    def run_subtask(self, subtask: Subtask) -> SubtaskOutcome: ...


AgentFactory = Callable[[EvalTask, HarnessConfig], EvalAgent]


def _satisfied(sub: Subtask, finished: dict[str, SubtaskOutcome]) -> bool:
    return all(dep in finished and finished[dep].status in DONE_STATUSES for dep in sub.depends_on)


def _doomed(sub: Subtask, finished: dict[str, SubtaskOutcome]) -> bool:
    """A dependency finished without succeeding, so this subtask can never start."""
    return any(
        dep in finished and finished[dep].status not in DONE_STATUSES for dep in sub.depends_on
    )


def _start_ready(
    pending: Sequence[Subtask],
    running: Sequence[tuple[Subtask, SubtaskOutcome]],
    finished: dict[str, SubtaskOutcome],
    max_parallel: int,
    now: int,
    execute: Execute,
) -> tuple[tuple[Subtask, SubtaskOutcome], ...]:
    """Start, in declaration order, what fits: free slot, dependencies done, no shared file."""
    active = tuple(running)
    for sub in pending:
        busy = {path for other, _ in active for path in other.files}
        if len(active) >= max_parallel or not _satisfied(sub, finished) or busy & set(sub.files):
            continue
        outcome = execute(sub)
        placed = replace(outcome, start=now, end=now + outcome.duration_units)
        active = (*active, (sub, placed))
    return active


def schedule(
    subtasks: Sequence[Subtask], max_parallel: int, execute: Execute, start: int = 0
) -> tuple[SubtaskOutcome, ...]:
    """Bounded parallel schedule in simulated time, returned in declaration order.

    Two subtasks never overlap in time when they share a file, and none starts before all of
    its dependencies finished successfully. A subtask whose dependency failed is not executed.
    """
    if max_parallel < 1:
        raise ValidationError("invalid_parallelism", i18n.t("evaluation.error.parallel"))
    pending = tuple(subtasks)
    running: tuple[tuple[Subtask, SubtaskOutcome], ...] = ()
    finished: dict[str, SubtaskOutcome] = {}
    now = start
    while pending or running:
        doomed = tuple(sub for sub in pending if _doomed(sub, finished))
        for sub in doomed:
            finished[sub.id] = SubtaskOutcome(
                sub.id,
                TaskStatus.NOT_EXECUTED,
                failure=FAILURE_DEPENDENCY_FAILED,
                start=now,
                end=now,
            )
        pending = tuple(sub for sub in pending if sub not in doomed)
        if doomed:
            continue
        running = _start_ready(pending, running, finished, max_parallel, now, execute)
        started = {sub.id for sub, _ in running}
        pending = tuple(sub for sub in pending if sub.id not in started)
        if not running:
            if pending:
                ids = ", ".join(sub.id for sub in pending)
                raise ValidationError(
                    "unschedulable", i18n.t("evaluation.error.unschedulable", ids=ids)
                )
            break
        now = min(outcome.end for _, outcome in running)
        finished.update({sub.id: out for sub, out in running if out.end <= now})
        running = tuple((sub, out) for sub, out in running if out.end > now)
    return tuple(finished[sub.id] for sub in subtasks)


def run_in_order(
    subtasks: Sequence[Subtask], execute: Execute, start: int = 0
) -> tuple[SubtaskOutcome, ...]:
    """No plan: declaration order, one at a time, with no dependency resolution.

    A subtask reached before its dependencies succeeded is blocked rather than reordered.
    """
    finished: dict[str, SubtaskOutcome] = {}
    now = start
    for sub in subtasks:
        if _satisfied(sub, finished):
            outcome = execute(sub)
            finished[sub.id] = replace(outcome, start=now, end=now + outcome.duration_units)
        else:
            finished[sub.id] = SubtaskOutcome(
                sub.id, TaskStatus.BLOCKED, failure=FAILURE_DEPENDENCY_UNMET, start=now, end=now
            )
        now = finished[sub.id].end
    return tuple(finished[sub.id] for sub in subtasks)


def run_one(
    task: EvalTask, config: HarnessConfig, agent_factory: AgentFactory = ScriptedAgent
) -> RunResult:
    """One task under one configuration."""
    agent = agent_factory(task, config)
    if agent.planned:
        begin = PLAN_DURATION_UNITS
        outcomes = schedule(task.subtasks, agent.max_parallel, agent.run_subtask, begin)
    else:
        begin = 0
        outcomes = run_in_order(task.subtasks, agent.run_subtask)
    duration = max([begin, *(outcome.end for outcome in outcomes)])
    criteria = judge_criteria(task, outcomes)
    return RunResult(
        task_id=task.id,
        config_id=config.id,
        category=task.category,
        planned=agent.planned,
        policy_flow=agent.policy_flow,
        success=all(c.status is CriterionStatus.MET for c in criteria),
        counts=run_counts(task, outcomes, criteria, duration),
        criteria=criteria,
        subtasks=tuple(summarize_subtask(outcome) for outcome in outcomes),
        executor_tier=agent.executor_tier,
        tool_profile=agent.tool_profile,
        tools=tuple(agent.tools),
        tool_selection=config.tool_selection,
        subtask_tools=tuple(o.tools for o in outcomes if o.tools is not None),
    )


def _require_unique(what: str, ids: Sequence[str]) -> None:
    dups = sorted({item for item in ids if ids.count(item) > 1})
    if not ids or dups:
        raise ValidationError(
            "invalid_eval_input",
            i18n.t("evaluation.error.input", what=what, ids=", ".join(dups) or "-"),
            {"what": what, "duplicates": dups},
        )


def run(
    tasks: Sequence[EvalTask],
    configs: Sequence[HarnessConfig],
    agent_factory: AgentFactory = ScriptedAgent,
) -> EvalReport:
    """Run every task under every configuration and aggregate raw counts per configuration."""
    _require_unique("task", [task.id for task in tasks])
    _require_unique("config", [config.id for config in configs])
    with i18n.use_language(MECHANICS_LANGUAGE):
        runs = tuple(run_one(task, config, agent_factory) for config in configs for task in tasks)
    return EvalReport(
        task_ids=tuple(task.id for task in tasks),
        configs=tuple(configs),
        aggregates=tuple(aggregate(config.id, runs) for config in configs),
        runs=runs,
    )
