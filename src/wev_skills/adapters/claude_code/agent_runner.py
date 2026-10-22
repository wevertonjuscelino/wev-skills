"""Runs an unattended specialist (or a bare question) through ``claude -p``."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

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

UNATTENDED_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash")


def _body(rendered: str) -> str:
    """The system prompt: the rendered subagent without its frontmatter."""
    lines = rendered.split("\n")
    end = lines.index(FRONTMATTER_FENCE, 1)
    return "\n".join(lines[end + 1 :]).strip("\n")


def _parse(raw: RawCommandResult) -> AgentRunResult:
    if raw.timed_out:
        return AgentRunResult(False, i18n.t("agent_runner.timed_out"), True)
    try:
        data = json.loads(raw.stdout)
        result = data.get("result")
        failed = data.get("is_error") is True
    except ValueError, AttributeError:
        result, failed = None, False
    if failed or not isinstance(result, str):
        return AgentRunResult(False, i18n.t("agent_runner.bad_output", code=raw.exit_code))
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

    def _base(self, prompt: str) -> list[str]:
        return [
            self._program,
            "-p",
            prompt,
            "--output-format",
            "json",
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
            *self._base("Task:\n" + objective),
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
        return _parse(self._runner.run(argv, str(workspace), timeout, None))

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
            return _parse(self._runner.run(argv, scratch, timeout, None))
