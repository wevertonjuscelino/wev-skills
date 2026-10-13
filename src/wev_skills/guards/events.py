"""Guard events: the recorded history the execution guard judges (architecture 4.8)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from wev_skills.core._codec import Serializable

SIGNATURE_LENGTH = 16
FAILED_ATTEMPT_STATUSES = frozenset({"failed", "blocked"})


class GuardEventKind(StrEnum):
    COMMAND = "command"
    AGENT_HANDOFF = "agent_handoff"
    TASK_ATTEMPT = "task_attempt"
    VERIFICATION = "verification"
    PROGRESS = "progress"
    BUDGET = "budget"
    RESET = "reset"


@dataclass(frozen=True)
class GuardEvent(Serializable):
    """One fact about a task. Only the fields of its ``kind`` are meaningful."""

    kind: GuardEventKind
    task_id: str
    at: float
    signature: str = ""
    exit_code: int | None = None
    polling: bool = False
    flaky: bool = False
    read_only: bool = False
    """A command on the read-only list: it cannot change the tree, so it is not counted
    toward the no-progress window (a repeated one still counts as a loop)."""
    from_agent: str = ""
    to_agent: str = ""
    status: str = ""
    error_signature: str = ""
    passed: bool = False
    state_fingerprint: str = ""
    fingerprint: str = ""
    units: float = 0.0

    @property
    def failed(self) -> bool:
        """A command with a non-zero (or missing) exit code, or an attempt that failed."""
        if self.kind is GuardEventKind.COMMAND:
            return self.exit_code != 0
        if self.kind is GuardEventKind.TASK_ATTEMPT:
            return self.status in FAILED_ATTEMPT_STATUSES
        return False


def effective_events(events: Iterable[GuardEvent]) -> tuple[GuardEvent, ...]:
    """The events that still count: those after the latest reset marker of their scope.

    A ``RESET`` marker with a ``task_id`` clears the earlier events of that task; one with an
    empty ``task_id`` clears every earlier event. Order in the sequence decides, not ``at``.
    Markers themselves are dropped from the result.
    """
    kept: list[GuardEvent] = []
    for event in events:
        if event.kind is not GuardEventKind.RESET:
            kept.append(event)
        elif event.task_id:
            kept = [e for e in kept if e.task_id != event.task_id]
        else:
            kept = []
    return tuple(kept)


def command_signature(argv: Sequence[str], cwd: str | None) -> str:
    """Stable short hash of the argv plus the normalized working directory."""
    normalized_cwd = os.path.normpath(cwd) if cwd else ""
    payload = json.dumps([list(argv), normalized_cwd], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:SIGNATURE_LENGTH]


def command_event(
    task_id: str,
    at: float,
    argv: Sequence[str],
    cwd: str | None,
    exit_code: int | None,
    polling: bool = False,
    flaky: bool = False,
    read_only: bool = False,
) -> GuardEvent:
    return GuardEvent(
        GuardEventKind.COMMAND,
        task_id,
        at,
        signature=command_signature(argv, cwd),
        exit_code=exit_code,
        polling=polling,
        flaky=flaky,
        read_only=read_only,
    )


def handoff_event(task_id: str, at: float, from_agent: str, to_agent: str) -> GuardEvent:
    return GuardEvent(
        GuardEventKind.AGENT_HANDOFF, task_id, at, from_agent=from_agent, to_agent=to_agent
    )


def attempt_event(
    task_id: str, at: float, status: str, error_signature: str = "", fingerprint: str = ""
) -> GuardEvent:
    """One recorded outcome; ``fingerprint`` is the tree it was recorded on."""
    return GuardEvent(
        GuardEventKind.TASK_ATTEMPT,
        task_id,
        at,
        status=status,
        error_signature=error_signature,
        fingerprint=fingerprint,
    )


def verification_event(
    task_id: str, at: float, signature: str, passed: bool, state_fingerprint: str
) -> GuardEvent:
    return GuardEvent(
        GuardEventKind.VERIFICATION,
        task_id,
        at,
        signature=signature,
        passed=passed,
        state_fingerprint=state_fingerprint,
    )


def progress_event(task_id: str, at: float, fingerprint: str) -> GuardEvent:
    return GuardEvent(GuardEventKind.PROGRESS, task_id, at, fingerprint=fingerprint)


def budget_event(task_id: str, at: float, units: float) -> GuardEvent:
    return GuardEvent(GuardEventKind.BUDGET, task_id, at, units=units)


def reset_event(task_id: str, at: float) -> GuardEvent:
    """Marker written by a human acknowledgement; ``task_id`` empty means the whole run."""
    return GuardEvent(GuardEventKind.RESET, task_id, at)
