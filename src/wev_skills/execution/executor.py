"""Command executor: gate, run through a ``Runner``, log redacted output (architecture 4.9)."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.core import fsutil
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import (
    Evidence,
    EvidenceLabel,
    Mode,
    PermissionOutcome,
    RawCommandResult,
    RiskLevel,
    RunStatus,
)
from wev_skills.core.errors import ApprovalRequired, NotFound, PermissionDenied, ValidationError
from wev_skills.core.ports import Clock, CommandGate, Runner, SubprocessRunner, SystemClock
from wev_skills.guards.events import GuardEvent, command_event
from wev_skills.security import untrusted
from wev_skills.security.redact import redact as real_redact
from wev_skills.security.redact import redact_argv

Resolver = Callable[[Sequence[str], str], str]
"""``(argv, cwd) -> program``: the path to execute, or ``PermissionDenied``."""
OUTPUT_SOURCE = "command output"
TAIL_FIELDS = ("stdout_tail", "stderr_tail")

TAIL_CHARS = 2000
GIT_TIMEOUT_SECONDS = 30.0
GIT_STATUS_ARGV = ("git", "status", "--porcelain")
_SEQUENCE_RE = re.compile(r"^(\d+)-")
_START_FAILURE_RE = re.compile(
    r"^(FileNotFoundError|PermissionError|NotADirectoryError|OSError): \[Errno "
)
_MISSING_BINARY_EXIT = 127
_QUOTE = '"'


@dataclass(frozen=True)
class CommandRecord(Serializable):
    argv: tuple[str, ...]
    cwd: str
    duration_ms: int
    exit_code: int | None
    status: RunStatus
    stdout_ref: str
    stderr_ref: str
    stdout_tail: str
    stderr_tail: str
    changed_files: tuple[str, ...]
    timed_out: bool
    task_id: str | None
    started_at: float
    program: str = ""
    """The path that was executed: looked up on the safe path, never on ``$PATH``."""


def _identity(text: str) -> str:
    return text


def _status_of(raw: RawCommandResult, could_not_start: bool) -> RunStatus:
    if could_not_start:
        return RunStatus.BLOCKED
    if raw.timed_out or raw.exit_code is None:
        return RunStatus.UNKNOWN
    return RunStatus.PASSED if raw.exit_code == 0 else RunStatus.FAILED


def _could_not_start(raw: RawCommandResult) -> bool:
    return (
        raw.exit_code == _MISSING_BINARY_EXIT
        and not raw.stdout
        and bool(_START_FAILURE_RE.match(raw.stderr))
    )


def _parse_porcelain(text: str) -> frozenset[str]:
    """Each porcelain line as ``XY path`` (renames keep only the new path)."""
    lines = (line for line in text.splitlines() if len(line) > 3)
    return frozenset(f"{line[:2]} {line[3:].split(' -> ')[-1].strip(_QUOTE)}" for line in lines)


def _paths(lines: frozenset[str]) -> frozenset[str]:
    return frozenset(line[3:] for line in lines)


class CommandExecutor:
    """Runs one argv at a time. It never builds shell strings and never records the child's env."""

    def __init__(
        self,
        gate: CommandGate,
        runner: Runner,
        log_dir: Path,
        redactor: Callable[[str], str] = _identity,
        clock: Clock | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self._gate = gate
        self._runner = runner
        self._log_dir = Path(log_dir)
        self._redact = redactor
        self._clock = clock or SystemClock()
        self._resolver = resolver if resolver is not None else self._default_resolver()

    def _default_resolver(self) -> Resolver | None:
        """The gate's lookup when real programs are run; a scripted runner has none to find."""
        lookup = getattr(self._gate, "resolve_program", None)
        real = isinstance(self._runner, SubprocessRunner)
        return lookup if real and callable(lookup) else None

    def _safe_argv(self, argv: Sequence[str]) -> tuple[str, ...]:
        """``argv`` for logs, records and errors: redacted as a whole, then token by token."""
        whole = redact_argv(argv) if self._redact is real_redact else tuple(argv)
        return tuple(self._redact(part) for part in whole)

    def _program(self, argv: tuple[str, ...], cwd: str) -> str:
        return self._resolver(argv, cwd) if self._resolver is not None else argv[0]

    def run(
        self,
        command: Sequence[str],
        cwd: str | os.PathLike[str],
        mode: Mode,
        risk: RiskLevel,
        timeout: float | None = None,
        task_id: str | None = None,
        track_changes: bool = True,
    ) -> CommandRecord:
        argv = self._validate_argv(command)
        cwd_text = str(cwd)
        if not Path(cwd_text).is_dir():
            raise NotFound(
                "cwd_not_found", i18n.t("exec.error.cwd", cwd=cwd_text), {"cwd": cwd_text}
            )
        program = self._program(argv, cwd_text)
        self._authorize(argv, cwd_text, mode, risk)
        before = self._git_lines(cwd_text) if track_changes else None
        started_at = self._clock.now()
        raw, started = self._invoke((program, *argv[1:]), cwd_text, timeout)
        after = self._git_lines(cwd_text) if before is not None else None
        changed = self._changed(before, after)
        record = self._record(argv, cwd_text, raw, started, started_at, changed, task_id)
        return replace(record, program=program)

    def _validate_argv(self, command: Sequence[str]) -> tuple[str, ...]:
        if isinstance(command, (str, bytes)):
            raise ValidationError("shell_string", i18n.t("exec.error.string_command"))
        argv = tuple(command)
        if not argv or not all(isinstance(part, str) and part for part in argv):
            raise ValidationError("invalid_argv", i18n.t("exec.error.empty_command"))
        return argv

    def _authorize(self, argv: tuple[str, ...], cwd: str, mode: Mode, risk: RiskLevel) -> None:
        decision = self._gate.check_command(argv, cwd, mode, risk)
        details = {"argv": list(self._safe_argv(argv)), "reason": decision.reason, "cwd": cwd}
        if decision.outcome is PermissionOutcome.DENY:
            message = i18n.t("exec.error.denied", reason=decision.reason)
            raise PermissionDenied("permission_denied", message, details)
        if decision.outcome is PermissionOutcome.NEEDS_APPROVAL:
            message = i18n.t("exec.error.approval", reason=decision.reason)
            raise ApprovalRequired("approval_required", message, details)

    def _invoke(
        self, argv: tuple[str, ...], cwd: str, timeout: float | None
    ) -> tuple[RawCommandResult, bool]:
        try:
            raw = self._runner.run(argv, cwd, timeout, None)
        except OSError as exc:
            reason = f"{type(exc).__name__}: {exc}"
            return RawCommandResult(argv, None, "", reason, 0), True
        return raw, _could_not_start(raw)

    def _git_lines(self, cwd: str) -> frozenset[str] | None:
        try:
            git = (self._program(GIT_STATUS_ARGV, cwd), *GIT_STATUS_ARGV[1:])
            raw = self._runner.run(git, cwd, GIT_TIMEOUT_SECONDS, None)
        except OSError, PermissionDenied:
            return None
        if raw.timed_out or raw.exit_code != 0:
            return None
        return _parse_porcelain(raw.stdout)

    @staticmethod
    def _changed(before: frozenset[str] | None, after: frozenset[str] | None) -> tuple[str, ...]:
        if before is None or after is None:
            return ()
        return tuple(sorted(_paths(after - before) | _paths(before - after)))

    def _write_logs(self, argv: Sequence[str], stdout: str, stderr: str) -> tuple[str, str]:
        digest = hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()[:8]
        fsutil.ensure_private_dir(self._log_dir)
        with fsutil.locked(self._log_dir / "commands"):
            existing = (_SEQUENCE_RE.match(p.name) for p in self._log_dir.iterdir())
            sequence = max((int(m.group(1)) for m in existing if m), default=0) + 1
            stem = f"{sequence:06d}-{digest}"
            out_path = self._log_dir / f"{stem}.stdout.log"
            err_path = self._log_dir / f"{stem}.stderr.log"
            fsutil.atomic_write_text(out_path, stdout)
            fsutil.atomic_write_text(err_path, stderr)
        return str(out_path), str(err_path)

    def _record(
        self,
        argv: tuple[str, ...],
        cwd: str,
        raw: RawCommandResult,
        could_not_start: bool,
        started_at: float,
        changed: tuple[str, ...],
        task_id: str | None,
    ) -> CommandRecord:
        stdout, stderr = self._redact(raw.stdout), self._redact(raw.stderr)
        safe_argv = self._safe_argv(argv)
        out_ref, err_ref = self._write_logs(safe_argv, stdout, stderr)
        return CommandRecord(
            argv=safe_argv,
            cwd=cwd,
            duration_ms=raw.duration_ms,
            exit_code=None if could_not_start else raw.exit_code,
            status=_status_of(raw, could_not_start),
            stdout_ref=out_ref,
            stderr_ref=err_ref,
            stdout_tail=stdout[-TAIL_CHARS:],
            stderr_tail=stderr[-TAIL_CHARS:],
            changed_files=changed,
            timed_out=raw.timed_out,
            task_id=task_id,
            started_at=started_at,
        )


def untrusted_output(record: dict[str, Any]) -> dict[str, Any]:
    """A record as the CLI prints it: each non-empty output tail fenced as untrusted data.

    What a program printed is data from outside the engine. Control characters and escape
    sequences are stripped and the text is wrapped, so it reads as data, not instructions.
    """
    fenced = {
        name: untrusted.wrap(str(record[name]), OUTPUT_SOURCE)
        for name in TAIL_FIELDS
        if record.get(name)
    }
    return {**record, **fenced, "untrusted_output": True}


def to_evidence(record: CommandRecord, label: EvidenceLabel) -> Evidence:
    summary = i18n.t(
        "exec.evidence.summary",
        command=" ".join(record.argv),
        status=record.status.value,
        code=record.exit_code,
    )
    return Evidence(
        kind="command",
        summary=summary,
        ref=record.stdout_ref,
        exit_code=record.exit_code,
        label=label,
    )


def to_guard_event(
    record: CommandRecord, polling: bool = False, flaky: bool = False, read_only: bool = False
) -> GuardEvent:
    return command_event(
        record.task_id or "",
        record.started_at,
        record.argv,
        record.cwd,
        record.exit_code,
        polling=polling,
        flaky=flaky,
        read_only=read_only,
    )
