"""The wiring of a score run, shared by ``specialists score`` and the score at ``run finish``."""

from __future__ import annotations

from wev_skills.commands._agent_runner import claude_agent_runner
from wev_skills.commands._scope import Scope
from wev_skills.core import wiring
from wev_skills.core.ports import SubprocessRunner
from wev_skills.evaluation.compare import CompareReport, compare_reviewer
from wev_skills.evaluation.scoring import ScoreReport, score_specialist


def score(scope: Scope, agent_id: str) -> ScoreReport:
    """Score ``agent_id`` in ``scope`` with the real ``claude`` CLI as the unattended agent."""
    runner = SubprocessRunner()
    agent = claude_agent_runner(scope.config, runner)
    audit = wiring.build_audit_log(scope.config, scope.root)
    return score_specialist(scope.root, scope.config, runner, agent, agent_id, audit)


def compare(scope: Scope, agent_id: str, rev: str) -> CompareReport:
    """Compare the reviewer ``agent_id`` of ``rev`` with the working tree, with the real agent."""
    runner = SubprocessRunner()
    agent = claude_agent_runner(scope.config, runner)
    audit = wiring.build_audit_log(scope.config, scope.root)
    return compare_reviewer(scope.root, scope.config, runner, agent, agent_id, rev, audit)
