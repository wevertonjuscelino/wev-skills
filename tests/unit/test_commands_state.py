from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from wev_skills import cli
from wev_skills.core.contracts import Mode, TaskStatus
from wev_skills.state import model
from wev_skills.state.store import StateStore, run_dir


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class StateCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_dir = Path(tmp.name).resolve() / "wev-state"
        self.config = Path(tmp.name) / "config.json"
        self.config.write_text(json.dumps({"state_dir": str(self.state_dir)}), encoding="utf-8")

    def wev(self, *argv: str) -> tuple[int, str, str]:
        return run_main("--config", str(self.config), *argv)

    def make_run(self, run_id: str, objective: str, age: int) -> StateStore:
        store = StateStore(run_dir(self.state_dir, run_id))
        store.create(objective, Mode.EXECUTE)
        os.utime(store.state_path, ns=(age * 10**9, age * 10**9))
        return store

    def test_list_is_empty_without_runs(self) -> None:
        code, out, _ = self.wev("state", "list")
        self.assertEqual(code, 0)
        expected = {"state_dir": str(self.state_dir), "active": None, "latest": None, "runs": []}
        self.assertEqual(json.loads(out), expected)

    def test_list_summarizes_runs_and_names_the_latest(self) -> None:
        self.make_run("run-a", "first", 200)
        self.make_run("run-b", "second", 100)
        code, out, _ = self.wev("state", "list")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["latest"], "run-a")
        self.assertEqual([r["run_id"] for r in data["runs"]], ["run-a", "run-b"])
        self.assertEqual(data["runs"][1]["objective"], "second")
        self.assertEqual(data["runs"][0]["phase"], "request")

    def test_list_reports_a_corrupt_run_without_failing(self) -> None:
        store = self.make_run("run-a", "first", 100)
        store.state_path.write_text("{broken", encoding="utf-8")
        code, out, _ = self.wev("state", "list")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["runs"][0]["error"]["code"], "state_corrupt")

    def test_show_defaults_to_the_latest_run_and_accepts_run(self) -> None:
        self.make_run("run-a", "first", 100)
        self.make_run("run-b", "second", 200)
        code, out, _ = self.wev("state", "show")
        self.assertEqual((code, json.loads(out)["objective"]), (0, "second"))
        code, out, _ = self.wev("state", "show", "--run", "run-a")
        self.assertEqual((code, json.loads(out)["run_id"]), (0, "run-a"))

    def test_show_errors(self) -> None:
        code, _, err = self.wev("state", "show")
        self.assertEqual((code, json.loads(err)["error"]["code"]), (7, "no_active_run"))
        code, _, err = self.wev("state", "show", "--run", "missing")
        self.assertEqual((code, json.loads(err)["error"]["code"]), (7, "state_not_found"))
        code, _, err = self.wev("state", "show", "--run", "../../etc")
        self.assertEqual((code, json.loads(err)["error"]["code"]), (2, "invalid_run_id"))

    def test_show_corrupt_state_is_a_validation_error(self) -> None:
        store = self.make_run("run-a", "first", 100)
        store.state_path.write_text("{broken", encoding="utf-8")
        code, _, err = self.wev("state", "show")
        self.assertEqual((code, json.loads(err)["error"]["code"]), (2, "state_corrupt"))

    def test_drift_reports_running_tasks_for_reverification(self) -> None:
        store = self.make_run("run-a", "first", 100)
        store.update(lambda s: model.with_task(s, "t1"))
        store.update(lambda s: model.with_task_status(s, "t1", TaskStatus.RUNNING))
        code, out, _ = self.wev("state", "drift", "--run", "run-a")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((data["run_id"], data["drifted"]), ("run-a", True))
        self.assertEqual(data["stale_running_tasks"], ["t1"])

    def test_help_is_translated(self) -> None:
        code, out, _ = run_main("--lang", "pt-BR", "state", "--help")
        self.assertEqual(code, 0)
        self.assertIn("Lista as execuções", out)


if __name__ == "__main__":
    unittest.main()
