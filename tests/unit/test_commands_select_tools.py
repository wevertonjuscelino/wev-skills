"""``wev select-tools`` and ``wev task tools``: the CLI faces of per-task tool selection."""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from wev_skills import cli

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_jev.py"
READ = ["Read", "Grep", "Glob"]


def run_main(*argv: str) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    text = out.getvalue()
    return code, json.loads(text) if text.strip() else {}, err.getvalue()


class SelectToolsCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def task_file(self, **fields: Any) -> str:
        base = {"id": "t1", "title": "Tidy", "objective": "Tidy the parser module"}
        path = self.dir / "plan-task.json"
        path.write_text(json.dumps({**base, **fields}), encoding="utf-8")
        return str(path)

    def config(self, **sections: Any) -> str:
        path = self.dir / "wev.config.json"
        path.write_text(json.dumps(sections), encoding="utf-8")
        return str(path)

    def fake_jev(self) -> str:
        script = self.dir / "jev"
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return str(script)

    def test_a_read_only_review_on_the_real_catalog_gets_the_read_tools(self) -> None:
        path = self.task_file(objective="Review the parser for defects", read_only=True)
        code, data, _ = run_main("select-tools", "--task-file", path, "--agent", "code-reviewer")
        self.assertEqual(code, 0)
        self.assertEqual(data["selection"]["selected"], READ)
        self.assertEqual(data["selection"]["dropped"], ["Bash"])
        self.assertEqual((data["agent_id"], data["provider"]), ("code-reviewer", "local-policy"))
        self.assertEqual(data["estimate_label"], "estimated definition tokens (approximate)")

    def test_a_feature_with_checks_keeps_edit_write_and_the_shell(self) -> None:
        path = self.task_file(objective="Add an export command", checks=["make test"])
        _, data, _ = run_main("select-tools", "--task-file", path, "--agent", "senior-engineer")
        self.assertEqual(data["selection"]["selected"], [*READ, "Edit", "Write", "Bash"])
        self.assertEqual(data["selection"]["dropped"], [])
        self.assertEqual(data["tier"], "standard")

    def test_the_tier_resolves_an_automatic_profile(self) -> None:
        config = self.config(harness={"tool_profile": "auto"})
        path = self.task_file(checks=["make test"])
        argv = ("--config", config, "select-tools", "--task-file", path, "--agent")
        _, lean, _ = run_main(*argv, "senior-engineer", "--tier", "premium")
        self.assertEqual(lean["selection"]["profile"], "lean")
        self.assertEqual(lean["selection"]["selected"], ["Read", "Edit", "Bash"])
        _, plain, _ = run_main(*argv, "senior-engineer", "--tier", "economy")
        self.assertEqual(plain["selection"]["profile"], "structured")

    def test_provider_mode_uses_the_configured_provider(self) -> None:
        config = self.config(
            decision={"provider": "jev", "jev": {"command": self.fake_jev()}},
            harness={"tool_selection": "provider"},
        )
        path = self.task_file()
        answers = {"FAKE_JEV_TOOL_ANSWERS": json.dumps({"Write": 0.0, "Bash": 0.7})}
        with mock.patch.dict(os.environ, answers):
            code, data, _ = run_main(
                "--config",
                config,
                "select-tools",
                "--task-file",
                path,
                "--agent",
                "senior-engineer",
            )
        self.assertEqual(code, 0)
        self.assertEqual((data["provider"], data["selection"]["source"]), ("jev", "jev"))
        self.assertEqual(data["selection"]["dropped"], ["Write"])

    def test_local_mode_does_not_call_the_configured_provider(self) -> None:
        config = self.config(
            decision={"provider": "jev", "jev": {"command": str(self.dir / "missing-jev")}},
            harness={"tool_selection": "local"},
        )
        _, data, _ = run_main(
            "--config", config, "select-tools", "--task-file", self.task_file(), "--agent",
            "senior-engineer",
        )  # fmt: skip
        self.assertEqual(data["selection"]["source"], "local-policy")
        self.assertFalse(any("JEV" in reason for reason in data["selection"]["reasons"]))

    def test_reasons_follow_the_language(self) -> None:
        path = self.task_file()
        _, data, _ = run_main(
            "--lang", "pt-BR", "select-tools", "--task-file", path, "--agent", "senior-engineer"
        )
        self.assertTrue(any("removida" in reason for reason in data["selection"]["reasons"]))

    def test_an_unknown_agent_or_a_bad_task_file_is_an_error(self) -> None:
        code, _, err = run_main(
            "select-tools", "--task-file", self.task_file(), "--agent", "nobody-here"
        )
        self.assertNotEqual(code, 0)
        self.assertIn("error", err)
        bad = self.dir / "bad.json"
        bad.write_text(json.dumps({"title": "no id"}), encoding="utf-8")
        code, _, err = run_main(
            "select-tools", "--task-file", str(bad), "--agent", "senior-engineer"
        )
        self.assertEqual(code, 2)
        self.assertIn("invalid_task_file", err)

    def test_task_tools_is_registered_with_its_flags(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["task", "tools", "t1", "--add", "Write", "--reason", "new file"])
        self.assertEqual(
            (args.task, args.add, args.reason, args.run), ("t1", "Write", "new file", None)
        )


if __name__ == "__main__":
    unittest.main()
