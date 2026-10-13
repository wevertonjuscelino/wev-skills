"""Session naming, ownership tokens, run records and the wrapper script for remote runs."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import RunStatus
from wev_skills.core.errors import ValidationError

SESSION_PREFIX = "wev"
OWNER_OPTION = "@wev_owner"
META_OPTION = "@wev_meta"
TOKEN_PREFIX = "wev1-"
MAX_TASK_SLUG = 32
MAX_EXIT_CODE = 255
MAX_TIMEOUT_SECONDS = 7 * 24 * 3600

_TOKEN_RE = re.compile(r"wev1-[0-9a-f]{16}")
_BASE_DIR_RE = re.compile(r"(~/|/)?[A-Za-z0-9._][A-Za-z0-9._/-]*")
_EXIT_RE = re.compile(r"[0-9]{1,3}")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def task_slug(task_id: str) -> str:
    """``task_id`` reduced to ``[a-z0-9-]`` and truncated; rejects ids that reduce to nothing."""
    raw = task_id.lower() if isinstance(task_id, str) else ""
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:MAX_TASK_SLUG].strip("-")
    if not slug:
        raise ValidationError("remote_invalid_task_id", i18n.t("remote.error.invalid_task_id"))
    return slug


def session_name(task_id: str, alias: str) -> str:
    """``wev-<task>-<hosthash>``: unique per task and host, safe as a tmux target."""
    return f"{SESSION_PREFIX}-{task_slug(task_id)}-{_sha(alias)[:8]}"


def owner_token(task_id: str, alias: str) -> str:
    """Marker stored on the session. Derived from the exact task id, so two task ids
    that share a slug never recognize each other's session. It is a marker, not a secret."""
    return TOKEN_PREFIX + _sha(f"{alias}\n{task_id}")[:16]


def is_owner_token(value: str) -> bool:
    return _TOKEN_RE.fullmatch(value) is not None


def action_string(alias: str, argv: Sequence[str]) -> str:
    """The exact string an approval must cover: alias plus the quoted command."""
    return f"{alias} {shlex.join(tuple(argv))}"


def validate_argv(argv: Sequence[str]) -> tuple[str, ...]:
    args = tuple(argv) if not isinstance(argv, str) else ()
    valid = bool(args) and all(isinstance(a, str) and "\x00" not in a for a in args)
    if not valid or not args[0] or args[0].startswith("-"):
        raise ValidationError("remote_invalid_command", i18n.t("remote.error.invalid_command"))
    return args


def validate_timeout(timeout_seconds: int | None) -> int | None:
    if timeout_seconds is None:
        return None
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ValidationError("remote_invalid_timeout", i18n.t("remote.error.invalid_timeout"))
    return timeout_seconds


def validate_base_dir(base_dir: str) -> str:
    """Absolute or ``~/``-relative, plain characters only, no ``..`` segment."""
    ok = isinstance(base_dir, str) and _BASE_DIR_RE.fullmatch(base_dir) is not None
    if not ok or ".." in base_dir.split("/"):
        raise ValidationError("remote_invalid_base_dir", i18n.t("remote.error.invalid_base_dir"))
    return base_dir.rstrip("/")


def remote_path(path: str) -> str:
    """Path as sent to the host: ``~/x`` becomes ``x``, relative to the home directory
    where sshd starts every command and where the wrapper is launched after ``cd``."""
    return path[2:] if path.startswith("~/") else path


@dataclass(frozen=True)
class RunPaths:
    base_dir: str
    log_path: str
    exit_path: str
    exit_tmp_path: str
    script_path: str


def run_paths(base_dir: str, task_id: str, alias: str) -> RunPaths:
    base = validate_base_dir(base_dir)
    token_hex = owner_token(task_id, alias)[len(TOKEN_PREFIX) :]
    stem = f"{base}/{session_name(task_id, alias)}.{token_hex}"
    return RunPaths(base, f"{stem}.log", f"{stem}.exit", f"{stem}.exit.tmp", f"{stem}.sh")


def build_wrapper_script(
    argv: Sequence[str], paths: RunPaths, timeout_seconds: int | None = None
) -> str:
    """Explicit ``sh`` script: run the command with output appended to the log, then
    publish the numeric exit status atomically (temp file, then ``mv``)."""
    command = validate_argv(argv)
    if timeout_seconds is not None:
        command = ("timeout", str(timeout_seconds), *command)
    log = shlex.quote(remote_path(paths.log_path))
    tmp = shlex.quote(remote_path(paths.exit_tmp_path))
    final = shlex.quote(remote_path(paths.exit_path))
    return "\n".join(
        (
            f"{shlex.join(command)} >> {log} 2>&1 < /dev/null",
            "rc=$?",
            f"printf '%s\\n' \"$rc\" > {tmp} && mv -f -- {tmp} {final}",
        )
    )


def launch_line(paths: RunPaths) -> str:
    """The only text typed into the session: plain characters, no user-supplied content."""
    return f"cd && sh {shlex.quote(remote_path(paths.script_path))}"


@dataclass(frozen=True)
class RemoteRun(Serializable):
    task_id: str
    alias: str
    session: str
    argv: tuple[str, ...]
    started_at: float
    log_path: str
    exit_path: str
    owner_token: str


class RunRecords(Protocol):
    """Remembers which runs this tool started, outside the host that ran them.

    Both methods raise a ``WevError`` when the records cannot be read or written.
    """

    def record(self, run: RemoteRun) -> None: ...

    def find(self, task_id: str, alias: str) -> RemoteRun | None: ...


@dataclass(frozen=True)
class RemoteStatus(Serializable):
    status: RunStatus
    exit_code: int | None
    session_exists: bool
    owned: bool
    reason: str


@dataclass(frozen=True)
class PreflightReport(Serializable):
    alias: str
    hostname: str
    user: str
    tmux_available: bool
    tmux_version: str
    timeout_available: bool
    base_dir: str
    base_dir_exists: bool
    base_dir_writable: bool


def parse_exit_code(text: str) -> int | None:
    """The exit status recorded in the exit file, or ``None`` when it is not a status."""
    stripped = text.strip()
    if _EXIT_RE.fullmatch(stripped) is None or int(stripped) > MAX_EXIT_CODE:
        return None
    return int(stripped)


def derive_status(
    session_exists: bool, owned: bool, exit_text: str | None, recorded: bool = False
) -> RemoteStatus:
    """Evidence rules. Only a recorded exit status yields PASSED or FAILED, and only when
    the run is tied to this task: its session exists with this task's owner marker, or
    the session is gone and ``recorded`` says this tool started the task on this host.
    An exit file with neither is a file anything on the host could have written."""
    if exit_text is not None:
        return _from_exit_file(session_exists, owned, exit_text, recorded)
    if session_exists and owned:
        return RemoteStatus(RunStatus.RUNNING, None, True, True, i18n.t("remote.status.running"))
    if session_exists:
        return RemoteStatus(RunStatus.UNKNOWN, None, True, False, i18n.t("remote.status.foreign"))
    return RemoteStatus(RunStatus.UNKNOWN, None, False, False, i18n.t("remote.status.gone"))


def _from_exit_file(
    session_exists: bool, owned: bool, exit_text: str, recorded: bool
) -> RemoteStatus:
    def unknown(key: str) -> RemoteStatus:
        return RemoteStatus(RunStatus.UNKNOWN, None, session_exists, owned, i18n.t(key))

    code = parse_exit_code(exit_text)
    if code is None:
        return unknown("remote.status.bad_exit_file")
    if session_exists and not owned:
        return unknown("remote.status.exit_unowned")
    if not session_exists and not recorded:
        return unknown("remote.status.exit_unrecorded")
    status = RunStatus.PASSED if code == 0 else RunStatus.FAILED
    return RemoteStatus(status, code, session_exists, owned, i18n.t("remote.status.exit_file"))


def parse_meta(text: str) -> tuple[tuple[str, ...], float]:
    """Recorded argv and start time; ``((), 0.0)`` when the record is missing or damaged."""
    try:
        data = json.loads(text)
    except ValueError:
        return (), 0.0
    if not isinstance(data, dict):
        return (), 0.0
    argv, started = data.get("argv"), data.get("started_at")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return (), 0.0
    if isinstance(started, bool) or not isinstance(started, (int, float)):
        return tuple(argv), 0.0
    return tuple(argv), float(started)
