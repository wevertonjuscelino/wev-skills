"""Specialist observations are evidence-derived, bounded and replay-idempotent."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from wev_skills.agents import learning, project
from wev_skills.config import parse_config
from wev_skills.core.contracts import Mode, TaskStatus
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.core.wiring import build_agents
from wev_skills.state.model import RepoSnapshot, RunState, TaskRecord
from wev_skills.state.records import CheckOutcome, VerificationRecord
from wev_skills.state.store import StateStore, run_dir


def recorded(run_id: str, passed: bool = True) -> RunState:
    check = CheckOutcome(
        "test-1",
        ("python3", "-m", "unittest"),
        "passed" if passed else "failed",
        0 if passed else 1,
        "logs/check",
    )
    task = TaskRecord(
        status=TaskStatus.VERIFIED if passed else TaskStatus.FAILED,
        agent_id="project-test",
    )
    report = VerificationRecord(
        "project-test",
        "2026-10-13T12:00:00Z",
        passed,
        "untrusted summary must not become a lesson",
        (check,),
    )
    return RunState(
        run_id,
        "goal",
        Mode.EXECUTE,
        run_id,
        run_id,
        tasks={"project-test": task},
        verifications=(report,),
    )


class LearningTests(unittest.TestCase):
    def test_replay_counters_and_contradiction(self) -> None:
        first, failed = recorded("run-1"), recorded("run-2", False)
        lessons = learning.derive((first, failed, first), "project-test")
        self.assertEqual(len(lessons), 1)
        self.assertEqual((lessons[0].confirmations, lessons[0].contradictions), (1, 1))
        self.assertNotIn("untrusted summary", lessons[0].text)
        self.assertEqual(learning.derive((first, failed), "project-test"), lessons)

    def test_unverified_success_teaches_nothing(self) -> None:
        state = recorded("run-1")
        task = replace(state.tasks["project-test"], status=TaskStatus.RUNNING)
        self.assertEqual(
            learning.derive((replace(state, tasks={"project-test": task}),), "project-test"), ()
        )

    def test_trivial_check_teaches_nothing(self) -> None:
        state = recorded("run-1")
        report = replace(
            state.verifications[0],
            checks=(replace(state.verifications[0].checks[0], trivial=True),),
        )
        self.assertEqual(
            learning.derive((replace(state, verifications=(report,)),), "project-test"), ()
        )

    def test_pruning_hard_cap(self) -> None:
        lesson = learning.derive((recorded("run-1"),), "project-test")[0]
        many = tuple(replace(lesson, id=f"lesson-{index}") for index in range(40))
        self.assertEqual(len(learning.reconcile((), many, 100)), 30)

    def test_create_discover_export_and_no_permission_growth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, config = Path(temporary).resolve(), parse_config()
            parent = build_agents(config, root).resolved("senior-engineer")
            spec = project.create(root, config, "project-test", "senior-engineer", ("widgets",))
            self.assertEqual(spec.permissions, parent.permissions)
            self.assertEqual(spec.tools, parent.tools)
            self.assertIn(spec.id, build_agents(config, root).registry)
            files = project.export(root, config, "en")
            self.assertEqual(files, [root / ".claude" / "agents" / "project-test.md"])
            self.assertEqual(project.learn(root, config, spec.id).experience, ())
            with self.assertRaises(ValidationError):
                project.create(root, config, "project-test", "senior-engineer", ())

    def test_learning_counts_the_lessons_shown_in_the_run_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, config = Path(temporary).resolve(), parse_config()
            project.create(root, config, "project-test", "senior-engineer", ())
            store = StateStore(run_dir(root / ".wev", "run-1"))
            store.create("goal", Mode.EXECUTE, "run-1")
            source = recorded("run-1")
            store.update(
                lambda current: replace(
                    current,
                    tasks=source.tasks,
                    verifications=source.verifications,
                    repo=RepoSnapshot(str(root), "main", "abc"),
                )
            )
            lesson_id = project.learn(root, config, "project-test").experience[0].id
            data = {"task_id": "project-test", "agent_id": "project-test"}
            store.append_event("lessons.shown", {**data, "lessons": [lesson_id]})
            other = StateStore(run_dir(root / ".wev", "run-2"))
            other.create("goal", Mode.EXECUTE, "run-2")
            other.update(
                lambda current: replace(current, repo=RepoSnapshot("/elsewhere", "m", "a"))
            )
            other.events_path.write_text("not json\n", encoding="utf-8")
            counted = project.learn(root, config, "project-test").experience[0]
            self.assertEqual((counted.shown_verified, counted.shown_unverified), (1, 0))

    def test_learning_persisted_history_preserves_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, config = Path(temporary).resolve(), parse_config()
            original = project.create(root, config, "project-test", "senior-engineer", ())
            store = StateStore(run_dir(root / ".wev", "run-1"))
            store.create("goal", Mode.EXECUTE, "run-1")
            source = recorded("run-1")
            store.update(
                lambda current: replace(
                    current,
                    tasks=source.tasks,
                    verifications=source.verifications,
                    repo=RepoSnapshot(str(root), "main", "abc"),
                )
            )
            learned = project.learn(root, config, "project-test")
            self.assertEqual(len(learned.experience), 1)
            self.assertEqual(learned.experience[0].confirmations, 1)
            self.assertEqual(project.learn(root, config, "project-test"), learned)
            self.assertEqual(learned.permissions, original.permissions)
            self.assertEqual(learned.tools, original.tools)

    def test_shared_state_does_not_mix_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            first, second = base / "first", base / "second"
            first.mkdir()
            second.mkdir()
            config = parse_config(overrides={"state_dir": str(base / "state")})
            for root in (first, second):
                project.create(root, config, "project-test", "senior-engineer", ())
            store = StateStore(run_dir(base / "state", "run-1"))
            store.create("goal", Mode.EXECUTE, "run-1")
            source = recorded("run-1")
            store.update(
                lambda current: replace(
                    current,
                    tasks=source.tasks,
                    verifications=source.verifications,
                    repo=RepoSnapshot(str(first), "main", "abc"),
                )
            )
            self.assertEqual(len(project.learn(first, config, "project-test").experience), 1)
            self.assertEqual(project.learn(second, config, "project-test").experience, ())

    def test_symlink_learning_cannot_write_another_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, config = Path(temporary).resolve(), parse_config()
            project.create(root, config, "original", "senior-engineer", ())
            target = root / "wev-specialists" / "original.json"
            before = target.read_bytes()
            (target.parent / "alias.json").symlink_to(target)
            with self.assertRaises(PermissionDenied):
                project.learn(root, config, "alias")
            self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
