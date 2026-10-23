"""Records of layered review rounds: the findings a round kept and how they ended."""

from __future__ import annotations

from dataclasses import dataclass, replace

from wev_skills.core._codec import Serializable

RULE_REVIEW_ROUNDS = "review_rounds"
"""``GuardTrip.rule`` of a run that used every round ``review.max_rounds`` allows."""


@dataclass(frozen=True)
class FindingRecord(Serializable):
    id: str
    round: int
    file: str
    line: int
    title: str
    body: str
    tag: str
    """``important``, ``nit`` or ``pre_existing``."""
    class_wide: bool
    votes_real: int
    votes_total: int
    status: str = "open"
    """``open``, ``fixed`` or ``dismissed``."""
    outcome: str = ""
    reason: str = ""
    resolved_by: str = ""


@dataclass(frozen=True)
class ReviewRoundRecord(Serializable):
    number: int
    at: str
    scope: str
    """``full`` or ``diff``."""
    tree: str
    fingerprint: str
    depth: str
    findings: tuple[FindingRecord, ...] = ()
    skipped: int = 0
    runs_used: int = 0
    summary: str = ""


def all_findings(rounds: tuple[ReviewRoundRecord, ...]) -> tuple[FindingRecord, ...]:
    """Every finding of every round. A finding lives in the round that found it, and its
    status changes there, so this is the one place to read what is open now."""
    return tuple(finding for review in rounds for finding in review.findings)


def with_finding_closed(
    rounds: tuple[ReviewRoundRecord, ...],
    finding_id: str,
    status: str,
    outcome: str,
    reason: str,
    resolved_by: str,
) -> tuple[ReviewRoundRecord, ...]:
    """``rounds`` with the finding ``finding_id`` closed as given (new records)."""
    return tuple(
        replace(
            review,
            findings=tuple(
                replace(f, status=status, outcome=outcome, reason=reason, resolved_by=resolved_by)
                if f.id == finding_id
                else f
                for f in review.findings
            ),
        )
        for review in rounds
    )
