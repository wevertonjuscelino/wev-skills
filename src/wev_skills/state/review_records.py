"""Records of layered review rounds: the findings a round kept and how they ended."""

from __future__ import annotations

from dataclasses import dataclass

from wev_skills.core._codec import Serializable


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
