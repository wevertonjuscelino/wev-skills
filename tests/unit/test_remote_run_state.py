from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from wev_skills.core.errors import WevError
from wev_skills.remote.records import StateRunRecords
from wev_skills.remote.session import RemoteRun
from wev_skills.state import StateStore
from wev_skills.state.model import RunState, with_remote_run
from wev_skills.state.records import RemoteRunRecord


def remote_run(task: str = "t1", alias: str = "dev", started: float = 1.0) -> RemoteRun:
    return RemoteRun(
        task_id=task,
        alias=alias,
        session=f"wev-{task}-{alias}",
        argv=("make", "build"),
        started_at=started,
        log_path="/tmp/x.log",
        exit_path="/tmp/x.exit",
        owner_token="token",
    )


class WithRemoteRunTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = StateStore(Path(tmp.name) / "run1")
        self.state = self.store.create("objective", "execute", run_id="run1")

    def test_a_new_state_has_no_remote_runs(self) -> None:
        self.assertEqual(self.state.remote_runs, ())

    def test_records_are_added_and_replace_the_same_task_and_host(self) -> None:
        first = RemoteRunRecord.from_dict(remote_run().to_dict())
        second = RemoteRunRecord.from_dict(remote_run(started=2.0).to_dict())
        other = RemoteRunRecord.from_dict(remote_run(alias="prod").to_dict())
        state = with_remote_run(with_remote_run(self.state, first), other)
        state = with_remote_run(state, second)
        self.assertEqual(
            [(r.alias, r.started_at) for r in state.remote_runs], [("prod", 1.0), ("dev", 2.0)]
        )

    def test_state_without_the_field_still_loads(self) -> None:
        data = self.state.to_dict()
        del data["remote_runs"]
        self.assertEqual(RunState.from_dict(data).remote_runs, ())

    def test_round_trip_through_the_store(self) -> None:
        record = RemoteRunRecord.from_dict(remote_run().to_dict())
        self.store.update(lambda s: with_remote_run(s, record))
        self.assertEqual(self.store.load().remote_runs, (record,))


class StateRunRecordsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = StateStore(Path(tmp.name) / "run1")
        self.store.create("objective", "execute", run_id="run1")
        self.records = StateRunRecords(self.store)

    def test_find_returns_none_before_any_start(self) -> None:
        self.assertIsNone(self.records.find("t1", "dev"))

    def test_record_then_find_returns_the_same_run(self) -> None:
        run = remote_run()
        self.records.record(run)
        self.assertEqual(self.records.find("t1", "dev"), run)
        self.assertIsNone(self.records.find("t1", "prod"))

    def test_a_restart_replaces_the_earlier_record(self) -> None:
        self.records.record(remote_run(started=1.0))
        later = replace(remote_run(), started_at=5.0)
        self.records.record(later)
        self.assertEqual(self.records.find("t1", "dev"), later)
        self.assertEqual(len(self.store.load().remote_runs), 1)

    def test_a_damaged_state_is_an_error_for_find_and_record(self) -> None:
        self.store.state_path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(WevError):
            self.records.find("t1", "dev")
        with self.assertRaises(WevError):
            self.records.record(remote_run())
        self.assertEqual(self.store.state_path.read_text(encoding="utf-8"), "{ not json")

    def test_nothing_is_written_to_a_separate_file(self) -> None:
        self.records.record(remote_run())
        self.assertFalse(list(self.store.run_dir.parent.rglob("remote-runs.json")))
        written = json.loads(self.store.state_path.read_text(encoding="utf-8"))
        self.assertEqual(len(written["remote_runs"]), 1)


if __name__ == "__main__":
    unittest.main()
