from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import wev_skills
from wev_skills.core.contracts import Mode, TaskStatus
from wev_skills.core.errors import NotFound, StateConflict, ValidationError
from wev_skills.state import model
from wev_skills.state.model import RUN_ID_RE, RunState
from wev_skills.state.store import (
    StateStore,
    latest_run,
    list_runs,
    new_run_id,
    run_dir,
)

SRC = str(Path(wev_skills.__file__).resolve().parents[1])
WORKERS = 4
UPDATES_PER_WORKER = 25
WORKER_SCRIPT = """
import sys
from wev_skills.state import model
from wev_skills.state.store import StateStore

store = StateStore(sys.argv[1])
for _ in range(int(sys.argv[2])):
    store.update(lambda s: model.with_discovery(s, "counter", s.discovery.get("counter", 0) + 1))
"""


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.value = start

    def now(self) -> float:
        self.value += 1.0
        return self.value


def bump(state: RunState) -> RunState:
    return model.with_discovery(state, "counter", state.discovery.get("counter", 0) + 1)


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.store = StateStore(self.tmp / "runs" / "run-1", FakeClock())


class CreateLoadTests(StoreCase):
    def test_create_writes_revision_one_and_load_reads_it_back(self) -> None:
        self.assertFalse(self.store.exists())
        created = self.store.create("ship it", Mode.EXECUTE)
        self.assertTrue(self.store.exists())
        self.assertEqual((created.revision, created.run_id), (1, "run-1"))
        self.assertEqual(created.created_at, created.updated_at)
        self.assertEqual(self.store.load(), created)

    def test_create_accepts_mode_string_and_explicit_run_id(self) -> None:
        created = self.store.create("x", "plan", run_id="custom.id-1")
        self.assertEqual((created.mode, created.run_id), (Mode.PLAN, "custom.id-1"))

    def test_create_twice_raises_state_conflict_and_keeps_first(self) -> None:
        first = self.store.create("first", Mode.AUTO)
        with self.assertRaises(StateConflict):
            self.store.create("second", Mode.AUTO)
        self.assertEqual(self.store.load(), first)

    def test_create_rejects_bad_input(self) -> None:
        for objective, mode, run_id in (
            ("", "plan", None),
            ("x", "yolo", None),
            ("x", "plan", "../escape"),
            ("x", "plan", ".."),
            ("x", "plan", "a/b"),
            ("x", "plan", "a\\b"),
        ):
            with self.subTest(run_id=run_id, mode=mode), self.assertRaises(ValidationError):
                self.store.create(objective, mode, run_id=run_id)
        self.assertFalse(self.store.exists())

    def test_state_file_and_directory_are_private(self) -> None:
        self.store.create("x", Mode.PLAN)
        self.assertEqual(self.store.state_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.run_dir.stat().st_mode & 0o777, 0o700)

    def test_load_without_state_raises_not_found(self) -> None:
        with self.assertRaises(NotFound):
            self.store.load()

    def test_corrupt_file_raises_validation_error_and_is_left_untouched(self) -> None:
        self.store.create("x", Mode.PLAN)
        for garbage in ("{not json", "[1, 2]", '{"schema_version": 1, "revision": "one"}'):
            with self.subTest(garbage=garbage):
                self.store.state_path.write_text(garbage, encoding="utf-8")
                with self.assertRaises(ValidationError) as caught:
                    self.store.load()
                self.assertEqual(caught.exception.code, "state_corrupt")
                self.assertIn("untouched", caught.exception.message)
                with self.assertRaises(ValidationError):
                    self.store.update(bump)
                self.assertEqual(self.store.state_path.read_text(encoding="utf-8"), garbage)

    def test_wrong_version_raises_clear_error_and_is_left_untouched(self) -> None:
        self.store.create("x", Mode.PLAN)
        data = json.loads(self.store.state_path.read_text(encoding="utf-8"))
        text = json.dumps({**data, "schema_version": 2})
        self.store.state_path.write_text(text, encoding="utf-8")
        with self.assertRaises(ValidationError) as caught:
            self.store.load()
        self.assertEqual(caught.exception.code, "state_version_unsupported")
        self.assertIn("schema_version 2", caught.exception.message)
        self.assertEqual(self.store.state_path.read_text(encoding="utf-8"), text)


class UpdateTests(StoreCase):
    def test_update_bumps_revision_and_updated_at(self) -> None:
        created = self.store.create("x", Mode.EXECUTE)
        updated = self.store.update(lambda s: model.with_next_step(s, "plan"))
        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.next_step, "plan")
        self.assertEqual(updated.created_at, created.created_at)
        self.assertGreater(updated.updated_at, created.updated_at)
        self.assertEqual(self.store.load(), updated)

    def test_update_reads_latest_state_from_disk_not_a_stale_copy(self) -> None:
        self.store.create("x", Mode.EXECUTE)
        other = StateStore(self.store.run_dir, FakeClock())
        other.update(bump)
        self.assertEqual(self.store.update(bump).discovery["counter"], 2)

    def test_expected_revision_mismatch_raises_state_conflict(self) -> None:
        self.store.create("x", Mode.EXECUTE)
        self.store.update(bump, expected_revision=1)
        before = self.store.state_path.read_text(encoding="utf-8")
        with self.assertRaises(StateConflict) as caught:
            self.store.update(bump, expected_revision=1)
        self.assertEqual(caught.exception.details, {"expected": 1, "found": 2})
        self.assertEqual(self.store.state_path.read_text(encoding="utf-8"), before)
        self.assertEqual(self.store.update(bump, expected_revision=2).revision, 3)

    def test_failing_mutator_leaves_previous_state_and_no_temp_files(self) -> None:
        self.store.create("x", Mode.EXECUTE)
        self.store.update(bump)
        before = self.store.state_path.read_text(encoding="utf-8")

        def crash(state: RunState) -> RunState:
            raise RuntimeError("crash mid-update")

        with self.assertRaises(RuntimeError):
            self.store.update(crash)
        self.assertEqual(self.store.state_path.read_text(encoding="utf-8"), before)
        self.assertEqual([p.name for p in self.store.run_dir.glob(".*.tmp")], [])
        self.assertEqual(self.store.update(bump).revision, 3)

    def test_crash_between_temp_write_and_replace_keeps_previous_state(self) -> None:
        self.store.create("x", Mode.EXECUTE)
        before = self.store.state_path.read_text(encoding="utf-8")
        with mock.patch("os.replace", side_effect=OSError("power cut")), self.assertRaises(OSError):
            self.store.update(bump)
        self.assertEqual(self.store.state_path.read_text(encoding="utf-8"), before)
        self.assertEqual([p.name for p in self.store.run_dir.glob(".*.tmp")], [])
        self.assertEqual(self.store.update(bump).revision, 2)

    def test_invalid_mutator_results_are_rejected_and_state_is_kept(self) -> None:
        self.store.create("x", Mode.EXECUTE)
        before = self.store.state_path.read_text(encoding="utf-8")
        bad_mutators = (
            lambda s: None,
            lambda s: replace(s, run_id="other"),
            lambda s: replace(s, created_at="1999"),
            lambda s: replace(s, objective=""),
            lambda s: model.with_discovery(s, "env", {"SECRET": "x"}),
            lambda s: model.with_task_status(s, "ghost", TaskStatus.RUNNING),
        )
        for mutator in bad_mutators:
            with self.assertRaises(ValidationError):
                self.store.update(mutator)  # type: ignore[arg-type]
        self.assertEqual(self.store.state_path.read_text(encoding="utf-8"), before)

    def test_mutator_cannot_set_revision(self) -> None:
        self.store.create("x", Mode.EXECUTE)
        self.assertEqual(self.store.update(lambda s: replace(s, revision=40)).revision, 2)


class ConcurrencyTests(StoreCase):
    def test_parallel_processes_lose_no_update_and_file_is_always_valid_json(self) -> None:
        self.store.create("count", Mode.EXECUTE)
        env = {**os.environ, "PYTHONPATH": SRC}
        target, count = str(self.store.run_dir), str(UPDATES_PER_WORKER)
        argv = [sys.executable, "-c", WORKER_SCRIPT, target, count]
        stop = threading.Event()
        problems: list[str] = []
        reads = [0]

        def read_continuously() -> None:
            while not stop.is_set():
                try:
                    json.loads(self.store.state_path.read_text(encoding="utf-8"))
                    reads[0] += 1
                except (OSError, ValueError) as exc:
                    problems.append(repr(exc))

        reader = threading.Thread(target=read_continuously)
        reader.start()
        try:
            workers = [
                subprocess.Popen(argv, env=env, stderr=subprocess.PIPE) for _ in range(WORKERS)
            ]
            failures = [w.communicate(timeout=120)[1] for w in workers]
        finally:
            stop.set()
            reader.join()
        self.assertEqual([w.returncode for w in workers], [0] * WORKERS, failures)
        self.assertEqual(problems, [])
        self.assertGreater(reads[0], 0)
        final = self.store.load()
        total = WORKERS * UPDATES_PER_WORKER
        self.assertEqual(final.discovery["counter"], total)
        self.assertEqual(final.revision, 1 + total)

    def test_parallel_event_appends_are_not_interleaved(self) -> None:
        script = (
            "import sys\nfrom wev_skills.state.store import StateStore\n"
            "s = StateStore(sys.argv[1])\n"
            "for i in range(20):\n    s.append_event('tick', {'i': i, 'pad': 'x' * 2000})\n"
        )
        env = {**os.environ, "PYTHONPATH": SRC}
        argv = [sys.executable, "-c", script, str(self.store.run_dir)]
        workers = [subprocess.Popen(argv, env=env) for _ in range(WORKERS)]
        self.assertEqual([w.wait(timeout=120) for w in workers], [0] * WORKERS)
        self.assertEqual(len(self.store.events()), WORKERS * 20)


class EventTests(StoreCase):
    def test_create_and_append_event_write_json_lines(self) -> None:
        self.store.create("x", Mode.PLAN)
        self.store.append_event("phase_changed", {"to": "plan"})
        events = self.store.events()
        self.assertEqual([e["type"] for e in events], ["run_created", "phase_changed"])
        self.assertEqual(events[1]["data"], {"to": "plan"})
        self.assertTrue(events[1]["at"].endswith("Z"))
        lines = self.store.events_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)

    def test_append_event_rejects_bad_type_and_environment(self) -> None:
        bad = (("", {}), ("x", {"env": {"A": "b"}}), ("x", os.environ), ("x", [1]))
        for event_type, data in bad:
            with self.assertRaises(ValidationError):
                self.store.append_event(event_type, data)  # type: ignore[arg-type]
        self.assertEqual(self.store.events(), [])


class RunListingTests(StoreCase):
    def test_new_run_id_is_utc_timestamp_plus_suffix_and_directory_safe(self) -> None:
        first, second = new_run_id(FakeClock(0.0)), new_run_id(FakeClock(0.0))
        self.assertRegex(first, r"^19700101T000001Z-[0-9a-f]{6}$")
        self.assertNotEqual(first, second)
        self.assertTrue(RUN_ID_RE.match(first))

    def test_generated_id_is_used_when_directory_name_is_not_a_valid_id(self) -> None:
        store = StateStore(self.tmp / "bad name", FakeClock(0.0))
        self.assertRegex(store.create("x", Mode.PLAN).run_id, r"^19700101T\d{6}Z-[0-9a-f]{6}$")

    def test_run_dir_rejects_unsafe_ids(self) -> None:
        self.assertEqual(run_dir(self.tmp, "r1"), self.tmp / "runs" / "r1")
        for bad in ("..", ".", "a/b", "../r1", "", "a\\b"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                run_dir(self.tmp, bad)

    def test_list_and_latest(self) -> None:
        self.assertEqual(list_runs(self.tmp), [])
        self.assertIsNone(latest_run(self.tmp))
        for index, name in enumerate(("b-run", "a-run", "c-run")):
            store = StateStore(run_dir(self.tmp, name), FakeClock())
            store.create("x", Mode.PLAN)
            os.utime(store.state_path, ns=(index * 10**9, index * 10**9))
        (self.tmp / "runs" / "empty-dir").mkdir()
        (self.tmp / "runs" / "stray.txt").write_text("x", encoding="utf-8")
        os.symlink(self.tmp / "runs" / "a-run", self.tmp / "runs" / "linked")
        self.assertEqual(list_runs(self.tmp), ["a-run", "b-run", "c-run"])
        self.assertEqual(latest_run(self.tmp), "c-run")
        os.utime(self.tmp / "runs" / "a-run" / "state.json", ns=(99 * 10**9, 99 * 10**9))
        self.assertEqual(latest_run(self.tmp), "a-run")


if __name__ == "__main__":
    unittest.main()
