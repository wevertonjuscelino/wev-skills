"""Which lessons a task was shown, and how those tasks ended, counted per lesson."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from tests.unit._agent_helpers import make
from tests.unit._orchestrator_helpers import DOER, OrchestratorCase
from tests.unit.test_agents_experience import lesson
from tests.unit.test_specialists_learning import recorded
from wev_skills.agents import learning
from wev_skills.agents.experience import shown_lesson_ids
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.core import wiring
from wev_skills.core.contracts import TaskStatus
from wev_skills.state.model import RunState

AGENT = "project-test"


def experienced_catalog() -> wiring.AgentCatalog:
    lessons = [
        lesson("l-top", text="most confirmed", confirmations=5),
        lesson("l-low", text="less confirmed", confirmations=1),
        lesson("l-stale", text="not shown", status="stale", confirmations=9),
    ]
    spec = make(
        "builder",
        specialties=["implementation"],
        permissions=DOER,
        tools={"allow": ["Read", "Edit", "Bash"]},
        experience=lessons,
    )
    registry = AgentRegistry([spec])
    return wiring.AgentCatalog(registry, AgentFactory(registry), frozenset())


class StartRecordsShownLessons(OrchestratorCase):
    def services(self) -> wiring.Services:
        return replace(super().services(), agents=experienced_catalog())

    def test_start_keeps_the_ids_of_the_lessons_the_contract_shows(self) -> None:
        self.start()
        self.run_task()
        self.assertEqual(self.state().tasks["task-1"].lessons_shown, ("l-top", "l-low"))

    def test_the_cap_on_rendered_lessons_also_caps_the_record(self) -> None:
        self.overrides = {"specialists": {"max_lessons_rendered": 1}}
        self.start()
        self.run_task()
        self.assertEqual(self.state().tasks["task-1"].lessons_shown, ("l-top",))

    def test_shown_ids_follow_the_rendered_selection(self) -> None:
        spec = experienced_catalog().registry.get("builder")
        self.assertEqual(shown_lesson_ids(spec.experience, 12), ("l-top", "l-low"))
        self.assertEqual(shown_lesson_ids(spec.experience, 0), ())


def ended(run_id: str, status: TaskStatus, shown: tuple[str, ...]) -> RunState:
    """A run where the agent's task was shown ``shown`` and ended with ``status``."""
    state = recorded(run_id)
    task = replace(state.tasks[AGENT], status=status, lessons_shown=shown)
    return replace(state, tasks={AGENT: task}, verifications=())


def counts(states: tuple[RunState, ...]) -> list[tuple[Any, ...]]:
    return [(item.shown_verified, item.shown_unverified) for item in learning.derive(states, AGENT)]


class DeriveCountsUsage(OrchestratorCase):
    def setUp(self) -> None:
        super().setUp()
        self.source = recorded("run-0")
        self.lesson_id = learning.derive((self.source,), AGENT)[0].id

    def test_verified_and_failed_tasks_are_counted_apart(self) -> None:
        shown = (self.lesson_id,)
        states = (
            self.source,
            ended("run-1", TaskStatus.VERIFIED, shown),
            ended("run-2", TaskStatus.FAILED, shown),
            ended("run-3", TaskStatus.BLOCKED, shown),
        )
        self.assertEqual(counts(states), [(1, 2)])

    def test_a_task_that_has_not_ended_teaches_nothing(self) -> None:
        shown = (self.lesson_id,)
        states = (self.source, ended("run-1", TaskStatus.RUNNING, shown))
        self.assertEqual(counts(states), [(0, 0)])

    def test_replaying_a_run_does_not_count_twice(self) -> None:
        run = ended("run-1", TaskStatus.VERIFIED, (self.lesson_id,))
        self.assertEqual(counts((self.source, run, run)), [(1, 0)])

    def test_unknown_ids_and_other_agents_are_ignored(self) -> None:
        other = ended("run-1", TaskStatus.VERIFIED, (self.lesson_id,))
        other = replace(other, tasks={AGENT: replace(other.tasks[AGENT], agent_id="someone")})
        unknown = ended("run-2", TaskStatus.VERIFIED, ("lesson-unknown",))
        self.assertEqual(counts((self.source, other, unknown)), [(0, 0)])
