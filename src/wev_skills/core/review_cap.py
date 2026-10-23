"""The run-level stop a person must clear after the review rounds are used up."""

from __future__ import annotations

from wev_skills.core.contracts import GuardAction
from wev_skills.core.engine import Engine
from wev_skills.guards.execution import GuardVerdict
from wev_skills.state.model import RunState
from wev_skills.state.review_records import RULE_REVIEW_ROUNDS

ACKNOWLEDGED = "acknowledged"


def pending_stop(engine: Engine, state: RunState) -> GuardVerdict | None:
    """STOP while the last ``review_rounds`` trip is unacknowledged and the cap is still reached."""
    trips = [t for t in state.guard_trips if not t.task_id and t.rule == RULE_REVIEW_ROUNDS]
    cap = engine.services.config.review.max_rounds + state.review_allowance
    if not trips or trips[-1].action == ACKNOWLEDGED or len(state.review_rounds) < cap:
        return None
    return GuardVerdict(GuardAction.STOP, RULE_REVIEW_ROUNDS, trips[-1].reasons)


def run_guard_verdict(engine: Engine, state: RunState) -> GuardVerdict:
    """What ``guard check`` says of the run: its verdict, or the review stop when that is clear.

    Only the guard report reads this; ``run_verdict`` (which gates every command) does not,
    so an open review stop never blocks the run's tasks.
    """
    verdict = engine.run_verdict(state)
    if verdict.action is GuardAction.CONTINUE:
        return pending_stop(engine, state) or verdict
    return verdict
