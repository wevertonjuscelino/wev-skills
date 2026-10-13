from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.unit.test_evaluation_tasks import task_data
from wev_skills import cli
from wev_skills.evaluation import report
from wev_skills.evaluation import tasks as eval_tasks


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class EvalCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_list_shows_shipped_tasks_and_configs(self) -> None:
        code, out, _ = run_main("--lang", "en", "eval", "list")
        self.assertEqual(code, 0)
        listing = json.loads(out)
        self.assertGreaterEqual(len(listing["tasks"]), 6)
        self.assertIn("baseline", [config["id"] for config in listing["configs"]])
        keys = {"id", "title", "category", "window_tokens", "subtasks", "steps"}
        self.assertEqual(set(listing["tasks"][0]), keys)

    def test_run_prints_json_with_the_notice_for_the_selection(self) -> None:
        code, out, _ = run_main(
            "--lang",
            "en",
            "eval",
            "run",
            "--task",
            "simple-fix",
            "--config",
            "baseline",
            "--config",
            "attempts-1",
        )
        self.assertEqual(code, 0)
        document = json.loads(out)
        self.assertEqual(document["notice"], report.notice("en"))
        self.assertEqual(document["task_ids"], ["simple-fix"])
        self.assertEqual([run["config_id"] for run in document["runs"]], ["baseline", "attempts-1"])

    def test_run_markdown_in_portuguese(self) -> None:
        code, out, _ = run_main(
            "eval",
            "run",
            "--task",
            "simple-fix",
            "--config",
            "baseline",
            "--format",
            "md",
            "--lang",
            "pt-BR",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual((payload["format"], payload["language"]), ("md", "pt-BR"))
        self.assertTrue(payload["content"].startswith("> Aviso:"))
        self.assertIn("Agregado por configuração", payload["content"])

    def test_out_writes_exactly_what_stdout_would_print(self) -> None:
        target = self.root / "nested" / "report.json"
        selection = ("--task", "failing-test", "--config", "attempts-1", "--config", "attempts-2")
        code, out, _ = run_main("--lang", "en", "eval", "run", *selection, "--out", str(target))
        self.assertEqual(code, 0)
        summary = json.loads(out)
        self.assertEqual((summary["written"], summary["runs"]), (str(target), 2))
        self.assertIn("scripted agent", summary["notice"])
        _, printed, _ = run_main("--lang", "en", "eval", "run", *selection)
        self.assertEqual(target.read_text(encoding="utf-8"), printed)

    def test_unknown_ids_are_not_found(self) -> None:
        for flag in ("--task", "--config"):
            code, _, err = run_main("--lang", "en", "eval", "run", flag, "ghost")
            self.assertEqual(code, 7, flag)
            error = json.loads(err)["error"]
            self.assertEqual(error["code"], "eval_id_not_found")
            self.assertEqual(error["details"]["missing"], ["ghost"])

    def test_validate_good_bad_and_missing_files(self) -> None:
        good = self.root / "good.json"
        good.write_text(json.dumps(task_data()))
        code, out, _ = run_main("--lang", "en", "eval", "validate", str(good))
        result = json.loads(out)
        self.assertEqual((code, result["valid"], result["id"]), (0, True, "sample"))
        bad = self.root / "bad.json"
        bad.write_text(json.dumps(task_data(category="nope")))
        code, _, err = run_main("--lang", "en", "eval", "validate", str(bad))
        self.assertEqual((code, json.loads(err)["error"]["code"]), (2, "schema_validation_failed"))
        inconsistent = task_data()
        inconsistent["script"][1]["criteria"] = ["ghost"]
        bad.write_text(json.dumps(inconsistent))
        code, _, err = run_main("--lang", "en", "eval", "validate", str(bad))
        self.assertEqual((code, json.loads(err)["error"]["code"]), (2, "invalid_eval_task"))
        code, _, _ = run_main("--lang", "en", "eval", "validate", str(self.root / "none.json"))
        self.assertEqual(code, 7)

    def test_shipped_task_files_validate(self) -> None:
        for path in sorted((eval_tasks.EVALS_DIR / eval_tasks.TASKS_SUBDIR).glob("*.json")):
            code, _, err = run_main("--lang", "en", "eval", "validate", str(path))
            self.assertEqual(code, 0, err)

    def test_missing_evals_directory_is_a_clear_not_found(self) -> None:
        with mock.patch.object(eval_tasks, "EVALS_DIR", self.root / "absent"):
            for command in (("list",), ("run",)):
                code, _, err = run_main("--lang", "en", "eval", *command)
                self.assertEqual(code, 7, command)
                error = json.loads(err)["error"]
                self.assertEqual(error["code"], "evals_dir_not_found")
                self.assertIn("--tasks-dir", error["message"])

    def test_explicit_sources_work_without_the_evals_directory(self) -> None:
        tasks_dir = self.root / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "sample.json").write_text(json.dumps(task_data()))
        configs = self.root / "configs.json"
        configs.write_text(json.dumps({"configs": [{"id": "only"}]}))
        with mock.patch.object(eval_tasks, "EVALS_DIR", self.root / "absent"):
            code, out, err = run_main(
                "--lang",
                "en",
                "eval",
                "run",
                "--tasks-dir",
                str(tasks_dir),
                "--configs",
                str(configs),
            )
        self.assertEqual(code, 0, err)
        document = json.loads(out)
        self.assertEqual(document["aggregates"][0]["successes"], 1)
        self.assertEqual(document["runs"][0]["counts"]["criteria_met"], 1)


if __name__ == "__main__":
    unittest.main()
