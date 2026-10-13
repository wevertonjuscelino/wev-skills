"""Execution guard: a pure function over a recorded event history (architecture 4.8).

The guard never kills anything. It returns a verdict and the caller decides.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from wev_skills import i18n
from wev_skills.config import DEFAULT_TASK_TIMEOUT_SECONDS, LimitsConfig
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import GuardAction
from wev_skills.guards.events import GuardEvent, GuardEventKind, effective_events
from wev_skills.guards.loops import find_cycle

SEVERITY: tuple[GuardAction, ...] = (
    GuardAction.STOP,
    GuardAction.ASK_HUMAN,
    GuardAction.ESCALATE,
    GuardAction.REDUCE_SCOPE,
    GuardAction.CHANGE_STRATEGY,
    GuardAction.CONTINUE,
)
RULE_NONE = "none"
FAILURE_ESCALATION_FACTOR = 2


@dataclass(frozen=True)
class GuardLimits(Serializable):
    """Thresholds per rule. ``None`` or ``0`` disables the rule."""

    max_identical_commands: int | None = 3
    max_consecutive_failures: int | None = 3
    max_attempts: int | None = 3
    max_handoff_cycle_repeats: int | None = 2
    no_progress_window: int | None = 8
    max_repeated_verifications: int | None = 2
    budget_units: float | None = 100.0
    task_timeout_seconds: float | None = DEFAULT_TASK_TIMEOUT_SECONDS
    flaky_retries: int = 2
    max_polling_commands: int | None = 60

    @classmethod
    def from_config(cls, limits: LimitsConfig) -> GuardLimits:
        """Take what ``LimitsConfig`` has; the remaining rules keep their defaults."""
        return cls(
            max_identical_commands=limits.max_identical_commands,
            max_consecutive_failures=limits.max_consecutive_failures,
            max_attempts=limits.max_attempts,
            budget_units=limits.budget_units,
            task_timeout_seconds=limits.task_timeout_seconds,
            max_polling_commands=limits.max_polling_commands,
        )


@dataclass(frozen=True)
class GuardVerdict(Serializable):
    action: GuardAction
    rule: str
    reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Trip:
    action: GuardAction
    rule: str
    reason: str
    task_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _on(limit: float | None) -> bool:
    return limit is not None and limit > 0


def _is_command(event: GuardEvent, include_polling: bool = False) -> bool:
    return event.kind is GuardEventKind.COMMAND and (include_polling or not event.polling)


def _since_progress(evs: Sequence[GuardEvent]) -> list[GuardEvent]:
    """Non-polling commands after the latest progress event, oldest first."""
    trailing: list[GuardEvent] = []
    for event in reversed(evs):
        if event.kind is GuardEventKind.PROGRESS:
            break
        if _is_command(event):
            trailing.append(event)
    return trailing[::-1]


def _cycle_trip(tid: str, commands: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    """A cycle of two or three distinct commands repeating with no progress in between."""
    limit = lim.max_identical_commands or 0
    cycle = find_cycle([event.signature for event in commands], limit)
    if not cycle:
        return None
    reason = i18n.t("guard.cycle", signatures=", ".join(cycle), limit=limit)
    extra = {"cycle": list(cycle), "count": limit + 1}
    return _Trip(GuardAction.CHANGE_STRATEGY, "identical_commands", reason, tid, extra)


def _rule_identical(tid: str, evs: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    if not _on(lim.max_identical_commands):
        return None
    commands = _since_progress(evs)
    if not commands:
        return None
    last, count = commands[-1], 0
    for event in reversed(commands):
        if event.signature == last.signature:
            count += 1
        elif event.exit_code == 0:
            break
    allowed = (lim.max_identical_commands or 0) + (lim.flaky_retries if last.flaky else 0)
    if count <= allowed:
        return _cycle_trip(tid, commands, lim)
    reason = i18n.t("guard.identical", signature=last.signature, count=count, limit=allowed)
    return _Trip(
        GuardAction.CHANGE_STRATEGY,
        "identical_commands",
        reason,
        tid,
        {"signature": last.signature, "count": count},
    )


def _rule_polling(tid: str, evs: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    """Polling is exempt from the loop rules, but not without end: past the cap, ask."""
    if not _on(lim.max_polling_commands):
        return None
    count = 0
    for event in reversed(evs):
        if event.kind is not GuardEventKind.COMMAND:
            continue
        if not event.polling:
            break
        count += 1
    if count <= (lim.max_polling_commands or 0):
        return None
    reason = i18n.t("guard.polling_cap", count=count, limit=lim.max_polling_commands)
    return _Trip(GuardAction.ASK_HUMAN, "polling_cap", reason, tid, {"count": count})


def _rule_failures(tid: str, evs: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    limit = lim.max_consecutive_failures
    if not _on(limit):
        return None
    stream = [e for e in evs if _is_command(e) or e.kind is GuardEventKind.TASK_ATTEMPT]
    count = 0
    for event in reversed(stream):
        if not event.failed:
            break
        count += 1
    if count < (limit or 0):
        return None
    if count >= FAILURE_ESCALATION_FACTOR * (limit or 0):
        reason = i18n.t("guard.failures_escalate", count=count, limit=limit)
        return _Trip(GuardAction.ESCALATE, "consecutive_failures", reason, tid, {"count": count})
    reason = i18n.t("guard.failures", count=count, limit=limit)
    return _Trip(GuardAction.CHANGE_STRATEGY, "consecutive_failures", reason, tid, {"count": count})


def _rule_attempts(tid: str, evs: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    attempts = [e for e in evs if e.kind is GuardEventKind.TASK_ATTEMPT]
    if _on(lim.max_attempts) and len(attempts) >= (lim.max_attempts or 0):
        reason = i18n.t("guard.attempts", count=len(attempts), limit=lim.max_attempts)
        return _Trip(GuardAction.ESCALATE, "attempts", reason, tid, {"count": len(attempts)})
    failed = [e for e in attempts if e.failed]
    repeated = (
        len(failed) >= 2
        and attempts[-1].failed
        and bool(failed[-1].error_signature)
        and failed[-1].error_signature == failed[-2].error_signature
    )
    if repeated:
        reason = i18n.t("guard.same_error", signature=failed[-1].error_signature)
        return _Trip(
            GuardAction.CHANGE_STRATEGY,
            "repeated_error",
            reason,
            tid,
            {"error_signature": failed[-1].error_signature},
        )
    return None


def _count_handoff_cycles(evs: Iterable[GuardEvent]) -> tuple[int, list[str]]:
    chain: list[str] = []
    cycles = 0
    last_cycle: list[str] = []
    for event in evs:
        if event.kind is not GuardEventKind.AGENT_HANDOFF:
            continue
        if not chain or chain[-1] != event.from_agent:
            chain = [event.from_agent]
        if event.to_agent in chain:
            cycles += 1
            last_cycle = [*chain[chain.index(event.to_agent) :], event.to_agent]
            chain = chain[: chain.index(event.to_agent) + 1]
        else:
            chain.append(event.to_agent)
    return cycles, last_cycle


def _rule_handoff(tid: str, evs: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    if not _on(lim.max_handoff_cycle_repeats):
        return None
    cycles, cycle = _count_handoff_cycles(evs)
    if cycles <= (lim.max_handoff_cycle_repeats or 0):
        return None
    reason = i18n.t(
        "guard.handoff_cycle",
        chain=" -> ".join(cycle),
        count=cycles,
        limit=lim.max_handoff_cycle_repeats,
    )
    return _Trip(GuardAction.STOP, "handoff_cycle", reason, tid, {"cycle": cycle, "count": cycles})


def _commands_since_progress_change(evs: Sequence[GuardEvent]) -> int:
    count, seen = 0, None
    for event in evs:
        if event.kind is GuardEventKind.PROGRESS and event.fingerprint != seen:
            seen, count = event.fingerprint, 0
        elif _is_command(event) and not event.read_only:
            count += 1
    return count


def _rule_no_progress(tid: str, evs: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    if not _on(lim.no_progress_window):
        return None
    count = _commands_since_progress_change(evs)
    if count < (lim.no_progress_window or 0):
        return None
    reason = i18n.t("guard.no_progress", count=count, window=lim.no_progress_window)
    return _Trip(GuardAction.REDUCE_SCOPE, "no_progress", reason, tid, {"commands": count})


def _verification_runs(evs: Sequence[GuardEvent]) -> dict[str, int]:
    """Trailing failures per signature that share the latest failing state fingerprint."""
    runs: dict[str, int] = {}
    fingerprints: dict[str, str] = {}
    for event in evs:
        if event.kind is not GuardEventKind.VERIFICATION:
            continue
        sig = event.signature
        if event.passed:
            runs[sig] = 0
        elif fingerprints.get(sig) == event.state_fingerprint:
            runs[sig] = runs.get(sig, 0) + 1
        else:
            runs[sig] = 1
        fingerprints[sig] = event.state_fingerprint
    return runs


def _rule_verification(tid: str, evs: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    limit = lim.max_repeated_verifications
    if not _on(limit):
        return None
    for sig, count in sorted(_verification_runs(evs).items()):
        if count > (limit or 0):
            reason = i18n.t("guard.verification", signature=sig, count=count, limit=limit)
            return _Trip(
                GuardAction.CHANGE_STRATEGY,
                "repeated_verification",
                reason,
                tid,
                {"signature": sig, "count": count},
            )
    return None


def _rule_timeout(
    tid: str, evs: Sequence[GuardEvent], lim: GuardLimits, now: float
) -> _Trip | None:
    limit = lim.task_timeout_seconds
    if not _on(limit) or not evs:
        return None
    elapsed = now - min(e.at for e in evs)
    if elapsed <= (limit or 0):
        return None
    if _is_command(evs[-1], include_polling=True) and evs[-1].polling:
        reason = i18n.t("guard.timeout_polling", limit=limit)
        return _Trip(GuardAction.CONTINUE, "timeout", reason, tid, {"waiting": True})
    reason = i18n.t("guard.timeout", elapsed=round(elapsed, 1), limit=limit)
    return _Trip(GuardAction.ASK_HUMAN, "timeout", reason, tid, {"elapsed": elapsed})


def _rule_budget(evs: Sequence[GuardEvent], lim: GuardLimits) -> _Trip | None:
    if not _on(lim.budget_units):
        return None
    used = sum(e.units for e in evs if e.kind is GuardEventKind.BUDGET)
    if used <= (lim.budget_units or 0):
        return None
    reason = i18n.t("guard.budget", used=used, limit=lim.budget_units)
    return _Trip(GuardAction.ASK_HUMAN, "budget", reason, "", {"used": used})


_TASK_RULES: tuple[Callable[[str, Sequence[GuardEvent], GuardLimits], _Trip | None], ...] = (
    _rule_identical,
    _rule_failures,
    _rule_attempts,
    _rule_handoff,
    _rule_no_progress,
    _rule_verification,
    _rule_polling,
)


def _group_by_task(events: Sequence[GuardEvent]) -> dict[str, list[GuardEvent]]:
    groups: dict[str, list[GuardEvent]] = {}
    for event in events:
        groups.setdefault(event.task_id, []).append(event)
    return groups


def _trip_summary(trip: _Trip) -> dict[str, Any]:
    return {
        "rule": trip.rule,
        "action": trip.action.value,
        "task_id": trip.task_id,
        "reason": trip.reason,
    }


def _verdict(trips: Sequence[_Trip]) -> GuardVerdict:
    if not trips:
        return GuardVerdict(GuardAction.CONTINUE, RULE_NONE, (i18n.t("guard.ok"),), {})
    ordered = sorted(trips, key=lambda trip: SEVERITY.index(trip.action))
    top = ordered[0]
    details: dict[str, Any] = {**top.extra, "task_id": top.task_id}
    details["other_rules"] = [_trip_summary(trip) for trip in ordered[1:]]
    return GuardVerdict(top.action, top.rule, tuple(t.reason for t in ordered), details)


def evaluate(
    events: Iterable[GuardEvent],
    limits: GuardLimits,
    now: float | None = None,
    unresolved_dependencies: Sequence[str] = (),
) -> GuardVerdict:
    """Judge a history. Per-task rules run per ``task_id``; budget covers the whole history."""
    history = effective_events(events)
    moment = now if now is not None else max((e.at for e in history), default=0.0)
    trips: list[_Trip] = []
    for tid, group in _group_by_task(history).items():
        trips.extend(trip for rule in _TASK_RULES if (trip := rule(tid, group, limits)))
        timeout = _rule_timeout(tid, group, limits, moment)
        if timeout:
            trips.append(timeout)
    budget = _rule_budget(history, limits)
    if budget:
        trips.append(budget)
    if unresolved_dependencies:
        ids = sorted(unresolved_dependencies)
        reason = i18n.t("guard.dependencies", ids=", ".join(ids))
        trips.append(
            _Trip(
                GuardAction.STOP,
                "unresolved_dependencies",
                reason,
                "",
                {"unresolved_dependencies": ids},
            )
        )
    return _verdict(trips)


class ExecutionGuard:
    """Thin wrapper that appends an event and judges the new history."""

    def __init__(self, limits: GuardLimits) -> None:
        self._limits = limits

    def observe(
        self, history: Sequence[GuardEvent], event: GuardEvent
    ) -> tuple[tuple[GuardEvent, ...], GuardVerdict]:
        new_history = (*history, event)
        return new_history, evaluate(new_history, self._limits, now=event.at)
