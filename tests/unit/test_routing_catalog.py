"""Agent routing over the shipped catalog (regression: every task went to frontend-engineer)."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from wev_skills.config import LimitsConfig, load_config
from wev_skills.core import planning, wiring
from wev_skills.core.contracts import Classification, Complexity, Mode, PlanTask, RiskLevel
from wev_skills.decisions.local import LocalPolicyProvider, agent_score, task_words
from wev_skills.state.model import RunState, with_classification, with_plan

STAMP = "2026-10-13T00:00:00.000000Z"


@dataclass(frozen=True)
class FakeAgent:
    id: str
    description: str = ""
    specialties: tuple[str, ...] = ()


def state_for(task: PlanTask, mode: Mode = Mode.EXECUTE) -> RunState:
    base = RunState("run-1", "objective", mode, STAMP, STAMP)
    low = Classification(Complexity.SIMPLE, RiskLevel.LOW, 0.0, False, (), "test")
    return with_plan(with_classification(base, low), planning.Plan("objective", (task,)))


class CatalogRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.config = load_config()
        cls.catalog = wiring.build_agents(cls.config, Path(cls.tmp.name))
        cls.provider = LocalPolicyProvider(LimitsConfig())
        cls.router = wiring.build_model_router(cls.config)

    def route(self, title: str, mode: Mode = Mode.EXECUTE, **fields: Any) -> str:
        task = PlanTask("t1", title, fields.pop("objective", title), **fields)
        chosen = planning.assign(
            state_for(task, mode),
            task,
            self.catalog,
            self.provider,
            self.router,
            self.config.agents.default_agent,
        )
        return chosen.agent_id

    def test_ui_task_goes_to_the_frontend_engineer(self) -> None:
        self.assertEqual(
            self.route("Add a button component to the settings UI"), "frontend-engineer"
        )
        self.assertEqual(self.route("Fix the CSS of the responsive layout"), "frontend-engineer")

    def test_test_writing_task_goes_to_the_test_engineer(self) -> None:
        self.assertEqual(self.route("Write unit tests for the parser"), "test-engineer")
        self.assertEqual(self.route("Add a regression test for the date bug"), "test-engineer")

    def test_generic_and_trivial_tasks_go_to_the_default_agent(self) -> None:
        for title in ("Add a greeting", "Fix a typo in the README", "Rename a variable", "x"):
            with self.subTest(title=title):
                self.assertEqual(self.route(title), "senior-engineer")

    def test_security_review_goes_to_the_auditor_when_hinted(self) -> None:
        title = "Review the session handling"
        self.assertEqual(self.route(title, agent_hint="security-auditor"), "security-auditor")

    def test_security_review_goes_to_the_auditor_when_the_task_is_read_only(self) -> None:
        title = "Security review of the session handling"
        self.assertEqual(self.route(title, read_only=True), "security-auditor")
        self.assertEqual(self.route(title, mode=Mode.PLAN), "security-auditor")

    def test_a_task_that_changes_files_never_goes_to_a_read_only_agent(self) -> None:
        chosen = self.route("Fix the security vulnerabilities in the session handling")
        self.assertTrue(self.catalog.resolved(chosen).permissions.may_mutate)

    def test_read_only_code_review_goes_to_the_code_reviewer(self) -> None:
        title = "Code review of the parser change for correctness and regressions"
        self.assertEqual(self.route(title, read_only=True), "code-reviewer")

    def test_routing_does_not_depend_on_the_order_of_the_agents(self) -> None:
        task = PlanTask("t1", "Write unit tests for the parser", "")
        pool = planning.candidates(state_for(task), task, self.catalog)
        forward = self.provider.route_agent(task, pool, "senior-engineer")
        backward = self.provider.route_agent(task, tuple(reversed(pool)), "senior-engineer")
        self.assertEqual((forward, backward), ("test-engineer", "test-engineer"))


class DefaultAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.catalog = wiring.build_agents(load_config(), Path(tmp.name))

    def default(self, configured: str, drop: tuple[str, ...] = ()) -> str:
        task = PlanTask("t1", "x", "x")
        pool = planning.candidates(state_for(task), task, self.catalog)
        return planning.default_agent(tuple(s for s in pool if s.id not in drop), configured)

    def test_configured_default_wins_when_it_is_a_candidate(self) -> None:
        self.assertEqual(self.default("senior-engineer"), "senior-engineer")
        self.assertEqual(self.default("test-engineer"), "test-engineer")

    def test_without_it_the_first_mutating_agent_by_id_is_used(self) -> None:
        self.assertEqual(self.default("senior-engineer", ("senior-engineer",)), "frontend-engineer")
        self.assertEqual(self.default("no-such-agent"), "frontend-engineer")

    def test_a_read_only_default_is_not_used_for_work_that_changes_files(self) -> None:
        self.assertEqual(self.default("code-reviewer"), "frontend-engineer")


class ScoringTests(unittest.TestCase):
    def test_words_are_whole_lowercase_and_without_stop_words(self) -> None:
        words = task_words("Fix THE bug in the UI, and the tests for it")
        self.assertEqual(words, frozenset({"fix", "bug", "ui", "test"}))

    def test_a_substring_is_not_a_match(self) -> None:
        agent = FakeAgent("a", "", ("testing",))
        self.assertEqual(agent_score(task_words("contest results"), agent), 0)

    def test_stop_words_never_score(self) -> None:
        agent = FakeAgent("a", "Reads the code and the docs for the team", ())
        self.assertEqual(agent_score(task_words("the and for"), agent), 0)

    def test_a_specialty_weighs_more_than_description_text(self) -> None:
        described = FakeAgent("a", "Handles parser work", ())
        specialist = FakeAgent("b", "", ("parser",))
        words = task_words("Rewrite the parser")
        self.assertGreater(agent_score(words, specialist), agent_score(words, described))
        partial = FakeAgent("c", "", ("parser-design",))
        self.assertGreater(agent_score(words, partial), agent_score(words, described))
        self.assertGreater(agent_score(words, specialist), agent_score(words, partial))

    def test_a_whole_specialty_beats_a_fragment_of_one(self) -> None:
        whole = FakeAgent("z", "", ("security",))
        fragment = FakeAgent("a", "", ("code-review",))
        words = task_words("Security review")
        self.assertGreater(agent_score(words, whole), agent_score(words, fragment))

    def test_no_match_falls_back_to_the_default_then_to_the_first_id(self) -> None:
        provider = LocalPolicyProvider(LimitsConfig())
        agents = [FakeAgent("zeta", "docs", ("docs",)), FakeAgent("alpha", "python", ("python",))]
        task = PlanTask("1", "unrelated", "nothing")
        self.assertEqual(provider.route_agent(task, agents, "zeta"), "zeta")
        self.assertEqual(provider.route_agent(task, agents, "ghost"), "alpha")
        self.assertEqual(provider.route_agent(task, agents), "alpha")
        hinted = replace(task, agent_hint="zeta")
        self.assertEqual(provider.route_agent(hinted, agents, "alpha"), "zeta")


if __name__ == "__main__":
    unittest.main()
