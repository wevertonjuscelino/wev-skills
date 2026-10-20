"""Lessons about the checks a task will run come first; relevance never hides a lesson."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

from tests.unit._agent_helpers import make
from tests.unit._orchestrator_helpers import DOER, OrchestratorCase
from tests.unit.test_agents_experience import lesson
from tests.unit.test_specialists_learning import recorded
from wev_skills.agents import learning
from wev_skills.agents.experience import Lesson, active_lessons, check_key
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.core import wiring
from wev_skills.core.contracts import TaskContract

MAKE_TEST = check_key(("make", "test"))


def keyed(lesson_id: str, key: tuple[str, ...], **fields: Any) -> dict[str, Any]:
    return lesson(lesson_id, key=list(key), **fields)


def lessons(*items: dict[str, Any]) -> tuple[Lesson, ...]:
    return make("worker", experience=list(items)).experience


def order(items: tuple[Lesson, ...], relevant: frozenset[tuple[str, ...]]) -> list[str]:
    return [item.id for item in active_lessons(items, relevant)]


class RelevanceOrderTests(unittest.TestCase):
    def test_a_lesson_about_a_check_of_the_task_comes_first(self) -> None:
        found = lessons(
            keyed("other", check_key(("ruff", "check")), confirmations=9),
            keyed("mine", MAKE_TEST, confirmations=1),
        )
        self.assertEqual(order(found, frozenset({MAKE_TEST})), ["mine", "other"])
        self.assertEqual(order(found, frozenset()), ["other", "mine"])

    def test_relevance_does_not_lift_a_demoted_lesson(self) -> None:
        found = lessons(
            keyed("weak", MAKE_TEST, confirmations=9, shown_verified=0, shown_unverified=6),
            keyed("good", ("guard", "loop"), confirmations=1, shown_verified=9, shown_unverified=1),
        )
        self.assertEqual(order(found, frozenset({MAKE_TEST})), ["good", "weak"])

    def test_learning_keys_checks_the_same_way(self) -> None:
        derived = learning.derive((recorded("run-1"),), "project-test")[0]
        self.assertEqual(derived.key, check_key(("python3", "-m", "unittest")))


def keyed_catalog() -> wiring.AgentCatalog:
    spec = make(
        "builder",
        specialties=["implementation"],
        permissions=DOER,
        tools={"allow": ["Read", "Edit", "Bash"]},
        experience=[
            keyed("general", ("guard", "loop"), text="general lesson", confirmations=9),
            keyed("about-make", MAKE_TEST, text="about make test", confirmations=1),
        ],
    )
    registry = AgentRegistry([spec])
    return wiring.AgentCatalog(registry, AgentFactory(registry), frozenset())


class ContractRelevanceTests(OrchestratorCase):
    def services(self) -> wiring.Services:
        return replace(super().services(), agents=keyed_catalog())

    def test_the_contract_and_the_record_lead_with_the_relevant_lesson(self) -> None:
        self.start()
        contract = TaskContract.from_dict(self.orch().next_tasks()["tasks"][0])
        self.assertEqual(contract.checks, ("make test",))
        self.assertLess(
            contract.context.index("about make test"), contract.context.index("general lesson")
        )
        self.orch().start_task("task-1")
        self.assertEqual(self.lessons_shown(), ("about-make", "general"))

    def test_under_a_cap_of_one_the_relevant_lesson_is_the_one_shown(self) -> None:
        self.overrides = {"specialists": {"max_lessons_rendered": 1}}
        self.start()
        self.run_task()
        self.assertEqual(self.lessons_shown(), ("about-make",))


if __name__ == "__main__":
    unittest.main()
