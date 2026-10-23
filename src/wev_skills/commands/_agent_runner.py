"""The unattended agent behind ``specialists score`` and ``review run``: the real ``claude`` CLI."""

from __future__ import annotations

from wev_skills.adapters.claude_code.agent_runner import ClaudeAgentRunner
from wev_skills.adapters.claude_code.engine_cli import ENGINE_LAUNCHER
from wev_skills.config import Config
from wev_skills.core.ports import Runner


def claude_agent_runner(config: Config, runner: Runner) -> ClaudeAgentRunner:
    return ClaudeAgentRunner(
        runner,
        ENGINE_LAUNCHER.parent.parent,
        max_lessons=config.specialists.max_lessons_rendered,
    )
