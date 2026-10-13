"""In-process checks of argument handling for ``run``, ``plan``, ``task``, ``exec`` and
``guard check``. The full flows are in ``tests/integration/test_cli_flow.py``."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from wev_skills import cli
from wev_skills.commands.task import read_evidence
from wev_skills.core.contracts import EvidenceLabel
from wev_skills.core.errors import NotFound, ValidationError


class OrchestrationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve()
        (self.work / "wev.json").write_text(json.dumps({"state_dir": "state"}), encoding="utf-8")
        (self.work / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)

    def run_cli(self, *argv: str) -> tuple[int, Any, Any]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--lang", "en", "--config", "wev.json", *argv])
        stdout = json.loads(out.getvalue()) if out.getvalue().strip() else None
        stderr = json.loads(err.getvalue())["error"] if err.getvalue().strip() else None
        return code, stdout, stderr

    def start(self, *extra: str) -> Any:
        code, out, err = self.run_cli(
            "run", "start", "--objective", "Do it", "--files", "1", "--run-id", "r1", *extra
        )
        self.assertEqual(code, 0, err)
        return out

    def test_commands_without_a_run_say_how_to_start_one(self) -> None:
        for argv in (
            ("run", "status"),
            ("task", "next"),
            ("plan", "show"),
            ("guard", "check"),
            ("exec", "--", "ls"),
        ):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli(*argv)
                self.assertEqual((code, err["code"]), (7, "no_active_run"))
                self.assertIn("wev run start", err["details"]["next_step"])

    def test_start_uses_the_given_id_and_the_latest_run_is_the_default(self) -> None:
        self.assertEqual(self.start()["run_id"], "r1")
        self.assertTrue((self.work / "state" / "runs" / "r1" / "state.json").is_file())
        code, status, _ = self.run_cli("run", "status")
        self.assertEqual((code, status["run_id"]), (0, "r1"))
        self.assertEqual(self.run_cli("run", "status", "--run", "other")[0], 7)

    def brief(self, *argv: str) -> tuple[int, str, Any]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--config", "wev.json", "run", "brief", *argv])
        error = json.loads(err.getvalue())["error"] if err.getvalue().strip() else None
        return code, out.getvalue(), error

    def test_brief_prints_plain_text_for_the_active_run(self) -> None:
        self.start()
        code, text, _ = self.brief("--lang", "en")
        self.assertEqual(code, 0)
        lines = text.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "wev run r1: mode auto, phase execute")
        self.assertEqual(lines[-1], "Next step: wev task next --run r1")
        self.assertIn("Objetivo: Do it", self.brief("--lang", "pt-BR")[1])
        self.assertLessEqual(len(self.brief("--max-chars", "90", "--lang", "en")[1].rstrip()), 90)
        self.assertEqual(self.brief("--max-chars", "5")[2]["code"], "invalid_max_chars")

    def test_brief_default_limit_comes_from_the_configuration(self) -> None:
        config = {"state_dir": "state", "harness": {"plan_reminder_max_chars": 100}}
        (self.work / "wev.json").write_text(json.dumps(config), encoding="utf-8")
        self.start()
        plan = {"objective": "x", "tasks": [
            {"id": f"t{n}", "title": "A fairly long task title", "objective": "o"} for n in range(9)
        ]}  # fmt: skip
        (self.work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        self.assertEqual(self.run_cli("plan", "set", "--file", "plan.json")[0], 0)
        code, text, _ = self.brief("--lang", "en")
        self.assertEqual(code, 0)
        self.assertLessEqual(len(text.rstrip("\n")), 100)

    def test_finish_ends_the_active_run_and_brief_then_finds_none(self) -> None:
        self.start()
        code, out, _ = self.run_cli("run", "finish")
        self.assertEqual((code, out["run_id"], out["phase"]), (0, "r1", "done"))
        code, text, error = self.brief()
        self.assertEqual((code, text, error["code"]), (7, "", "no_active_run"))
        code, text, _ = self.brief("--run", "r1", "--lang", "en")
        self.assertEqual(code, 0)
        self.assertIn("phase done", text)
        code, _, error = self.run_cli("run", "finish")
        self.assertEqual((code, error["code"]), (7, "no_active_run"))
        self.assertEqual(self.run_cli("run", "finish", "--run", "r1")[0], 0)
        code, _, error = self.run_cli("task", "next")
        self.assertEqual((code, error["code"]), (7, "no_active_run"))
        self.assertIn("wev run start", error["message"])
        code, _, error = self.run_cli("task", "next", "--run", "r1")
        self.assertEqual((code, error["code"]), (2, "run_finished"))
        self.assertEqual(self.run_cli("run", "status", "--run", "r1")[1]["phase"], "done")

    def test_start_needs_an_objective_and_rejects_resume_mode(self) -> None:
        code, _, err = self.run_cli("run", "start", "--files", "1")
        self.assertEqual((code, err["code"]), (2, "missing_objective"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["run", "start", "--objective", "x", "--mode", "resume"]), 2)

    def test_signals_file_is_accepted(self) -> None:
        (self.work / "signals.json").write_text(
            json.dumps({"objective": "Deploy", "touches_production": True}), encoding="utf-8"
        )
        code, out, _ = self.run_cli("run", "start", "--signals-file", "signals.json")
        self.assertEqual((code, out["classification"]["risk"]), (0, "high"))

    def test_exec_needs_a_command(self) -> None:
        self.start()
        code, _, err = self.run_cli("exec", "--")
        self.assertEqual((code, err["code"]), (2, "missing_command"))

    def test_guard_check_prints_the_verdict(self) -> None:
        self.start()
        code, verdict, _ = self.run_cli("guard", "check")
        self.assertEqual((code, verdict["action"], verdict["run_id"]), (0, "continue", "r1"))

    def test_missing_plan_file_and_unknown_task(self) -> None:
        self.start()
        self.assertEqual(self.run_cli("plan", "set", "--file", "nope.json")[0], 7)
        self.assertEqual(self.run_cli("task", "start", "ghost")[0], 7)
        code, plan, _ = self.run_cli("plan", "show")
        self.assertEqual((code, plan["plan"]), (0, None))

    def test_report_formats(self) -> None:
        self.start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                ["--config", "wev.json", "run", "report", "--format", "md", "--lang", "pt-BR"]
            )
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith("# Relatório de entrega: execução r1"))
        code, report, _ = self.run_cli("run", "report")
        self.assertEqual((code, report["status"]), (0, "incomplete"))

    def test_usage_errors(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in (
                ["run"],
                ["task", "record", "t"],
                ["task", "review", "t"],
                ["task", "record", "t", "--status", "done", "--summary", "x"],
                ["plan", "set"],
            ):
                with self.subTest(argv=argv):
                    self.assertEqual(cli.main(argv), 2)

    def test_evidence_file(self) -> None:
        self.assertEqual(read_evidence(None), ())
        path = self.work / "evidence.json"
        item = {"kind": "criterion:works", "summary": "ran it", "ref": "log.txt", "label": "tested"}
        path.write_text(json.dumps({"evidence": [item]}), encoding="utf-8")
        (evidence,) = read_evidence(str(path))
        self.assertEqual((evidence.ref, evidence.label), ("log.txt", EvidenceLabel.TESTED))
        for bad in (
            {"evidence": "x"},
            {},
            {"evidence": [{"kind": "k"}]},
            {"evidence": [{**item, "label": "proven"}]},
        ):
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                read_evidence(str(path))
        with self.assertRaises(NotFound):
            read_evidence(str(self.work / "missing.json"))

    def test_help_exists_in_both_languages(self) -> None:
        for lang, word in (("en", "Record the outcome"), ("pt-BR", "Registra o resultado")):
            out = io.StringIO()
            with (
                contextlib.redirect_stdout(out),
                self.assertRaises(SystemExit),
                cli.i18n.use_language(lang),
            ):
                cli.build_parser().parse_args(["task", "--help"])
            self.assertIn(word, out.getvalue())


if __name__ == "__main__":
    unittest.main()
