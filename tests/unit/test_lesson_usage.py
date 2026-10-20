"""Which lessons a task was shown, and how those tasks ended, counted per lesson."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

from tests.unit._agent_helpers import make
from tests.unit._orchestrator_helpers import DOER, OrchestratorCase
from tests.unit.test_agents_experience import lesson
from tests.unit.test_specialists_learning import recorded
from wev_skills.agents import learning
from wev_skills.agents.experience import Lesson, shown_lesson_ids
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.agents.spec import AgentSpec
from wev_skills.core import shown_lessons, wiring
from wev_skills.core.contracts import Mode, TaskStatus
from wev_skills.core.engine import Engine
from wev_skills.core.errors import StateConflict
from wev_skills.state.model import RunState, TaskRecord
from wev_skills.state.store import StateStore

AGENT = "project-test"


def experienced_catalog(
    source: Path | None = None, factory: type[AgentFactory] = AgentFactory
) -> wiring.AgentCatalog:
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
    registry = AgentRegistry([spec], {"builder": source} if source else None)
    return wiring.AgentCatalog(registry, factory(registry), frozenset())


class InheritingFactory(AgentFactory):
    """Resolves with one more lesson, as an ``extends`` chain that adds lessons would."""

    def resolve(self, spec: AgentSpec) -> AgentSpec:
        resolved = super().resolve(spec)
        extra = Lesson.from_dict(lesson("l-parent", text="inherited", confirmations=2))
        return replace(resolved, experience=(*resolved.experience, extra))


class StartRecordsShownLessons(OrchestratorCase):
    def services(self) -> wiring.Services:
        return replace(super().services(), agents=experienced_catalog())

    def test_start_keeps_the_ids_of_the_lessons_the_contract_shows(self) -> None:
        self.start()
        self.run_task()
        self.assertEqual(self.lessons_shown(), ("l-top", "l-low"))

    def test_the_cap_on_rendered_lessons_also_caps_the_record(self) -> None:
        self.overrides = {"specialists": {"max_lessons_rendered": 1}}
        self.start()
        self.run_task()
        self.assertEqual(self.lessons_shown(), ("l-top",))

    def test_the_record_stays_out_of_the_state_file(self) -> None:
        self.start()
        self.run_task()
        self.assertNotIn("lessons_shown", self.orch().store.state_path.read_text())
        self.assertEqual(self.lessons_shown(), ("l-top", "l-low"))

    def test_shown_ids_follow_the_rendered_selection(self) -> None:
        spec = experienced_catalog().registry.get("builder")
        self.assertEqual(shown_lesson_ids(spec.experience, 12), ("l-top", "l-low"))
        self.assertEqual(shown_lesson_ids(spec.experience, 0), ())


Ended = tuple[RunState, tuple[str, ...]]


def ended(run_id: str, status: TaskStatus, shown: tuple[str, ...]) -> Ended:
    """A run where the agent's task was shown ``shown`` and ended with ``status``."""
    state = recorded(run_id)
    task = replace(state.tasks[AGENT], status=status)
    return replace(state, tasks={AGENT: task}, verifications=()), shown


def counts(runs: tuple[Ended, ...]) -> list[tuple[Any, ...]]:
    states = tuple(state for state, _ in runs)
    shown = {state.run_id: {AGENT: ids} for state, ids in runs}
    derived = learning.derive(states, AGENT, shown=shown)
    return [(item.shown_verified, item.shown_unverified) for item in derived]


class DeriveCountsUsage(OrchestratorCase):
    def setUp(self) -> None:
        super().setUp()
        source = recorded("run-0")
        self.source: Ended = (source, ())
        self.lesson_id = learning.derive((source,), AGENT)[0].id

    def test_verified_and_failed_tasks_are_counted_apart(self) -> None:
        shown = (self.lesson_id,)
        runs = (
            self.source,
            ended("run-1", TaskStatus.VERIFIED, shown),
            ended("run-2", TaskStatus.FAILED, shown),
            ended("run-3", TaskStatus.BLOCKED, shown),
        )
        self.assertEqual(counts(runs), [(1, 2)])

    def test_a_task_that_has_not_ended_teaches_nothing(self) -> None:
        shown = (self.lesson_id,)
        runs = (self.source, ended("run-1", TaskStatus.RUNNING, shown))
        self.assertEqual(counts(runs), [(0, 0)])

    def test_replaying_a_run_does_not_count_twice(self) -> None:
        run = ended("run-1", TaskStatus.VERIFIED, (self.lesson_id,))
        self.assertEqual(counts((self.source, run, run)), [(1, 0)])

    def test_unknown_ids_and_other_agents_are_ignored(self) -> None:
        state, shown = ended("run-1", TaskStatus.VERIFIED, (self.lesson_id,))
        moved = replace(state.tasks[AGENT], agent_id="someone")
        other: Ended = (replace(state, tasks={AGENT: moved}), shown)
        unknown = ended("run-2", TaskStatus.VERIFIED, ("lesson-unknown",))
        self.assertEqual(counts((self.source, other, unknown)), [(0, 0)])


class StartChecksTheSourceFile(OrchestratorCase):
    """The catalog loaded ``builder`` from a file; a start rereads it under the lock."""

    factory: type[AgentFactory] = AgentFactory

    def setUp(self) -> None:
        super().setUp()
        self.path = self.root / "wev-specialists" / "builder.json"
        self.loaded = experienced_catalog().registry.get("builder")
        self.write(self.loaded.experience)

    def services(self) -> wiring.Services:
        catalog = experienced_catalog(self.path, self.factory)
        return replace(super().services(), agents=catalog)

    def write(self, experience: tuple[Any, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = replace(self.loaded, experience=experience).to_dict()
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def assert_refused(self) -> None:
        self.start()
        self.orch().next_tasks()
        with self.assertRaises(StateConflict) as caught:
            self.orch().start_task("task-1")
        self.assertEqual(caught.exception.code, "lessons_changed")
        self.assertNotEqual(self.status_of("task-1"), TaskStatus.RUNNING)
        self.assertEqual(self.lessons_shown(), ())

    def test_a_start_goes_on_when_the_file_has_the_loaded_lessons(self) -> None:
        self.start()
        self.run_task()
        self.assertEqual(self.lessons_shown(), ("l-top", "l-low"))

    def test_a_start_is_refused_when_the_lessons_changed_after_loading(self) -> None:
        self.write(self.loaded.experience[1:])
        self.assert_refused()

    def test_a_start_is_refused_when_the_file_was_deleted(self) -> None:
        self.path.unlink()
        self.assert_refused()

    def test_a_start_records_its_agent_and_attempt(self) -> None:
        self.start()
        self.run_task()
        events = [e for e in self.orch().store.events() if e["type"] == "lessons.shown"]
        expected = {"task_id": "task-1", "agent_id": "builder", "attempt": 1}
        self.assertEqual(
            [{**e["data"], "lessons": None} for e in events], [{**expected, "lessons": None}]
        )

    def test_a_failed_record_keeps_the_start_and_is_audited(self) -> None:
        self.start()
        self.orch().next_tasks()
        failing = mock.patch.object(StateStore, "append_event", side_effect=OSError("disk full"))
        with failing:
            self.orch().start_task("task-1")
        self.assertEqual(self.status_of("task-1"), TaskStatus.RUNNING)
        self.assertIn("lessons.shown_failed", self.audit_types())

    def test_a_start_whose_commit_fails_leaves_no_record(self) -> None:
        self.start()
        self.orch().next_tasks()
        failing = mock.patch.object(Engine, "commit", side_effect=OSError("disk full"))
        with failing, self.assertRaises(OSError):
            self.orch().start_task("task-1")
        self.assertEqual(shown_lessons.by_task(self.orch().store.events()), {})


class InheritedLessonsDoNotBlockStarts(StartChecksTheSourceFile):
    factory = InheritingFactory

    def test_a_start_goes_on_when_the_file_has_the_loaded_lessons(self) -> None:
        self.start()
        self.run_task()
        self.assertEqual(self.lessons_shown(), ("l-top", "l-parent", "l-low"))


def shown(task: Any, attempt: Any, agent: Any, lessons: Any) -> dict[str, Any]:
    data = {"task_id": task, "attempt": attempt, "agent_id": agent, "lessons": lessons}
    return {"type": "lessons.shown", "data": data}


def credited(events: list[Any], agent: str, starts: int, legacy: tuple[str, ...] = ()) -> Any:
    records = shown_lessons.by_task(events).get("t", ())
    return shown_lessons.for_task(records, agent, starts, legacy)


class ForTaskTests(unittest.TestCase):
    def test_the_starts_of_a_cycle_are_merged_in_order(self) -> None:
        events = [shown("t", 1, "a", ["x", "y"]), shown("t", 2, "a", ["y", "z"])]
        self.assertEqual(credited(events, "a", 2), ("x", "y", "z"))
        self.assertEqual(credited(events, "a", 1), ("x", "y"))

    def test_lessons_shown_to_another_agent_are_not_credited(self) -> None:
        events = [shown("t", 1, "former", ["old"]), shown("t", 2, "current", ["new"])]
        self.assertEqual(credited(events, "current", 2), ("new",))

    def test_after_a_reopen_only_the_last_cycle_counts(self) -> None:
        events = [shown("t", 1, "a", ["x"]), shown("t", 2, "a", ["y"]), shown("t", 1, "a", ["z"])]
        self.assertEqual(credited(events, "a", 1), ("z",))

    def test_ids_release_3_0_0_kept_count_while_the_cycle_continues(self) -> None:
        self.assertEqual(credited([], "a", 1, ("old",)), ("old",))
        self.assertEqual(credited([shown("t", 2, "a", ["new"])], "a", 2, ("old",)), ("old", "new"))

    def test_ids_release_3_0_0_kept_are_dropped_after_a_restart_or_a_reassignment(self) -> None:
        self.assertEqual(credited([shown("t", 1, "a", ["new"])], "a", 1, ("old",)), ("new",))
        self.assertEqual(credited([shown("t", 2, "b", [])], "a", 2, ("old",)), ())

    def test_records_release_4_0_0_wrote_without_an_agent_are_not_counted(self) -> None:
        unattributed = {"type": "lessons.shown", "data": {"task_id": "t", "lessons": ["v4"]}}
        self.assertEqual(credited([unattributed, shown("t", 1, "a", ["new"])], "a", 1), ("new",))

    def test_lines_that_are_not_well_formed_records_are_skipped(self) -> None:
        events: list[Any] = [
            3,
            "text",
            None,
            {"type": "run_created", "data": {"task_id": "t"}},
            {"type": "lessons.shown", "data": "x"},
            shown(3, 1, "a", ["x"]),
            shown("t", 1, 5, ["x"]),
            shown("t", 1, "a", "x"),
            shown("t", "1", "a", ["x"]),
            shown("t", True, "a", ["x"]),
            shown("t", 0, "a", ["x"]),
            shown("t", 1, "a", ["ok", 7]),
        ]
        self.assertEqual(shown_lessons.by_task(events), {"t": ((1, "a", ("ok",)),)})

    def test_a_line_cut_short_is_skipped_when_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            whole = json.dumps(shown("t", 1, "a", ["x"]))
            path.write_text(whole + "\n" + whole[:20], encoding="utf-8")
            self.assertEqual(shown_lessons.read_events(path), [json.loads(whole)])
            self.assertEqual(shown_lessons.read_events(Path(temporary) / "missing"), [])


class LegacyRecordTests(unittest.TestCase):
    def test_only_a_task_from_3_0_0_writes_lessons_shown(self) -> None:
        legacy = TaskRecord(agent_id=AGENT, lessons_shown=("a",))
        self.assertEqual(TaskRecord.from_dict(legacy.to_dict()), legacy)
        self.assertNotIn("lessons_shown", TaskRecord(agent_id=AGENT).to_dict())

    def test_a_run_written_by_3_0_0_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = StateStore(Path(temporary) / "run-1")
            store.create("goal", Mode.EXECUTE, "run-1")
            task = TaskRecord(agent_id=AGENT, lessons_shown=("a",))
            store.update(lambda current: replace(current, tasks={"t": task}))
            self.assertEqual(store.load().tasks["t"].lessons_shown, ("a",))
