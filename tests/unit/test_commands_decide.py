from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from wev_skills import cli


def run_main(*argv: str) -> tuple[int, dict, str]:  # type: ignore[type-arg]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    text = out.getvalue()
    return code, json.loads(text) if text.strip() else {}, err.getvalue()


class DecideCommandTests(unittest.TestCase):
    def test_classify_flags(self) -> None:
        code, data, _ = run_main("classify", "--objective", "x", "--files", "2", "--production")
        self.assertEqual(code, 0)
        self.assertEqual(data["risk"], "high")
        self.assertEqual(data["source"], "local-policy")

    def test_classify_all_flags(self) -> None:
        code, data, _ = run_main(
            "classify",
            "--objective",
            "x",
            "--no-tests",
            "--irreversible",
            "--remote",
            "--destructive",
            "--external",
            "--unknowns",
            "5",
            "--subtasks",
            "3",
        )
        self.assertEqual(code, 0)
        self.assertEqual((data["complexity"], data["parallelizable"]), ("complex", True))
        self.assertEqual(data["uncertainty"], 1.0)

    def test_signals_file_with_flag_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "s.json")
            path.write_text(json.dumps({"objective": "x", "destructive": True}), encoding="utf-8")
            _, data, _ = run_main("classify", "--signals-file", str(path))
            self.assertEqual(data["risk"], "high")
            _, data, _ = run_main("classify", "--signals-file", str(path), "--files", "1")
            self.assertEqual(data["risk"], "high")

    def test_strategy_reports_the_executor_tier_and_accepts_an_override(self) -> None:
        argv = ("strategy", "--objective", "x", "--files", "2")
        _, routed, _ = run_main(*argv)
        self.assertEqual(
            (routed["executor_tier"], routed["strategy"]["needs_plan"]), ("standard", False)
        )
        _, weak, _ = run_main(*argv, "--executor-tier", "economy")
        self.assertEqual((weak["executor_tier"], weak["strategy"]["needs_plan"]), ("economy", True))
        self.assertIn("Executor tier economy", " ".join(weak["strategy"]["reasons"]))

    def test_missing_objective_is_error(self) -> None:
        code, _, err = run_main("classify", "--files", "1")
        self.assertEqual(code, 2)
        self.assertIn("missing_objective", err)

    def test_strategy(self) -> None:
        code, data, _ = run_main("strategy", "--objective", "x", "--files", "1", "--mode", "plan")
        self.assertEqual(code, 0)
        self.assertEqual(data["strategy"]["flow"], "planned")
        self.assertEqual(data["classification"]["risk"], "low")
        _, direct, _ = run_main("strategy", "--objective", "x", "--files", "1")
        self.assertEqual(direct["strategy"]["flow"], "direct")

    def test_route_model(self) -> None:
        code, data, _ = run_main("route-model", "--objective", "x", "--files", "1")
        self.assertEqual(code, 0)
        self.assertEqual(data["model_choice"]["tier"], "economy")
        _, data, _ = run_main(
            "route-model",
            "--objective",
            "x",
            "--files",
            "1",
            "--attempt",
            "3",
            "--unavailable",
            "claude-opus-5-5",
        )
        self.assertEqual(data["model_choice"]["model"], "claude-sonnet-5-5")

    def test_route_model_everything_unavailable_exits_nonzero(self) -> None:
        code, _, err = run_main(
            "route-model",
            "--objective",
            "x",
            "--unavailable",
            "claude-haiku-5-5",
            "--unavailable",
            "claude-sonnet-5-5",
            "--unavailable",
            "claude-opus-5-5",
        )
        self.assertEqual(code, 8)
        self.assertIn("no_model_available", err)

    def test_tier_bounds_must_pair(self) -> None:
        code, _, err = run_main("route-model", "--objective", "x", "--min-tier", "standard")
        self.assertEqual(code, 2)
        self.assertIn("invalid_tier_bounds", err)

    def test_portuguese_reasons(self) -> None:
        _, data, _ = run_main("--lang", "pt-BR", "classify", "--objective", "x", "--destructive")
        self.assertTrue(any("Risco alto" in r for r in data["reasons"]))


if __name__ == "__main__":
    unittest.main()
