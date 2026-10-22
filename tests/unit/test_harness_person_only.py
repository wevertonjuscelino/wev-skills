"""Human-operator commands are denied on harnesses that cannot ask (final review C1).

Codex, Gemini CLI and OpenCode turn a policy ``ask`` into allow plus a warning. An ask
marked ``person_only`` (operator commands, ``harness install|uninstall``) is a deny there;
Claude Code still renders it as the same ``ask``.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.unit.test_harness_hooks import FakeStdin, fixture
from wev_skills import cli
from wev_skills.adapters.claude_code import hooks

H3 = ("codex", "gemini", "opencode")
KEY = {"codex": "tool_input", "gemini": "tool_input", "opencode": "args"}
PERSON_ONLY = (
    "wev approval grant a1",
    "wev run adopt x",
    "wev harness uninstall --target gemini",
    "wev skills install rea",
    "wev skills update rea",
    "wev skills rollback rea",
    "wev skills freeze rea",
    "wev skills activate",
    "wev skills deactivate",
    "wev rea mode direct",
    "wev rea build-image",
    "git push && wev approval grant a1",
    # the marker comes from the whole line, not from the first reason shown
    "wev approval grant a1 --config x.json",
    "wev run start && wev approval grant a1",
    "wev --config x.json run adopt r1",
    "python3 -m wev_skills approval grant a1",
)
UNREADABLE = (
    # lines the guard cannot tokenize: denied whatever they name (fail safe)
    "(wev approval grant a1)",
    "{ wev approval grant a1; }",
    "if true; then wev approval grant a1; fi",
    "echo $(wev approval grant a1)",
    "echo `wev approval grant a1`",
    "wev approval grant a1 <<EOF\nx\nEOF",
    "wev approval grant a1 <<< x",
    "wev approval grant a1 " + "x " * 10_001,
    '("wev" approval grant a1)',
    "(w\\ev approval grant a1)",
    "(echo hi)",
    "echo $(date)",
    # a program word the shell rewrites: what runs is unknown (fail safe)
    "$'wev' approval grant a1",
    "{w,ev} approval grant a1",
    "$CC approval grant a1",
    "w*v approval grant a1",
    "nohup $CC approval grant a1",
)
POLICY_ASKS = (
    "git push",
    "wev run start --request x",
    "rm -rf $D",
)
DENIED = "this is a human-operator command; this harness cannot ask, so it was denied"
UNJUDGED = "the guard could not judge this command safely"


class PersonOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve() / "repo"
        (self.work / ".git").mkdir(parents=True)
        env = {name: f"{tmp.name}/{name}" for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME",
               "XDG_STATE_HOME", "XDG_CACHE_HOME")}  # fmt: skip
        patcher = mock.patch.dict(os.environ, {"HOME": tmp.name, **env})
        patcher.start()
        self.addCleanup(patcher.stop)

    def harness_hook(self, harness: str, command: str) -> tuple[int, str, str]:
        return self.run_hook(self.shell(harness, command), "--harness", harness)

    def run_hook(self, payload: dict[str, Any], *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.object(sys, "stdin", FakeStdin(json.dumps(payload))),
        ):
            code = cli.main(["--lang", "en", "hook", "pre-tool-use", *argv])
        return code, out.getvalue(), err.getvalue()

    def shell(self, harness: str, command: str) -> dict[str, Any]:
        payload = fixture(f"{harness}_shell")
        payload["cwd"] = str(self.work)
        payload[KEY[harness]] = {"command": command}
        return payload

    def assert_denied(self, commands: tuple[str, ...], expected: str) -> None:
        for harness in H3:
            for command in commands:
                with self.subTest(harness=harness, command=command):
                    code, out, err = self.harness_hook(harness, command)
                    data = json.loads(out)
                    if harness == "codex":
                        data = data["hookSpecificOutput"]
                        decision = data["permissionDecision"]
                        reason = data["permissionDecisionReason"]
                    else:
                        decision, reason = data["decision"], data["reason"]
                    self.assertEqual((code, decision, err), (0, "deny", ""))
                    self.assertIn(expected, reason)

    def test_operator_and_harness_commands_are_denied(self) -> None:
        self.assert_denied(PERSON_ONLY, DENIED)

    def test_lines_the_guard_cannot_tokenize_are_denied(self) -> None:
        self.assert_denied(UNREADABLE, UNJUDGED)

    def test_policy_asks_stay_allow_with_warning(self) -> None:
        for harness in H3:
            for command in POLICY_ASKS:
                with self.subTest(harness=harness, command=command):
                    code, out, err = self.harness_hook(harness, command)
                    self.assertEqual(code, 0)
                    self.assertNotIn('"deny"', out)
                    self.assertIn("this harness cannot ask, so it was allowed", out + err)

    def test_claude_still_asks_with_the_same_answer(self) -> None:
        for command in PERSON_ONLY + UNREADABLE:
            with self.subTest(command=command):
                payload = {"cwd": str(self.work), "tool_name": "Bash",
                           "tool_input": {"command": command}}  # fmt: skip
                code, out, _ = self.run_hook(payload)
                specific = json.loads(out)["hookSpecificOutput"]
                self.assertEqual((code, specific["permissionDecision"]), (0, "ask"))
                reason = specific["permissionDecisionReason"]
                self.assertEqual(out, hooks._output("ask", reason) + "\n")
                self.assertNotIn(DENIED, out)


if __name__ == "__main__":
    unittest.main()
