"""The wiring of a score run, shared by ``specialists score`` and the score at ``run finish``."""

from __future__ import annotations

from wev_skills.adapters.claude_code.agent_runner import ClaudeAgentRunner
from wev_skills.adapters.claude_code.engine_cli import ENGINE_LAUNCHER
from wev_skills.commands._scope import Scope
from wev_skills.core import wiring
from wev_skills.core.ports import SubprocessRunner
from wev_skills.evaluation.scoring import ScoreReport, score_specialist


def score(scope: Scope, agent_id: str) -> ScoreReport:
    """Score ``agent_id`` in ``scope`` with the real ``claude`` CLI as the unattended agent."""
    runner = SubprocessRunner()
    agent = ClaudeAgentRunner(
        runner,
        ENGINE_LAUNCHER.parent.parent,
        max_lessons=scope.config.specialists.max_lessons_rendered,
    )
    audit = wiring.build_audit_log(scope.config, scope.root)
    return score_specialist(scope.root, scope.config, runner, agent, agent_id, audit)
