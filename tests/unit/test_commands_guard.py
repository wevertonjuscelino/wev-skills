from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from wev_skills import cli
from wev_skills.guards import command_event, command_signature


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--lang", "en", *argv])
    return code, out.getvalue(), err.getvalue()


class GuardCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, payload: object) -> str:
        path = self.root / "events.json"
        path.write_text(json.dumps(payload))
        return str(path)

    def events(self, count: int) -> list[dict[str, object]]:
        return [command_event("t", float(i), ["pytest"], "/w", 0).to_dict() for i in range(count)]

    def test_continue_prints_verdict_and_exits_zero(self) -> None:
        code, out, _ = run_main("guard", "evaluate", "--events-file", self.write(self.events(2)))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["action"], "continue")

    def test_tripped_prints_the_verdict_on_stdout_and_exits_six(self) -> None:
        path = self.write({"events": self.events(4)})
        code, out, err = run_main("guard", "evaluate", "--events-file", path, "--now", "10")
        self.assertEqual((code, err), (6, ""))
        verdict = json.loads(out)
        self.assertEqual(verdict["action"], "change_strategy")
        self.assertEqual(verdict["rule"], "identical_commands")

    def test_dependency_flag_stops(self) -> None:
        path = self.write(self.events(1))
        code, out, _ = run_main("guard", "evaluate", "--events-file", path, "--dep", "dep-1")
        self.assertEqual(code, 6)
        details = json.loads(out)["details"]
        self.assertEqual(details["unresolved_dependencies"], ["dep-1"])

    def test_missing_and_malformed_files(self) -> None:
        code, _, _ = run_main("guard", "evaluate", "--events-file", str(self.root / "nope.json"))
        self.assertEqual(code, 7)
        for bad in ('{"x": 1}', "not json", '[{"kind": "bogus", "task_id": "t", "at": 1}]'):
            path = self.root / "bad.json"
            path.write_text(bad)
            code, _, _ = run_main("guard", "evaluate", "--events-file", str(path))
            self.assertEqual(code, 2, bad)

    def test_signature_matches_library(self) -> None:
        code, out, _ = run_main("guard", "signature", "--cwd", "/w", "--", "pytest", "-q")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["signature"], command_signature(["pytest", "-q"], "/w"))
        self.assertEqual(payload["argv"], ["pytest", "-q"])

    def test_signature_requires_a_command(self) -> None:
        code, _, _ = run_main("guard", "signature", "--")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
