"""Dependency-injection protocols plus the default subprocess runner and clock."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from wev_skills.core.contracts import (
    AgentRunResult,
    Mode,
    PermissionDecision,
    RawCommandResult,
    RiskLevel,
)

if TYPE_CHECKING:
    from wev_skills.agents.spec import AgentSpec


UNATTENDED_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash")
READ_ONLY_TOOLS = ("Read", "Glob", "Grep")


class Runner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        cwd: str | None,
        timeout: float | None,
        env: Mapping[str, str] | None,
    ) -> RawCommandResult: ...


class AgentRunner(Protocol):
    def run_agent(
        self,
        workspace: Path,
        spec: AgentSpec,
        objective: str,
        timeout: float,
        tools: Sequence[str] = UNATTENDED_TOOLS,
    ) -> AgentRunResult: ...

    def ask(self, prompt: str, timeout: float) -> AgentRunResult: ...


class CommandGate(Protocol):
    def check_command(
        self, argv: Sequence[str], cwd: str | None, mode: Mode, risk: RiskLevel
    ) -> PermissionDecision: ...


class Summarizer(Protocol):
    def summarize(self, texts: Sequence[str]) -> str: ...


@runtime_checkable
class AgentLike(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def specialties(self) -> Sequence[str]: ...


class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()


def _to_text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


class SubprocessRunner:
    """Runs argv without a shell. Never raises on non-zero exit or timeout."""

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> RawCommandResult:
        args = tuple(argv)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                cwd=cwd,
                env=dict(env) if env is not None else None,
                capture_output=True,
                timeout=timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return RawCommandResult(
                args, None, _to_text(exc.stdout), _to_text(exc.stderr), _elapsed(started), True
            )
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
            return RawCommandResult(args, 127, "", error, _elapsed(started))
        return RawCommandResult(
            args,
            proc.returncode,
            _to_text(proc.stdout),
            _to_text(proc.stderr),
            _elapsed(started),
        )


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
