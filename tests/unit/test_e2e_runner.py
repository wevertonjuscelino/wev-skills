"""The end-to-end runner (scripts/e2e.py): the confirmation gate, the cost lines, the report and
the exit codes, driven by a fake scenario module. No network."""

from __future__ import annotations

import importlib.util
import io
import os
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TextIO
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("e2e_runner", ROOT / "scripts" / "e2e.py")
assert spec and spec.loader
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)

FAKE = """
import json, os, unittest

@unittest.skipUnless(os.environ.get("WEV_E2E") == "alpha", "not selected")
class Alpha(unittest.TestCase):
    def test_rows(self):
        for result in os.environ["FAKE_RESULTS"].split(","):
            line = {"scenario": "alpha", "check": "check " + result, "command": "cmd | x",
                    "exit": 0, "result": result, "detail": "boom output"}
            with open(os.environ["WEV_E2E_REPORT"], "a") as handle:
                handle.write(json.dumps(line) + "\\n")
        with open(os.environ["FAKE_MARK"], "w") as handle:
            handle.write("ran")
"""
COSTS = {"alpha": "network only; no account"}


class Tty(io.StringIO):
    """A terminal that answers `answer` to whatever is asked."""

    def __init__(self, answer: str) -> None:
        super().__init__()
        self.answer = answer

    def readline(self, size: int = -1) -> str:
        return self.answer + "\n"


class RunnerCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "fakepkg").mkdir()
        (self.dir / "fakepkg" / "__init__.py").write_text("")
        (self.dir / "fakepkg" / "test_alpha.py").write_text(FAKE)
        self.mark = self.dir / "mark"
        self.reports = self.dir / "reports"

    def main(
        self, results: str, env: dict[str, str], tty: Callable[[], TextIO | None] = lambda: None
    ) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"FAKE_RESULTS": results, "FAKE_MARK": str(self.mark)}):
            code = e2e.main(
                ["--out-dir", str(self.reports)],
                scenarios=COSTS,
                package="fakepkg",
                root=self.dir,
                env=env,
                tty=tty,
                out=out,
            )
        return code, out.getvalue()

    def report(self) -> str:
        (path,) = self.reports.glob("e2e-*.md")
        return path.read_text(encoding="utf-8")

    def test_no_tty_and_no_env_exits_2_and_runs_nothing(self) -> None:
        code, out = self.main("passed", {})
        self.assertEqual(code, 2)
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.reports.exists())
        self.assertIn("alpha: network only; no account", out)  # the cost line came first

    def test_typed_no_exits_2_and_runs_nothing(self) -> None:
        code, _ = self.main("passed", {}, tty=lambda: Tty("no"))
        self.assertEqual(code, 2)
        self.assertFalse(self.mark.exists())

    def test_typed_yes_runs(self) -> None:
        code, _ = self.main("passed", {}, tty=lambda: Tty("yes"))
        self.assertEqual(code, 0)
        self.assertTrue(self.mark.exists())

    def test_env_yes_runs_and_writes_the_report_table(self) -> None:
        code, _ = self.main("passed,skipped: no network", {"WEV_E2E_CONFIRM": "yes"})
        text = self.report()
        self.assertEqual(code, 0)  # a skip is not fatal
        self.assertIn("| Check | Command | Exit | Result |", text)
        self.assertIn("| check passed | `cmd \\| x` | 0 | passed |", text)
        self.assertIn("skipped: no network", text)
        self.assertIn("macOS: tested with isolated HOME, not a clean machine", text)
        for label in ("Date:", "Platform:", "Clone commit:"):
            self.assertIn(label, text)

    def test_a_failed_check_exits_1_and_shows_its_output(self) -> None:
        code, _ = self.main("passed,failed", {"WEV_E2E_CONFIRM": "yes"})
        self.assertEqual(code, 1)
        self.assertIn("| check failed | `cmd \\| x` | 0 | failed |", self.report())
        self.assertIn("boom output", self.report())

    def test_unknown_scenario_exits_2(self) -> None:
        out = io.StringIO()
        code = e2e.main(["nope"], scenarios=COSTS, root=self.dir, out=out)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
