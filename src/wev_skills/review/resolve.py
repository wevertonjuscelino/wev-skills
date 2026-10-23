"""Closing a review finding by hand: ``review resolve`` (a Nit or Pre-existing one) and
``review dismiss`` (any tag, a person at a terminal)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from wev_skills import i18n
from wev_skills.core.engine import Engine
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError
from wev_skills.review.stats import BY_AGENT, BY_PERSON, REVIEWS_FILE, record_outcome
from wev_skills.review.summary import STATUS_OPEN
from wev_skills.state.model import RunState
from wev_skills.state.review_records import (
    FindingRecord,
    all_findings,
    with_finding_closed,
)

OUTCOMES = ("wrong", "intentional", "does-not-matter")
STATUS_DISMISSED = "dismissed"
TAG_IMPORTANT = "important"
RESOLVED_BY_AGENT = "resolve"


def find(state: RunState, finding_id: str) -> FindingRecord:
    for finding in all_findings(state.review_rounds):
        if finding.id == finding_id:
            return finding
    message = i18n.t("review.error.unknown_finding", id=finding_id)
    raise NotFound("unknown_finding", message, {"finding_id": finding_id})


def close(
    engine: Engine, finding_id: str, outcome: str, reason: str, by: str, person: bool
) -> dict[str, Any]:
    """Mark the finding dismissed. Without ``person`` an Important finding is refused."""
    text = engine.clean(reason).strip()
    if not text:
        raise ValidationError("reason_required", i18n.t("review.error.reason_required"))
    if outcome not in OUTCOMES:
        raise ValidationError("invalid_outcome", i18n.t("review.error.outcome", outcome=outcome))

    def change(state: RunState) -> RunState:
        found = find(state, finding_id)
        if found.status != STATUS_OPEN:
            raise ValidationError("finding_not_open", i18n.t("review.error.not_open", id=found.id))
        if found.tag == TAG_IMPORTANT and not person:
            message = i18n.t("review.error.dismiss_person_only", id=found.id)
            raise PermissionDenied("review_dismiss_person_only", message, {"finding_id": found.id})
        changes = {
            "status": STATUS_DISMISSED,
            "outcome": outcome,
            "reason": text,
            "resolved_by": by,
        }
        rounds = with_finding_closed(state.review_rounds, found.id, **changes)
        return replace(state, review_rounds=rounds)

    data = {"finding_id": finding_id, "outcome": outcome, "reason": text, "by": by}
    state = engine.commit(change, "review.dismissed" if person else "review.resolved", data)
    closed = find(state, finding_id)
    depth = next(r.depth for r in state.review_rounds if r.number == closed.round)
    by_whom = BY_PERSON if person else BY_AGENT
    path = engine.services.state_dir / REVIEWS_FILE
    record_outcome(path, engine.stamp(), state.run_id, closed, depth, by_whom)
    return {"run_id": state.run_id, "finding": closed.to_dict()}
