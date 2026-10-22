"""The end-to-end runner (scripts/e2e.py): the confirmation gate, the cost lines, the report and
the exit codes, driven by a fake scenario module. No network."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import tempfile
import time
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
    def test_crash(self):
        if os.environ.get("FAKE_CRASH"):
            raise RuntimeError(os.environ["FAKE_CRASH"])

    def test_rows(self):
        with open(os.environ["FAKE_MARK"], "w") as handle:
            handle.write("ran")
        for result in filter(None, os.environ["FAKE_RESULTS"].split(",")):
            line = {"scenario": "alpha", "check": "check " + result, "command": "cmd | x",
                    "exit": 0, "result": result, "detail": "boom output"}
            with open(os.environ["WEV_E2E_REPORT"], "a") as handle:
                handle.write(json.dumps(line) + "\\n")
            if result == "failed":
                self.fail("failed")
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
        self,
        results: str,
        env: dict[str, str],
        tty: Callable[[], TextIO | None] = lambda: None,
        crash: str = "",
        out: io.StringIO | None = None,
    ) -> tuple[int, str]:
        out = out or io.StringIO()
        fake = {"FAKE_RESULTS": results, "FAKE_MARK": str(self.mark), "FAKE_CRASH": crash}
        with mock.patch.dict(os.environ, fake):
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

    def test_yes_in_other_spellings_is_not_a_yes(self) -> None:
        for answer in ("YES", "y", "Yes", ""):
            code, _ = self.main("passed", {}, tty=lambda a=answer: Tty(a))
            self.assertEqual(code, 2, answer)
        self.assertFalse(self.mark.exists())

    def test_cost_lines_come_before_the_prompt(self) -> None:
        events: list[str] = []

        class Out(io.StringIO):
            def write(self, text: str) -> int:
                events.append("out:" + text.strip())
                return super().write(text)

        class Asking(Tty):
            def write(self, text: str) -> int:
                events.append("prompt")
                return super().write(text)

        self.main("passed", {}, tty=lambda: Asking("yes"), out=Out())
        cost = "out:alpha: network only; no account"
        self.assertLess(events.index(cost), events.index("prompt"))

    def test_a_crash_alone_is_a_failed_row(self) -> None:
        code, _ = self.main("", {"WEV_E2E_CONFIRM": "yes"}, crash="kaboom")
        self.assertEqual(code, 1)
        self.assertIn("| scenario ran |", self.report())
        self.assertIn("kaboom", self.report())

    def test_a_crash_next_to_a_failed_row_is_not_hidden(self) -> None:
        code, _ = self.main("failed", {"WEV_E2E_CONFIRM": "yes"}, crash="kaboom")
        text = self.report()
        self.assertEqual(code, 1)
        self.assertIn("| check failed |", text)
        self.assertIn("| scenario ran |", text)
        self.assertIn("kaboom", text)

    def test_a_crash_message_is_scrubbed(self) -> None:
        home = str(Path.home())
        self.main("", {"WEV_E2E_CONFIRM": "yes"}, crash=f"password=hunter2 at {home}/x")
        text = self.report()
        self.assertNotIn("hunter2", text)
        self.assertNotIn(home, text)

    def test_backticks_and_empty_commands_render_safely(self) -> None:
        rows = [
            {"scenario": "a", "check": "c1", "command": "echo `x`", "exit": 0, "result": "passed"},
            {"scenario": "a", "check": "c2", "command": "", "exit": None, "result": "passed"},
        ]
        text = e2e.render(rows, self.dir, "2026-01-01")
        self.assertIn("`` echo `x` ``", text)
        self.assertIn("| c2 |  |  | passed |", text)

    def test_a_second_run_keeps_the_other_scenarios_sections(self) -> None:
        both = {"alpha": "cost a", "beta": "cost b"}
        (self.dir / "fakepkg" / "test_beta.py").write_text(
            FAKE.replace('"alpha"', '"beta"').replace("Alpha", "Beta")
        )
        yes = {"WEV_E2E_CONFIRM": "yes"}

        def run(name: str, results: str) -> str:
            fake = {"FAKE_RESULTS": results, "FAKE_MARK": str(self.mark), "FAKE_CRASH": ""}
            with mock.patch.dict(os.environ, fake):
                e2e.main(
                    [name, "--out-dir", str(self.reports)], scenarios=both, package="fakepkg",
                    root=self.dir, env=yes, out=io.StringIO(),
                )  # fmt: skip
            return self.report()

        run("alpha", "passed")
        text = run("beta", "passed")
        self.assertIn("## alpha", text)
        self.assertIn("## beta", text)
        text = run("alpha", "skipped: later")
        self.assertEqual(text.count("## alpha"), 1)
        self.assertIn("skipped: later", text)
        self.assertEqual(text.count("check passed"), 1)  # alpha's old row is gone, beta's kept
        self.assertIn("## beta", text)
        self.assertEqual(text.count("# End-to-end report"), 1)

    def test_unknown_scenario_exits_2(self) -> None:
        out = io.StringIO()
        code = e2e.main(["nope"], scenarios=COSTS, root=self.dir, out=out)
        self.assertEqual(code, 2)


class SupportCase(unittest.TestCase):
    def test_a_timeout_kills_the_whole_process_group(self) -> None:
        from tests.e2e._support import run

        script = "(sleep 7.31) & echo out; echo err >&2; sleep 30"
        start = time.monotonic()
        done = run(["bash", "-c", script], 1, os.environ)
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(done.exit, -1)
        self.assertIn("err", done.output)  # stderr is kept
        left = subprocess.run(["pgrep", "-f", "sleep 7.31"], capture_output=True, check=False)
        self.assertNotEqual(left.returncode, 0, left.stdout)

    def test_the_child_env_drops_account_and_npm_variables(self) -> None:
        from tests.e2e._support import Tree

        dirty = {"NPM_CONFIG_PREFIX": "x", "npm_config_cache": "y", "XDG_CACHE_HOME": "z"}
        dirty |= {"CLAUDE_CONFIG_DIR": "c", "TYPESAFE_API_KEY": "k", "LANG": "C.UTF-8"}
        tree = Tree()
        self.addCleanup(tree.cleanup)
        with mock.patch.dict(os.environ, dirty):
            env = tree.env()
        for name in ("NPM_CONFIG_PREFIX", "npm_config_cache", "XDG_CACHE_HOME"):
            self.assertNotIn(name, env)
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        self.assertNotIn("TYPESAFE_API_KEY", env)
        self.assertEqual(env["LANG"], "C.UTF-8")
        self.assertEqual(env["HOME"], str(tree.home))

    def test_container_exec_runs_under_timeout_with_the_xdg_layout(self) -> None:
        from tests.e2e._docker import ContainerHost, docker_env

        host = ContainerHost.__new__(ContainerHost)
        host.name = "box"
        argv = host._wrapped(["wev", "version"], 90)
        self.assertEqual(argv[-5:], ["timeout", "--kill-after=5", "90", "wev", "version"][-5:])
        self.assertIn("XDG_DATA_HOME=/tmp/wev-xdg/data", argv)
        self.assertEqual(docker_env({"DOCKER_HOST": "unix:///x"})["DOCKER_HOST"], "unix:///x")


if __name__ == "__main__":
    unittest.main()
