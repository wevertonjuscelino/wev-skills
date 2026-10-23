"""Records the orchestrator stores per task: verification reports and independent reviews.

Like the rest of the state they hold only redacted text and no environment data.
"""

from __future__ import annotations

from dataclasses import dataclass

from wev_skills.core._codec import Serializable


@dataclass(frozen=True)
class CheckOutcome(Serializable):
    """One check of a verification: ``state`` is a ``verification.CheckState`` value."""

    check_id: str
    argv: tuple[str, ...]
    state: str
    exit_code: int | None = None
    log_ref: str = ""
    reason: str = ""
    tied: bool = False
    """The plan ties this check to named criteria; an untied check supports all of them."""
    trivial: bool = False
    """The command is a no-op (``true``, ``echo`` ...): it ran, and it shows nothing."""
    required: bool = False
    baseline_passed: bool = False


@dataclass(frozen=True)
class CriterionOutcome(Serializable):
    """One acceptance criterion: ``status`` is ``met``, ``unmet`` or ``unverified``."""

    criterion: str
    status: str
    evidence_refs: tuple[str, ...] = ()
    support: str = ""
    """``tied``, ``untied``, ``manual`` or ``none``: what kind of evidence stands behind it."""
    reason: str = ""


@dataclass(frozen=True)
class VerificationRecord(Serializable):
    task_id: str
    at: str
    all_met: bool
    summary: str
    checks: tuple[CheckOutcome, ...] = ()
    criteria: tuple[CriterionOutcome, ...] = ()
    unexecuted_checks: tuple[str, ...] = ()
    fingerprint: str = ""
    baseline: str = ""
    """``taken`` or ``not_taken``: whether the checks were run before the task's work."""
    tree_changed: bool | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskBaseline(Serializable):
    """What the engine saw when a task started: the tree, and which checks already passed."""

    at: str
    fingerprint: str
    taken: bool = False
    passed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovalNote(Serializable):
    """An approval this run asked for and what it was for (``kind``: ``task`` or ``command``)."""

    id: str
    task_id: str
    kind: str
    at: str


@dataclass(frozen=True)
class FieldChange(Serializable):
    """One field of a plan task as it was and as an amendment left it, as lists of text."""

    field: str
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanAmendment(Serializable):
    """A plan change to a task that had already started: recorded, not prevented."""

    at: str
    task_id: str
    reason: str
    changes: tuple[FieldChange, ...] = ()
    status_before: str = ""
    """The task's status when its plan changed (``TaskStatus`` value)."""


@dataclass(frozen=True)
class GuardTrip(Serializable):
    """A guard verdict other than ``continue``, kept even after the task is settled."""

    at: str
    task_id: str
    action: str
    rule: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolMiss(Serializable):
    """A tool that selection dropped and the task turned out to need (restored on request)."""

    at: str
    tool: str
    reason: str
    attempt: int = 0


@dataclass(frozen=True)
class ReviewRecord(Serializable):
    task_id: str
    at: str
    reviewer: str
    accepted: bool
    summary: str
    fingerprint: str = ""


@dataclass(frozen=True)
class RemoteRunRecord(Serializable):
    """A remote command this run started: the evidence that an exit file on the host is ours.

    Same fields as ``remote.session.RemoteRun``; it lives here so the state does not
    depend on the remote package.
    """

    task_id: str
    alias: str
    session: str
    argv: tuple[str, ...]
    started_at: float
    log_path: str
    exit_path: str
    owner_token: str
