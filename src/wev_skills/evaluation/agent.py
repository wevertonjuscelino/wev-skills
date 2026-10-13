"""Scripted agent: replays a fixed trajectory against the real harness components.

It does not reason and calls no model. Every outcome is decided by the script, its conditions
and the configuration, so the results describe harness mechanics, never model performance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from wev_skills.agents.tool_profile import apply_profile, resolve_profile
from wev_skills.config import TIER_NAMES, ModelsConfig
from wev_skills.context import ContextManager
from wev_skills.core.contracts import (
    AttemptRecord,
    GuardAction,
    Mode,
    ModelChoice,
    TaskStatus,
)
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.evaluation import tooling
from wev_skills.evaluation.configs import (
    PLAN_TOKENS,
    REFERENCE_PERMISSIONS,
    REFERENCE_TOOLS,
    SELECTION_OFF,
    SIMULATED_PRICE_PER_TOKEN,
    STEP_DURATION_UNITS,
    HarnessConfig,
)
from wev_skills.evaluation.metrics import SubtaskOutcome, VerifyRecord
from wev_skills.evaluation.tasks import CONTEXT_KINDS, OUTCOME_PASS, EvalTask, Step, Subtask
from wev_skills.guards import (
    GuardEvent,
    attempt_event,
    budget_event,
    command_event,
    evaluate,
    handoff_event,
    progress_event,
    verification_event,
)
from wev_skills.models import ModelRouter
from wev_skills.models.router import executor_tier

REASON_INFO_LOSS = "info_loss"
REASON_OVERFLOW = "context_overflow"
REASON_ATTEMPT_GATE = "attempt_gate"
REASON_TIER_GATE = "tier_gate"
REASON_VERIFY_FAILED = "verify_failed"
REASON_GUARD_PREFIX = "guard:"
NOT_RETRIED = frozenset({REASON_INFO_LOSS, REASON_OVERFLOW, tooling.REASON_TOOL_UNAVAILABLE})
"""A retry replays the same trajectory under the same context policy, so it cannot help."""
SOFT_ACTIONS = frozenset({GuardAction.CHANGE_STRATEGY, GuardAction.REDUCE_SCOPE})
"""Verdicts that end the attempt but allow another one. Any other verdict ends the subtask."""
CHARS_PER_TOKEN = 4
SEED_CRITERIA_ID = "seed.criteria"
SEED_PLAN_ID = "seed.plan"
FILLER = "."


@dataclass(frozen=True)
class _Trail:
    """What accumulates over all attempts of one subtask."""

    events: tuple[GuardEvent, ...] = ()
    acknowledged: frozenset[tuple[str, str]] = frozenset()
    clock: int = 0
    cost: int = 0
    trips: tuple[str, ...] = ()
    overflows: int = 0
    elided: int = 0
    summarized: int = 0
    info_loss: int = 0
    tools: tooling.SubtaskTools | None = None


@dataclass(frozen=True)
class _Attempt:
    number: int
    tier: str
    context: ContextManager
    fingerprint: str
    verifications: tuple[VerifyRecord, ...] = ()


@dataclass(frozen=True)
class _Stop:
    """Why an attempt ended early. An empty reason means it did not."""

    reason: str = ""
    hard: bool = False
    rule: str = ""
    step_id: str = ""


@dataclass(frozen=True)
class _Trip:
    rule: str
    hard: bool


def filler_text(item_id: str, tokens: int) -> str:
    """Deterministic text that the context manager estimates at exactly ``tokens`` tokens."""
    size = tokens * CHARS_PER_TOKEN
    return f"[{item_id}] ".ljust(size, FILLER)[:size]


def _item_kind(step: Step, passed: bool) -> str:
    if step.kind in CONTEXT_KINDS:
        return step.kind
    if step.kind == "command":
        return "tool_output" if passed else "error"
    if step.kind == "verify":
        return "evidence" if passed else "error"
    return "note"


def unmet_condition(step: Step, attempt_number: int, tier: str, context: ContextManager) -> str:
    """The first scripted condition this step fails under the current run, or ``""``."""
    conditions = step.conditions
    verbatim = {item.id for item in context.items if not (item.elided or item.summarized)}
    if any(required not in verbatim for required in conditions.requires_verbatim):
        return REASON_INFO_LOSS
    if attempt_number < conditions.pass_from_attempt:
        return REASON_ATTEMPT_GATE
    if conditions.min_tier and TIER_NAMES.index(tier) < TIER_NAMES.index(conditions.min_tier):
        return REASON_TIER_GATE
    return ""


def _step_events(
    sub_id: str, step: Step, passed: bool, at: float, fingerprint: str
) -> tuple[GuardEvent, ...]:
    if step.kind == "command":
        argv = tuple(step.signature.split())
        code = 0 if passed else 1
        return (command_event(sub_id, at, argv, None, code, step.polling, step.flaky),)
    if step.kind == "verify":
        return (verification_event(sub_id, at, step.signature, passed, fingerprint),)
    if step.kind == "edit":
        return (progress_event(sub_id, at, fingerprint),)
    if step.kind == "handoff":
        return (handoff_event(sub_id, at, step.from_agent, step.to_agent),)
    return ()


class ScriptedAgent:
    """Replays one task's script under one configuration, one subtask at a time."""

    def __init__(self, task: EvalTask, config: HarnessConfig) -> None:
        self._task = task
        self._config = config
        self._limits = config.guard_limits()
        self._provider = LocalPolicyProvider(config.limits())
        self._router = ModelRouter(ModelsConfig())
        self._classification = self._provider.classify_task(task.signals)
        self.executor_tier: str = executor_tier(config.executor_tier, self._choose(0))
        strategy = self._provider.select_strategy(
            self._classification, Mode.AUTO, self.executor_tier
        )
        self.tool_profile: str = resolve_profile(config.tool_profile, self.executor_tier)
        offered = apply_profile(REFERENCE_TOOLS, REFERENCE_PERMISSIONS, self.tool_profile)
        self.tools: tuple[str, ...] = offered.allow if offered is not None else ()
        self.policy_flow: str = strategy.flow.value
        wants_plan = config.planning == "auto" and strategy.needs_plan
        self.planned: bool = config.planning == "on" or wants_plan
        self.max_parallel: int = strategy.max_parallel if self.planned else 1

    def run_subtask(self, subtask: Subtask) -> SubtaskOutcome:
        """Run attempts until one succeeds, a limit is reached or a guard ends the subtask."""
        tools = tooling.select(self._task, subtask, self._config, self.executor_tier)
        trail = _Trail(tools=tools)
        records: tuple[AttemptRecord, ...] = ()
        tiers: tuple[str, ...] = ()
        escalations = 0
        attempt: _Attempt | None = None
        stop = _Stop()
        for number in range(1, self._config.max_attempts + 1):
            choice = self._choose(len(records))
            tiers = (*tiers, choice.tier)
            trail, attempt, stop = self._run_attempt(subtask.id, number, choice.tier, trail)
            if not stop.reason:
                break
            signature = f"{stop.reason}@{stop.step_id}"
            failed = TaskStatus.FAILED
            records = (*records, AttemptRecord(subtask.id, number, failed, choice.model, signature))
            trail, hard = self._after_failure(subtask.id, trail, stop, signature)
            decision = self._provider.should_escalate(records, self._config.max_attempts)
            exhausted = decision.action is GuardAction.ASK_HUMAN
            escalations += int(decision.escalate and not exhausted)
            if hard or exhausted:
                break
        verifications = attempt.verifications if attempt is not None else ()
        return _outcome(subtask.id, trail, tiers, stop, escalations, verifications)

    def _choose(self, failures: int) -> ModelChoice:
        return self._router.select(
            self._classification, agent_tier_bounds=self._config.tier_bounds(), attempt=failures
        )

    def _seed(self) -> ContextManager:
        """A fresh context holding the acceptance criteria and, when planned, the plan."""
        criteria = "\n".join(c.text for c in self._task.acceptance_criteria)
        context = self._config.new_context(self._task.window_tokens).add(
            {"id": SEED_CRITERIA_ID, "kind": "requirement", "text": criteria}
        )
        if not self.planned:
            return context
        plan = filler_text(SEED_PLAN_ID, PLAN_TOKENS)
        return context.add({"id": SEED_PLAN_ID, "kind": "decision", "text": plan})

    def _run_attempt(
        self, sub_id: str, number: int, tier: str, trail: _Trail
    ) -> tuple[_Trail, _Attempt, _Stop]:
        attempt = _Attempt(number, tier, self._seed(), f"start@{number}")
        for step in self._task.steps_for(sub_id):
            for index in range(step.repeat):
                item_id = step.id if index == 0 else f"{step.id}.r{index + 1}"
                trail, attempt, stop = self._play(sub_id, step, item_id, trail, attempt)
                if stop.reason:
                    return trail, attempt, stop
        done = attempt_event(sub_id, float(trail.clock), "passed")
        return replace(trail, events=(*trail.events, done)), attempt, _Stop()

    def _feed(
        self, context: ContextManager, step: Step, item_id: str, passed: bool
    ) -> tuple[ContextManager, int, int]:
        """Add the step's item and apply the context policy: (context, elided, summarized)."""
        if step.tokens <= 0:
            return context, 0, 0
        item = {
            "id": item_id,
            "kind": _item_kind(step, passed),
            "text": filler_text(item_id, step.tokens),
        }
        grown = context.add(item)
        if self._config.context_policy == "none":
            return grown, 0, 0
        compacted, report = grown.compact()
        return compacted, len(report.elided_ids), len(report.summarized_ids)

    def _play(
        self, sub_id: str, step: Step, item_id: str, trail: _Trail, attempt: _Attempt
    ) -> tuple[_Trail, _Attempt, _Stop]:
        gate = unmet_condition(step, attempt.number, attempt.tier, attempt.context)
        if trail.tools is not None:
            checking = self._config.tool_selection != SELECTION_OFF
            tools, usable = tooling.use(trail.tools, step.needs_tool, checking)
            trail = replace(trail, tools=tools)
            gate = gate if usable else tooling.REASON_TOOL_UNAVAILABLE
        passed = not gate and step.outcome == OUTCOME_PASS
        context, elided, summarized = self._feed(attempt.context, step, item_id, passed)
        overflow = context.total_tokens() > context.budget_tokens
        cost = context.total_tokens() * SIMULATED_PRICE_PER_TOKEN[attempt.tier]
        clock = trail.clock + STEP_DURATION_UNITS
        fingerprint = f"{item_id}@{attempt.number}" if step.kind == "edit" else attempt.fingerprint
        events = _step_events(sub_id, step, passed, float(clock), fingerprint)
        spent = budget_event(sub_id, float(clock), float(cost))
        trail = replace(
            trail,
            events=(*trail.events, *events, spent),
            clock=clock,
            cost=trail.cost + cost,
            overflows=trail.overflows + int(overflow),
            elided=trail.elided + elided,
            summarized=trail.summarized + summarized,
            info_loss=trail.info_loss + int(gate == REASON_INFO_LOSS),
        )
        record = (VerifyRecord(step.id, step.criteria, passed),) if step.kind == "verify" else ()
        attempt = replace(
            attempt,
            context=context,
            fingerprint=fingerprint,
            verifications=(*attempt.verifications, *record),
        )
        trail, trip = self._judge(trail)
        return trail, attempt, _stop_for(step, gate, overflow, passed, trip)

    def _judge(self, trail: _Trail, skip_rule: str = "") -> tuple[_Trail, _Trip | None]:
        """Ask the real guard. A verdict already acted on is not acted on (or counted) again.

        A disabled guard is not consulted at all: its repeated-error rule has no limit to
        switch off, so passing empty limits would still produce verdicts.
        """
        if not self._config.guard_enabled:
            return trail, None
        verdict = evaluate(trail.events, self._limits, now=float(trail.clock))
        if verdict.action is GuardAction.CONTINUE:
            return trail, None
        first = (verdict.rule, verdict.action, verdict.reasons[0])
        found: list[tuple[str, GuardAction, str]] = [first]
        found.extend(
            (other["rule"], GuardAction(other["action"]), other["reason"])
            for other in verdict.details.get("other_rules", [])
        )
        fresh = [
            (rule, action, reason)
            for rule, action, reason in found
            if action is not GuardAction.CONTINUE and (rule, reason) not in trail.acknowledged
        ]
        if not fresh:
            return trail, None
        counted = tuple(rule for rule, _, _ in fresh if rule != skip_rule)
        seen = trail.acknowledged | {(rule, reason) for rule, _, reason in fresh}
        hard = any(action not in SOFT_ACTIONS for _, action, _ in fresh)
        updated = replace(trail, acknowledged=seen, trips=(*trail.trips, *counted))
        return updated, _Trip(fresh[0][0], hard)

    def _after_failure(
        self, sub_id: str, trail: _Trail, stop: _Stop, signature: str
    ) -> tuple[_Trail, bool]:
        """Record the failed attempt, re-ask the guard, and say whether the subtask must end."""
        failed = attempt_event(sub_id, float(trail.clock), "failed", signature)
        recorded = replace(trail, events=(*trail.events, failed))
        judged, trip = self._judge(recorded, skip_rule=stop.rule)
        return judged, stop.hard or (trip is not None and trip.hard)


def _stop_for(step: Step, gate: str, overflow: bool, passed: bool, trip: _Trip | None) -> _Stop:
    verify_failed = step.kind == "verify" and not passed
    reason = gate
    if not reason and overflow:
        reason = REASON_OVERFLOW
    if not reason and verify_failed:
        reason = REASON_VERIFY_FAILED
    rule = trip.rule if trip is not None else ""
    if not reason and trip is not None:
        reason = f"{REASON_GUARD_PREFIX}{trip.rule}"
    hard = reason in NOT_RETRIED or (trip is not None and trip.hard)
    return _Stop(reason, bool(reason) and hard, rule, step.id)


def _outcome(
    sub_id: str,
    trail: _Trail,
    tiers: tuple[str, ...],
    stop: _Stop,
    escalations: int,
    verifications: tuple[VerifyRecord, ...],
) -> SubtaskOutcome:
    if stop.reason:
        status = TaskStatus.FAILED
    else:
        status = TaskStatus.VERIFIED if verifications else TaskStatus.PARTIAL
    first = TIER_NAMES.index(tiers[0])
    return SubtaskOutcome(
        subtask_id=sub_id,
        status=status,
        attempts=len(tiers),
        final_tier=tiers[-1],
        failure=stop.reason,
        duration_units=trail.clock,
        cost_units=trail.cost,
        escalations=escalations,
        tier_escalations=sum(1 for tier in tiers[1:] if TIER_NAMES.index(tier) > first),
        guard_trips=trail.trips,
        context_overflows=trail.overflows,
        items_elided=trail.elided,
        items_summarized=trail.summarized,
        info_loss_failures=trail.info_loss,
        verifications=verifications,
        tools=trail.tools,
    )
