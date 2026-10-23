"""Compare the approvals file with the audit log and name what does not agree.

This is tamper evidence, not tamper proofing: both files sit in the account of the agent
they constrain. It catches a hand-edited or naively forged approvals file and accidents
(a truncated audit log, a restored backup). A denied record that a reopen removed (another
spelling of the reopened action) is named in the ``approval.reopened`` event. An agent that
rewrites both files is not caught.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wev_skills.core._codec import Serializable

if TYPE_CHECKING:
    from wev_skills.governance.approvals import ApprovalRequest

BINDING_MISMATCH = "binding_mismatch"
GRANT_NOT_IN_AUDIT = "grant_not_in_audit"
DENIAL_NOT_IN_AUDIT = "denial_not_in_audit"
DENIAL_OVERWRITTEN = "denial_overwritten"
RECORD_MISSING = "record_missing"
_KEY_FIELDS = ("id", "generation", "binding", "decided_at", "head", "tree")
_KEY_DEFAULTS = {"head": "", "tree": ""}
"""Fields an event written before grants were anchored lacks; they were empty then."""


@dataclass(frozen=True)
class Mismatch(Serializable):
    """One disagreement between the approvals file and the audit log."""

    id: str
    problem: str


def audit_key(data: Mapping[str, Any]) -> tuple[Any, ...]:
    """What ties a record to its decision event: identity, decision time and anchor."""
    return tuple(data.get(name, _KEY_DEFAULTS.get(name)) for name in _KEY_FIELDS)


def _events(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    found = [event.get("data") for event in events if event.get("type") == kind]
    return [data for data in found if isinstance(data, Mapping)]


def _record_problems(
    record: ApprovalRequest,
    granted: set[tuple[Any, ...]],
    denied: list[Mapping[str, Any]],
) -> list[str]:
    from wev_skills.governance.approvals import (
        ApprovalStatus,
        action_hash,
        binding_hash,
    )

    problems: list[str] = []
    expected = binding_hash(record.argv, record.cwd, record.run_id, record.generation)
    if record.binding != expected or record.action_hash != action_hash(record.argv):
        problems.append(BINDING_MISMATCH)
    key = audit_key(record.to_dict())
    honored = record.status in (ApprovalStatus.GRANTED, ApprovalStatus.CONSUMED)
    if honored and key not in granted:
        problems.append(GRANT_NOT_IN_AUDIT)
    was_denied = any(
        (data.get("id"), data.get("generation")) == (record.id, record.generation)
        for data in denied
    )
    if record.status is ApprovalStatus.DENIED and key not in {audit_key(data) for data in denied}:
        problems.append(DENIAL_NOT_IN_AUDIT)
    if record.status is not ApprovalStatus.DENIED and was_denied:
        problems.append(DENIAL_OVERWRITTEN)
    return problems


def mismatches(
    records: Sequence[ApprovalRequest], events: Sequence[Mapping[str, Any]]
) -> tuple[Mismatch, ...]:
    """Every disagreement, ordered by approval id then problem."""
    from wev_skills.governance.approvals import (
        EVENT_DENIED,
        EVENT_GRANTED,
        EVENT_REOPENED,
        REPLACES_FIELD,
    )

    granted_events = _events(events, EVENT_GRANTED)
    granted = {audit_key(data) for data in granted_events}
    denied = _events(events, EVENT_DENIED)
    found = [
        Mismatch(record.id, problem)
        for record in records
        for problem in _record_problems(record, granted, denied)
    ]
    known = {record.id for record in records}
    reopened = _events(events, EVENT_REOPENED)
    replaced = {str(old) for data in reopened for old in data.get(REPLACES_FIELD) or ()}
    orphans = {str(data.get("id")) for data in (*granted_events, *denied)} - known - replaced
    found += [Mismatch(approval, RECORD_MISSING) for approval in orphans]
    return tuple(sorted(found, key=lambda item: (item.id, item.problem)))
