"""``run finish`` scores the project specialists the run used, only when the owner opted in."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from wev_skills import cli
from wev_skills.core.contracts import TaskStatus
from wev_skills.core.errors import ValidationError
from wev_skills.state import model
from wev_skills.state.store import StateStore


def _report(agent_id: str) -> Any:
    return SimpleNamespace(to_dict=lambda: {"agent_id": agent_id})


class ScoreOnFinishTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve()
        (self.work / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)

    def finish(
        self,
        on: bool,
        agents: dict[str, str],
        score: Any,
        statuses: dict[str, TaskStatus] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        statuses = statuses or {}
        config = {"state_dir": "state", "specialists": {"score_on_finish": on}}
        (self.work / "wev.json").write_text(json.dumps(config), encoding="utf-8")
        self.run_cli("run", "start", "--objective", "x", "--files", "1", "--run-id", "r1")
        store = StateStore(self.work / "state" / "runs" / "r1")

        def add(state: model.RunState) -> model.RunState:
            for task_id in agents:
                state = model.with_task(state, task_id)
            tasks = {
                t: dataclasses.replace(
                    state.tasks[t], agent_id=a, status=statuses.get(t, TaskStatus.VERIFIED)
                )
                for t, a in agents.items()
            }
            return dataclasses.replace(state, tasks={**state.tasks, **tasks})

        store.update(add)
        specs = [SimpleNamespace(id="spec-a"), SimpleNamespace(id="spec-b")]
        with (
            mock.patch("wev_skills.commands.run.project.list_specs", return_value=specs),
            mock.patch("wev_skills.commands._scoring.score", side_effect=score) as called,
        ):
            code, out = self.run_cli("run", "finish")
        self.calls = called.call_args_list
        return code, out

    def run_cli(self, *argv: str) -> tuple[int, dict[str, Any]]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--lang", "en", "--config", "wev.json", *argv])
        return code, json.loads(out.getvalue()) if out.getvalue().strip() else {}

    def test_off_by_default_never_calls_score(self) -> None:
        def fail(*_: Any) -> Any:
            raise AssertionError("score must not run")

        code, out = self.finish(False, {"T-1": "spec-a"}, fail)
        self.assertEqual((code, out["phase"]), (0, "done"))
        self.assertNotIn("scores", out)
        self.assertEqual(self.calls, [])

    def test_scores_each_used_project_specialist_once(self) -> None:
        agents = {"T-1": "spec-a", "T-2": "spec-b", "T-3": "spec-a", "T-4": "catalog-agent"}
        code, out = self.finish(True, agents, lambda _scope, agent_id: _report(agent_id))
        self.assertEqual(code, 0)
        self.assertEqual([c.args[1] for c in self.calls], ["spec-a", "spec-b"])
        self.assertEqual([s["agent_id"] for s in out["scores"]], ["spec-a", "spec-b"])
        self.assertEqual(out["score_errors"], [])

    def test_failing_scores_are_reported_and_the_run_stays_done(self) -> None:
        def score(_scope: Any, agent_id: str) -> Any:
            if agent_id == "spec-a":
                raise ValidationError("score_no_cases", "no cases")
            raise RuntimeError("boom")

        code, out = self.finish(True, {"T-1": "spec-a", "T-2": "spec-b"}, score)
        self.assertEqual((code, out["phase"], out["scores"]), (0, "done", []))
        self.assertEqual(
            [(e["specialist"], e["code"]) for e in out["score_errors"]],
            [("spec-a", "score_no_cases"), ("spec-b", "score_failed")],
        )

    def test_only_specialists_with_an_ended_task_are_scored(self) -> None:
        agents = {"T-1": "spec-a", "T-2": "spec-b"}
        states = {"T-1": TaskStatus.PENDING, "T-2": TaskStatus.FAILED}
        _, out = self.finish(True, agents, lambda _s, a: _report(a), states)
        self.assertEqual([s["agent_id"] for s in out["scores"]], ["spec-b"])

    def test_a_repeated_finish_does_not_score_again(self) -> None:
        self.finish(True, {"T-1": "spec-a"}, lambda _s, a: _report(a))
        with mock.patch("wev_skills.commands._scoring.score") as called:
            code, out = self.run_cli("run", "finish", "--run", "r1")
        self.assertEqual((code, called.call_count, "scores" in out), (0, 0, False))

    def test_an_unregistered_run_is_refused_and_not_scored(self) -> None:
        with mock.patch("wev_skills.core.active.is_registered", return_value=False):
            code, out = self.finish(True, {"T-1": "spec-a"}, lambda _s, a: _report(a))
        self.assertNotEqual(code, 0)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
