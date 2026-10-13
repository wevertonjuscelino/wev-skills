"""Result records and metrics of the scripted evaluation. Costs and durations are simulated."""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import TaskStatus
from wev_skills.evaluation.configs import SIMULATED_PRICE_PER_TOKEN, HarnessConfig
from wev_skills.evaluation.tasks import EvalTask
from wev_skills.evaluation.tooling import SubtaskTools
from wev_skills.verification import CriterionStatus

REPORT_SCHEMA_VERSION = 1
AGENT_KIND = "scripted"
EVIDENCE_LABEL = "simulated with mocks"
RATE_DIGITS = 4
DONE_STATUSES = frozenset({TaskStatus.VERIFIED, TaskStatus.PARTIAL})
"""Statuses that satisfy a dependency: the subtask ran to the end without a failure."""


@dataclass(frozen=True)
class RuleCount(Serializable):
    rule: str
    count: int


@dataclass(frozen=True)
class VerifyRecord(Serializable):
    step_id: str
    criteria: tuple[str, ...]
    passed: bool


@dataclass(frozen=True)
class SubtaskOutcome:
    """Everything one subtask produced, over all of its attempts."""

    subtask_id: str
    status: TaskStatus
    attempts: int = 0
    final_tier: str = ""
    failure: str = ""
    start: int = 0
    end: int = 0
    duration_units: int = 0
    cost_units: int = 0
    escalations: int = 0
    tier_escalations: int = 0
    guard_trips: tuple[str, ...] = ()
    context_overflows: int = 0
    items_elided: int = 0
    items_summarized: int = 0
    info_loss_failures: int = 0
    verifications: tuple[VerifyRecord, ...] = ()
    tools: SubtaskTools | None = None


@dataclass(frozen=True)
class SubtaskSummary(Serializable):
    subtask_id: str
    status: TaskStatus
    attempts: int
    final_tier: str
    failure: str
    start: int
    end: int


@dataclass(frozen=True)
class CriterionOutcome(Serializable):
    criterion_id: str
    status: CriterionStatus


@dataclass(frozen=True)
class Counts(Serializable):
    """Additive raw counts, for one run or summed over the runs of one configuration."""

    criteria_met: int = 0
    criteria_total: int = 0
    attempts: int = 0
    escalations: int = 0
    tier_escalations: int = 0
    guard_trips: int = 0
    context_overflows: int = 0
    items_elided: int = 0
    items_summarized: int = 0
    info_loss_failures: int = 0
    unexecuted_verifications: int = 0
    tool_selection_misses: int = 0
    estimated_tool_tokens_offered: int = 0
    estimated_tool_tokens_selected: int = 0
    """Sums of rough per-tool constants over the subtasks: estimates, not measurements."""
    cost_units: int = 0
    duration_units: int = 0
    guard_trips_by_rule: tuple[RuleCount, ...] = ()


@dataclass(frozen=True)
class RunResult(Serializable):
    task_id: str
    config_id: str
    category: str
    planned: bool
    policy_flow: str
    success: bool
    counts: Counts
    criteria: tuple[CriterionOutcome, ...]
    subtasks: tuple[SubtaskSummary, ...]
    executor_tier: str = ""
    tool_profile: str = ""
    tools: tuple[str, ...] = ()
    tool_selection: str = ""
    subtask_tools: tuple[SubtaskTools, ...] = ()


@dataclass(frozen=True)
class ConfigAggregate(Serializable):
    config_id: str
    runs: int
    successes: int
    success_rate: float
    criteria_rate: float
    counts: Counts


@dataclass(frozen=True)
class TierPrice(Serializable):
    tier: str
    simulated_units_per_token_step: int


@dataclass(frozen=True)
class EvalReport(Serializable):
    """Language-neutral results. The mandatory notice is added when the report is rendered."""

    task_ids: tuple[str, ...]
    configs: tuple[HarnessConfig, ...]
    aggregates: tuple[ConfigAggregate, ...]
    runs: tuple[RunResult, ...]
    schema_version: int = REPORT_SCHEMA_VERSION
    agent: str = AGENT_KIND
    evidence_label: str = EVIDENCE_LABEL
    simulated_prices: tuple[TierPrice, ...] = tuple(
        TierPrice(tier, price) for tier, price in SIMULATED_PRICE_PER_TOKEN.items()
    )


def _rule_counts(rules: Sequence[str]) -> tuple[RuleCount, ...]:
    return tuple(RuleCount(rule, count) for rule, count in sorted(Counter(rules).items()))


def summarize_subtask(outcome: SubtaskOutcome) -> SubtaskSummary:
    return SubtaskSummary(
        outcome.subtask_id,
        outcome.status,
        outcome.attempts,
        outcome.final_tier,
        outcome.failure,
        outcome.start,
        outcome.end,
    )


def judge_criteria(
    task: EvalTask, outcomes: Sequence[SubtaskOutcome]
) -> tuple[CriterionOutcome, ...]:
    """Unmet if a supporting verification failed, met if all of them ran and passed."""
    records = {r.step_id: r for outcome in outcomes for r in outcome.verifications}
    judged: list[CriterionOutcome] = []
    for criterion in task.acceptance_criteria:
        steps = [s.id for s in task.script if criterion.id in s.criteria]
        ran = [records[step_id] for step_id in steps if step_id in records]
        if any(not record.passed for record in ran):
            status = CriterionStatus.UNMET
        elif steps and len(ran) == len(steps):
            status = CriterionStatus.MET
        else:
            status = CriterionStatus.UNVERIFIED
        judged.append(CriterionOutcome(criterion.id, status))
    return tuple(judged)


def unexecuted_verifications(task: EvalTask, outcomes: Sequence[SubtaskOutcome]) -> int:
    """Scripted verify steps that did not run in the final attempt of their subtask."""
    ran = {record.step_id for outcome in outcomes for record in outcome.verifications}
    return sum(1 for step in task.script if step.kind == "verify" and step.id not in ran)


def run_counts(
    task: EvalTask,
    outcomes: Sequence[SubtaskOutcome],
    criteria: Sequence[CriterionOutcome],
    duration_units: int,
) -> Counts:
    trips = [rule for outcome in outcomes for rule in outcome.guard_trips]
    tools = [outcome.tools for outcome in outcomes if outcome.tools is not None]
    return Counts(
        criteria_met=sum(1 for c in criteria if c.status is CriterionStatus.MET),
        criteria_total=len(criteria),
        attempts=sum(o.attempts for o in outcomes),
        escalations=sum(o.escalations for o in outcomes),
        tier_escalations=sum(o.tier_escalations for o in outcomes),
        guard_trips=len(trips),
        context_overflows=sum(o.context_overflows for o in outcomes),
        items_elided=sum(o.items_elided for o in outcomes),
        items_summarized=sum(o.items_summarized for o in outcomes),
        info_loss_failures=sum(o.info_loss_failures for o in outcomes),
        unexecuted_verifications=unexecuted_verifications(task, outcomes),
        tool_selection_misses=sum(t.misses for t in tools),
        estimated_tool_tokens_offered=sum(t.estimated_tokens_offered for t in tools),
        estimated_tool_tokens_selected=sum(t.estimated_tokens_selected for t in tools),
        cost_units=sum(o.cost_units for o in outcomes),
        duration_units=duration_units,
        guard_trips_by_rule=_rule_counts(trips),
    )


def add_counts(first: Counts, second: Counts) -> Counts:
    """Field-wise sum; per-rule counts are merged by rule name."""
    by_rule = Counter({rc.rule: rc.count for rc in first.guard_trips_by_rule})
    by_rule.update({rc.rule: rc.count for rc in second.guard_trips_by_rule})
    summed = {
        f.name: getattr(first, f.name) + getattr(second, f.name)
        for f in dataclasses.fields(Counts)
        if f.name != "guard_trips_by_rule"
    }
    rules = tuple(RuleCount(rule, count) for rule, count in sorted(by_rule.items()))
    return Counts(**summed, guard_trips_by_rule=rules)


def _rate(part: int, whole: int) -> float:
    return round(part / whole, RATE_DIGITS) if whole else 0.0


def aggregate(config_id: str, runs: Sequence[RunResult]) -> ConfigAggregate:
    """Raw totals and rates for one configuration. No comparison between configurations."""
    own = [run for run in runs if run.config_id == config_id]
    total = Counts()
    for run in own:
        total = add_counts(total, run.counts)
    successes = sum(1 for run in own if run.success)
    return ConfigAggregate(
        config_id=config_id,
        runs=len(own),
        successes=successes,
        success_rate=_rate(successes, len(own)),
        criteria_rate=_rate(total.criteria_met, total.criteria_total),
        counts=total,
    )
