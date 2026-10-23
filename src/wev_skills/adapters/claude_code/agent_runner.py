"""Runs an unattended specialist (or a bare question) through ``claude -p``."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code.subagent import (
    DEFAULT_MAX_LESSONS,
    FRONTMATTER_FENCE,
    render_subagent,
)
from wev_skills.agents.spec import AgentSpec
from wev_skills.core.contracts import AgentRunResult, RawCommandResult
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import Runner
from wev_skills.security.redact import redact
from wev_skills.security.untrusted import sanitize

UNATTENDED_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash")
STDERR_TAIL_CHARS = 500
SESSION_KEYS = ("CLAUDECODE", "CLAUDE_PID")
SESSION_PREFIX = "CLAUDE_CODE_"
KEPT_SESSION_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN",)  # authentication, not session state


def _child_env() -> dict[str, str]:
    """The environment without the calling Claude Code session's own variables."""
    return {
        key: value
        for key, value in os.environ.items()
        if key in KEPT_SESSION_KEYS
        or (key not in SESSION_KEYS and not key.startswith(SESSION_PREFIX))
    }


def _body(rendered: str) -> str:
    """The system prompt: the rendered subagent without its frontmatter."""
    lines = rendered.split("\n")
    end = lines.index(FRONTMATTER_FENCE, 1)
    return "\n".join(lines[end + 1 :]).strip("\n")


def _stderr_tail(stderr: str) -> str:
    """The end of ``stderr``, cleaned before redaction (so an escape cannot split a secret)
    and cut on a line boundary (so the cut cannot leave half a secret), then redacted again."""
    cleaned = redact(sanitize(stderr))
    tail = cleaned[-STDERR_TAIL_CHARS:]
    if len(cleaned) > STDERR_TAIL_CHARS:
        tail = tail.partition("\n")[2]  # the first line is partial
    return redact(tail).strip()


def _result_event(stdout: str) -> dict[str, Any] | None:
    """The final result object: the one ``json`` output, or the last ``result`` event of a
    ``stream-json`` output (one JSON object per line)."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        if data.get("type", "result") == "result":
            return data
    return None


def _parse(raw: RawCommandResult) -> AgentRunResult:
    if raw.timed_out:
        return AgentRunResult(False, i18n.t("agent_runner.timed_out"), True)
    data = _result_event(raw.stdout) or {}
    result = data.get("result")
    failed = data.get("is_error") is True
    if failed or not isinstance(result, str):
        tail = _stderr_tail(raw.stderr)
        message = i18n.t("agent_runner.bad_output", code=raw.exit_code, stderr=tail)
        return AgentRunResult(False, message)
    return AgentRunResult(raw.exit_code == 0, result)


class ClaudeAgentRunner:
    def __init__(
        self,
        runner: Runner,
        plugin_root: Path,
        program: str = "claude",
        max_lessons: int = DEFAULT_MAX_LESSONS,
    ) -> None:
        self._runner = runner
        self._plugin_root = plugin_root
        self._program = program
        self._max_lessons = max_lessons

    def _require_plugin(self) -> None:
        for rel in (Path(".claude-plugin") / "plugin.json", Path("hooks") / "hooks.json"):
            if not (self._plugin_root / rel).is_file():
                raise ValidationError(
                    "plugin_missing",
                    i18n.t("agent_runner.plugin_missing", path=str(self._plugin_root / rel)),
                    {"path": str(self._plugin_root / rel)},
                )

    def _base(self, prompt: str, output: str = "json") -> list[str]:
        return [
            self._program,
            "-p",
            prompt,
            "--output-format",
            output,
            "--restricted",
            "--strict-mcp-config",
            "--plugin-dir",
            str(self._plugin_root),
        ]

    def run_agent(
        self, workspace: Path, spec: AgentSpec, objective: str, timeout: float
    ) -> AgentRunResult:
        self._require_plugin()
        tools = ",".join(UNATTENDED_TOOLS)
        system = _body(render_subagent(spec, max_lessons=self._max_lessons))
        if system.startswith("-"):
            system = " " + system  # a leading dash would be read as a flag
        argv = [
            *self._base("Task:\n" + objective, "stream-json"),
            "--verbose",  # the CLI requires it for stream-json in print mode
            "--tools",
            tools,
            "--allowedTools",
            tools,
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--append-system-prompt",
            system,
        ]
        raw = self._runner.run(argv, str(workspace), timeout, _child_env())
        return replace(_parse(raw), transcript=raw.stdout)

    def ask(self, prompt: str, timeout: float) -> AgentRunResult:
        self._require_plugin()
        argv = [
            *self._base("Request:\n" + prompt),
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
        ]
        with tempfile.TemporaryDirectory(prefix="wev-ask-") as scratch:
            return _parse(self._runner.run(argv, scratch, timeout, _child_env()))
