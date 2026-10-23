"""Human acknowledgement of a guard verdict: a reset marker, a decision and an audit event."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from wev_skills import i18n
from wev_skills.core import progress
from wev_skills.core.contracts import GuardAction
from wev_skills.core.engine import Engine, with_trip
from wev_skills.core.errors import ValidationError
from wev_skills.core.review_cap import ACKNOWLEDGED, pending_stop, run_guard_verdict
from wev_skills.guards.events import reset_event
from wev_skills.guards.execution import GuardVerdict
from wev_skills.state.model import RunState, with_decision, with_guard_event
from wev_skills.state.records import GuardTrip

SOURCE = "guard-acknowledge"
SCOPE_RUN = "run"
SCOPE_TASK = "task"


def _verdict(engine: Engine, state: RunState, task_id: str | None) -> GuardVerdict:
    if task_id is None:
        return run_guard_verdict(engine, state)
    task = progress.plan_task(state, task_id)
    return progress.task_verdict(
        progress.guard_events(state, task_id),
        engine.task_limits(state, task_id),
        engine.now(),
        progress.unresolved_dependencies(state, task),
    )


def _summary(verdict: GuardVerdict) -> dict[str, Any]:
    return {"action": verdict.action.value, "rule": verdict.rule, "reasons": list(verdict.reasons)}


def acknowledge(
    engine: Engine, task_id: str | None, reason: str, operator: str, confirmation: str
) -> dict[str, Any]:
    """Forget the earlier guard events of a task (or of the run) so the guard counts afresh.

    Refuses a blank reason and a scope whose guard is not tripped. Only the CLI command, which
    demands a person, should call this.
    """
    text = engine.clean(reason).strip()
    if not text:
        raise ValidationError("reason_required", i18n.t("guard.error.reason_required"))
    current = engine.load()
    before = _verdict(engine, current, task_id)
    review_stop = pending_stop(engine, current) if task_id is None else None
    if before.action is GuardAction.CONTINUE:
        raise ValidationError("guard_not_tripped", i18n.t("guard.error.not_tripped"))
    scope = SCOPE_RUN if task_id is None else SCOPE_TASK
    previous = _summary(before)
    audit = {
        "scope": scope,
        "task_id": task_id or "",
        "reason": text,
        "operator": operator,
        "confirmation": confirmation,
        "previous": previous,
    }

    def change(state: RunState) -> RunState:
        marker = reset_event(task_id or "", engine.now()).to_dict()
        label = i18n.t("orch.decision.guard_ack", scope=scope, task=task_id or "-")
        record = engine.decision(state.phase, label, (text, *before.reasons), SOURCE)
        tripped = GuardTrip(engine.stamp(), task_id or "", before.action.value, before.rule)
        noted = with_trip(with_guard_event(state, marker), tripped)
        cleared = GuardTrip(engine.stamp(), task_id or "", ACKNOWLEDGED, before.rule, (text,))
        allowed = state.review_allowance + (1 if review_stop is not None else 0)
        return replace(with_decision(with_trip(noted, cleared), record), review_allowance=allowed)

    state = engine.commit(change, "guard.acknowledged", audit)
    after = _verdict(engine, state, task_id)
    fields = engine.step_fields(state)
    return {"run_id": state.run_id, **audit, "after": _summary(after), **fields}
