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
Working directory of a shell call (fix round 1): Gemini ``dir_path`` is read in
google-gemini/gemini-cli v0.65.0 ``packages/core/src/tools/shell.ts`` (``dir_path?: string``, the
spawn cwd is ``path.resolve(targetDir, dir_path)``); OpenCode ``workdir`` is read in
anomalyco/opencode v1.19.3 ``packages/core/src/tool/plugin/shell.ts``
(``workdir: optionalKey(String)``).
Codex: the hook ``tool_input`` is built as ``{"command": ...}`` (plus ``description``) in
``core/src/tools/handlers/unified_exec/exec_command.rs`` and ``core/src/tools/sandboxing.rs``
at rust-v0.160.0, so Codex never sends a ``workdir`` to the hook; the codec still honors a
``workdir`` key if one appears (UNVERIFIED, treated like the other two).
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

from tests.unit.test_hook_trust import TrustCase
from wev_skills import cli, i18n
from wev_skills.adapters import harness_hooks as hh
from wev_skills.adapters.claude_code import hooks
from wev_skills.adapters.claude_code.bash_guard import ASK as ASK_DECISION
from wev_skills.adapters.claude_code.bash_guard import HookVerdict
from wev_skills.core import active

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


FAIL_SAFE_DENY = "has no ask decision for hooks, so it was denied"
HARNESS_PAYLOAD_KEY = {"codex": "tool_input", "gemini": "tool_input", "opencode": "args"}
H3 = ("codex", "gemini", "opencode")
WORKDIR_KEY = {"codex": "workdir", "gemini": "dir_path", "opencode": "workdir"}


def assert_denied(test: unittest.TestCase, harness: str, code: int, out: str, err: str) -> None:
    test.assertEqual((code, err.count("Traceback")), (0, 0), err)
    data = json.loads(out)
    if harness == "codex":
        data = data["hookSpecificOutput"]
        test.assertEqual(data["permissionDecision"], "deny")
        reason = data["permissionDecisionReason"]
    else:
        test.assertEqual(data["decision"], "deny")
        reason = data["reason"]
    test.assertIn(FAIL_SAFE_DENY, reason)


class FailSafeCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)

    def test_fail_safe_ask_is_deny_on_every_harness(self) -> None:
        for harness in ("codex", "gemini", "opencode"):
            with self.subTest(harness):
                out = hh.from_verdict(harness, HookVerdict(ASK_DECISION, "r", fail_safe=True))
                assert_denied(self, harness, out.exit_code, out.stdout, out.stderr)

    def test_unparseable_guard_answer_is_deny(self) -> None:
        for answer in ("not json", "[]", '{"hookSpecificOutput": 3}', hooks.FALLBACK_ASK):
            for harness in ("codex", "gemini", "opencode"):
                with self.subTest(harness=harness, answer=answer):
                    out = hh.from_claude_answer(harness, answer)
                    assert_denied(self, harness, out.exit_code, out.stdout, out.stderr)


class FailSafeCliTests(TrustCase):
    def run_harness(
        self, harness: str, payload: Any, name: str = "pre-tool-use"
    ) -> tuple[int, str, str]:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.object(sys, "stdin", FakeStdin(text)),
        ):
            code = cli.main(["--lang", "en", "hook", name, "--harness", harness])
        return code, out.getvalue(), err.getvalue()

    def shell(
        self, harness: str, command: str, cwd: Path | None = None, **extra: Any
    ) -> dict[str, Any]:
        payload = fixture(f"{harness}_shell")
        payload["cwd"] = str(cwd or self.work)
        payload[HARNESS_PAYLOAD_KEY[harness]] = {"command": command, **extra}
        return payload

    def test_policy_ask_is_allow_with_warning(self) -> None:
        for harness in H3:
            code, out, err = self.run_harness(harness, self.shell(harness, "git push"))
            self.assertEqual(code, 0)
            self.assertNotIn('"deny"', out)
            self.assertIn("this harness cannot ask", out + err)

    def test_unregistered_run_is_deny(self) -> None:
        self.forge()
        for harness in H3:
            assert_denied(self, harness, *self.run_harness(harness, self.shell(harness, "ls")))

    def test_unreadable_input_with_a_run_is_deny(self) -> None:
        self.forge()
        broken = '{"cwd": "' + str(self.work) + '", "tool'
        for harness in H3:
            assert_denied(self, harness, *self.run_harness(harness, broken))

    def test_internal_error_is_deny(self) -> None:
        with mock.patch.object(hooks, "find_hook_run", side_effect=RuntimeError("x")):
            for harness in H3:
                assert_denied(self, harness, *self.run_harness(harness, self.shell(harness, "ls")))

    def test_failure_building_the_answer_is_deny(self) -> None:
        boom = RuntimeError("x")
        with (
            mock.patch.object(hooks, "find_hook_run", side_effect=boom),
            mock.patch.object(hooks, "_output", side_effect=boom),
        ):
            for harness in H3:
                assert_denied(self, harness, *self.run_harness(harness, self.shell(harness, "ls")))

    def test_unknown_target_with_a_registered_run_is_deny(self) -> None:
        active.register_run(self.work, self.forge(), "20990101T000000Z-forged")
        elsewhere = self.work.parent / "elsewhere"
        elsewhere.mkdir()
        for harness in H3:
            payload = self.shell(harness, "rm -rf $TARGET/x", elsewhere)
            assert_denied(self, harness, *self.run_harness(harness, payload))

    def test_workdir_is_resolved_against_cwd_and_judged(self) -> None:
        out = self.work.parent / "out"
        out.mkdir()
        # From `out` (next to the repo), `../out` is the working directory itself.
        line = "rm -rf ../out"
        for harness in H3:
            key = WORKDIR_KEY[harness]
            plain = self.run_harness(harness, self.shell(harness, line))
            self.assertNotIn("'../out'", "".join(plain[1:]), harness)
            for named in ("../out", str(out)):
                moved = self.run_harness(harness, self.shell(harness, line, **{key: named}))
                self.assertIn("'../out'", "".join(moved[1:]), harness)

    def test_bad_workdir_is_deny(self) -> None:
        for harness in H3:
            key = WORKDIR_KEY[harness]
            for bad in (None, 5, ["a"], "", "no-such-dir", "a\x00b"):
                with self.subTest(harness=harness, bad=bad):
                    payload = self.shell(harness, "ls", **{key: bad})
                    assert_denied(self, harness, *self.run_harness(harness, payload))

    def test_prompt_reminder_refuses_the_harness_flag(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["--lang", "en", "hook", "prompt-reminder", "--harness", "codex"])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
