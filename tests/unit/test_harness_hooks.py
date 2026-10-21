"""Hook codecs for Codex, Gemini CLI and OpenCode.

Format facts come from docs/research/harness-{codex,gemini,opencode}.md:
- Codex section 3 (Hooks): PreToolUse stdin ``tool_name``/``tool_input``; deny is stdout
  ``hookSpecificOutput`` JSON; ask is unsupported; SessionStart ``additionalContext``.
- Gemini section 4 (Hooks): shell tool ``run_shell_command``; deny is exit 0 with
  ``{"decision":"deny","reason":...}``; ``systemMessage`` is the warning channel.
- OpenCode section 4: plugin sends ``{"tool": "bash", "args": {...}, "cwd": ...}``; the answer
  ``{"decision": "allow"|"deny", "reason"}`` is defined by wev (see the codec's docstring).
Codex shell tool name, verified by reading openai/codex at tag rust-v0.160.0 with ``gh api``:
``codex-rs/core/src/tools/hook_names.rs`` ``HookToolName::bash()`` returns ``Bash`` ("the hook
identity historically used for shell-like tools", the canonical name serialized into hook
stdin), and ``codex-rs/hooks/src/events/pre_tool_use.rs`` tests build requests with
``tool_name: "Bash"``.
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

from wev_skills import cli, i18n
from wev_skills.adapters import harness_hooks as hh
from wev_skills.adapters.claude_code import hooks
from wev_skills.commands import hook as hook_cmd

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "harness_payloads"
DENY = json.dumps(
    {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "no way",
        }
    }
)
ASK = DENY.replace("deny", "ask")
NON_SHELL = {"codex": "codex_other", "gemini": "gemini_other", "opencode": "opencode_other"}


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeStdin(io.StringIO):
    def isatty(self) -> bool:
        return False


class CodecTests(unittest.TestCase):
    def setUp(self) -> None:
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)

    def test_shell_payload_maps_to_claude_shape(self) -> None:
        for harness in ("codex", "gemini", "opencode"):
            with self.subTest(harness):
                self.assertEqual(
                    hh.to_claude_payload(harness, fixture(f"{harness}_shell")),
                    {"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "cwd": "/tmp/work"},
                )

    def test_non_shell_tool_is_no_opinion(self) -> None:
        for harness, name in NON_SHELL.items():
            with self.subTest(harness):
                self.assertIsNone(hh.to_claude_payload(harness, fixture(name)))
        self.assertIsNone(hh.to_claude_payload("codex", {"tool_name": "Bash"}))
        self.assertIsNone(
            hh.to_claude_payload(
                "gemini", {"tool_name": "run_shell_command", "tool_input": {"command": 3}}
            )
        )

    def test_deny_maps_to_harness_deny(self) -> None:
        codex = hh.from_claude_answer("codex", DENY)
        self.assertEqual(codex, hh.HookOutput(DENY, "", 0))
        expected = '{"decision": "deny", "reason": "no way"}'
        for harness in ("gemini", "opencode"):
            self.assertEqual(hh.from_claude_answer(harness, DENY), hh.HookOutput(expected, "", 0))

    def test_ask_becomes_allow_with_warning(self) -> None:
        warning = (
            "wev would ask before this command; this harness cannot ask, so it was allowed: no way"
        )
        self.assertEqual(hh.from_claude_answer("codex", ASK), hh.HookOutput("", warning, 0))
        for harness, key in (("gemini", "systemMessage"), ("opencode", "reason")):
            out = hh.from_claude_answer(harness, ASK)
            self.assertEqual((out.exit_code, out.stderr), (0, ""))
            self.assertEqual(json.loads(out.stdout), {"decision": "allow", key: warning})

    def test_no_opinion_is_silent(self) -> None:
        for harness in hh.HARNESSES:
            self.assertEqual(hh.from_claude_answer(harness, ""), hh.HookOutput("", "", 0))

    def test_session_context_formats(self) -> None:
        self.assertEqual(hh.session_context_output("opencode", "brief"), "brief")
        for harness in ("codex", "gemini"):
            data = json.loads(hh.session_context_output(harness, "brief"))
            self.assertEqual(
                data["hookSpecificOutput"],
                {"hookEventName": "SessionStart", "additionalContext": "brief"},
            )


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve() / "repo"
        (self.work / ".git").mkdir(parents=True)
        env = {
            "HOME": tmp.name,
            "XDG_DATA_HOME": f"{tmp.name}/xdg",
            "XDG_CONFIG_HOME": f"{tmp.name}/cfg",
            "XDG_STATE_HOME": f"{tmp.name}/state",
            "XDG_CACHE_HOME": f"{tmp.name}/cache",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)

    def run_hook(self, text: str, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.object(sys, "stdin", FakeStdin(text)),
        ):
            code = cli.main(["--lang", "en", "hook", "pre-tool-use", *argv])
        return code, out.getvalue(), err.getvalue()

    def shell(self, harness: str, command: str) -> str:
        payload = fixture(f"{harness}_shell")
        payload["cwd"] = str(self.work)
        key = "args" if harness == "opencode" else "tool_input"
        payload[key] = {"command": command}
        return json.dumps(payload)

    def test_deny_end_to_end(self) -> None:
        for harness in ("codex", "gemini", "opencode"):
            with self.subTest(harness):
                code, out, _ = self.run_hook(
                    self.shell(harness, "cat .git/config"), "--harness", harness
                )
                self.assertEqual(code, 0)
                self.assertIn('"deny"', out)

    def test_safe_command_and_non_shell_are_silent(self) -> None:
        for harness in ("codex", "gemini", "opencode"):
            with self.subTest(harness):
                safe = self.run_hook(self.shell(harness, "ls"), "--harness", harness)
                other = self.run_hook(json.dumps(fixture(NON_SHELL[harness])), "--harness", harness)
                self.assertEqual(safe, (0, "", ""))
                self.assertEqual(other, (0, "", ""))

    def test_malformed_stdin_never_crashes(self) -> None:
        for harness in ("codex", "gemini", "opencode"):
            for text in ("", "not json", "[1]", '{"tool_name": 5}', "\x00" * 10):
                with self.subTest(harness=harness, text=text):
                    code, out, err = self.run_hook(text, "--harness", harness)
                    self.assertEqual(code, 0)
                    self.assertNotIn("Traceback", out + err)

    def test_internal_error_ask_becomes_warning(self) -> None:
        boom = mock.Mock(side_effect=RuntimeError("x"))
        with mock.patch.dict(hook_cmd.HOOKS, {"pre-tool-use": boom}):
            code, out, err = self.run_hook(self.shell("codex", "ls"), "--harness", "codex")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("this harness cannot ask", err)

    def test_session_context_without_run_is_silent(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.object(sys, "stdin", FakeStdin(json.dumps({"cwd": str(self.work)}))),
        ):
            code = cli.main(["--lang", "en", "hook", "session-context", "--harness", "codex"])
        self.assertEqual((code, out.getvalue()), (0, ""))

    def test_claude_default_unchanged(self) -> None:
        payload = json.dumps(
            {
                "cwd": str(self.work),
                "tool_name": "Bash",
                "tool_input": {"command": "cat .git/config"},
            }
        )
        default = self.run_hook(payload)
        explicit = self.run_hook(payload, "--harness", "claude")
        self.assertEqual(default, explicit)
        self.assertIn("permissionDecision", default[1])
        self.assertEqual(default[1], hooks.pre_tool_use(json.loads(payload)) + "\n")


if __name__ == "__main__":
    unittest.main()
