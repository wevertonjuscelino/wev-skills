"""SSH transport: runs one command on one host alias. Knows nothing about tmux."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence
from typing import Protocol

from wev_skills import i18n
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import RemoteError, ValidationError
from wev_skills.core.ports import Runner
from wev_skills.core.textsafe import clean_text
from wev_skills.remote.inventory import validate_alias

SSH_FAILURE_EXIT = 255
MAX_CONNECT_TIMEOUT = 600
MAX_STDERR_CHARS = 500

_HOST_KEY_HINTS = (
    "host key verification failed",
    "remote host identification has changed",
    "no matching host key",
)
_AUTH_HINTS = ("permission denied", "too many authentication failures", "authentication failed")


class Transport(Protocol):
    def run(
        self, alias: str, remote_argv: Sequence[str], timeout: float | None = None
    ) -> RawCommandResult: ...


def build_remote_command(remote_argv: Sequence[str]) -> str:
    """Quote ``remote_argv`` into the single string the remote shell will parse."""
    args = tuple(remote_argv)
    if not args or not all(isinstance(arg, str) for arg in args) or not args[0]:
        raise ValidationError("remote_invalid_command", i18n.t("remote.error.invalid_command"))
    if any("\x00" in arg for arg in args):
        raise ValidationError("remote_invalid_command", i18n.t("remote.error.invalid_command"))
    return shlex.join(args)


def classify_ssh_failure(stderr: str) -> str:
    """``host_key``, ``authentication`` or ``connection`` for an ssh exit status 255."""
    lowered = stderr.lower()
    if any(hint in lowered for hint in _HOST_KEY_HINTS):
        return "host_key"
    if any(hint in lowered for hint in _AUTH_HINTS):
        return "authentication"
    return "connection"


class SshTransport:
    """Non-interactive ssh with strict host key checking; no passwords, keys or forwarding."""

    def __init__(
        self,
        runner: Runner,
        connect_timeout: int = 10,
        redactor: Callable[[str], str] | None = None,
    ) -> None:
        if (
            isinstance(connect_timeout, bool)
            or not isinstance(connect_timeout, int)
            or not 1 <= connect_timeout <= MAX_CONNECT_TIMEOUT
        ):
            raise ValidationError(
                "remote_invalid_timeout", i18n.t("remote.error.invalid_connect_timeout")
            )
        self._runner = runner
        self._connect_timeout = connect_timeout
        self._redactor = redactor

    def build_argv(self, alias: str, remote_argv: Sequence[str]) -> tuple[str, ...]:
        return (
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"ConnectTimeout={self._connect_timeout}",
            "--",
            validate_alias(alias),
            build_remote_command(remote_argv),
        )

    def run(
        self, alias: str, remote_argv: Sequence[str], timeout: float | None = None
    ) -> RawCommandResult:
        result = self._runner.run(self.build_argv(alias, remote_argv), None, timeout, None)
        if result.timed_out or result.exit_code is None:
            raise RemoteError("remote_timeout", i18n.t("remote.error.timeout"), {"alias": alias})
        if result.exit_code == SSH_FAILURE_EXIT:
            raise self._failure(alias, result.stderr)
        return result

    def _failure(self, alias: str, stderr: str) -> RemoteError:
        reason = classify_ssh_failure(stderr)
        details: dict[str, object] = {"alias": alias, "reason": reason}
        if self._redactor is not None:
            # Without a redactor the raw stderr is left out rather than risk leaking it.
            # Control characters go first, so an escape sequence cannot split a secret.
            details["stderr"] = self._redactor(clean_text(stderr, 0))[:MAX_STDERR_CHARS]
        return RemoteError(f"remote_{reason}_failed", i18n.t(f"remote.error.ssh.{reason}"), details)
