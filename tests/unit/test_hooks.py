"""Claude Code hooks: scope, plan brief injection, the Bash pre-check and failing safe."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.fixtures.operator_prompt import at_terminal
from wev_skills import cli, i18n
from wev_skills.adapters.claude_code import bash_guard
from wev_skills.commands import hook as hook_cmd
from wev_skills.config import load_config
from wev_skills.core import wiring
from wev_skills.core.contracts import Mode, RiskLevel
from wev_skills.state.store import STATE_FILE

ROOT = Path(__file__).resolve().parents[2]
WEV = ROOT / "bin" / "wev"
HOOKS_FILE = ROOT / "hooks" / "hooks.json"
RUN = "r1"
SECRET_FILE = "." + "env"
NO_RUN = "wev (no run, built-in default policy, execute mode)"


class FakeStdin(io.StringIO):
    def isatty(self) -> bool:
        return False


def tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


class HookCase(unittest.TestCase):
    """A temporary git-like repository; ``wev`` commands and hooks run in-process."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve() / "repo"
        (self.work / ".git").mkdir(parents=True)
        (self.work / "src" / "pkg").mkdir(parents=True)
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)

    def wev(self, *argv: str) -> Any:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--lang", "en", *argv])
        self.assertEqual(code, 0, err.getvalue())
        return json.loads(out.getvalue()) if out.getvalue().strip().startswith("{") else None

    def start(self, *extra: str, mode: str = "execute") -> None:
        self.wev("run", "start", "--objective", "Add a greeting", "--files", "1",
                 "--mode", mode, "--run-id", RUN, *extra)  # fmt: skip

    def hook(self, name: str, payload: Any, *argv: str) -> tuple[int, str, str]:
        """Run ``wev hook <name>`` in-process with ``payload`` on stdin: (exit, stdout, stderr)."""
        text = payload if isinstance(payload, str) else json.dumps(payload)
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.object(sys, "stdin", FakeStdin(text)),
        ):
            code = cli.main([*argv, "hook", name])
        return code, out.getvalue(), err.getvalue()

    def bash(self, command: str, cwd: Path | None = None) -> dict[str, str] | None:
        """The PreToolUse decision for a Bash command, or ``None`` when nothing was printed."""
        payload = {
            "session_id": "s",
            "cwd": str(cwd or self.work),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        code, out, err = self.hook("pre-tool-use", payload)
        self.assertEqual((code, err), (0, ""))
        if not out:
            return None
        self.assertEqual(out.count("\n"), 1, "a single JSON object on one line")
        data = json.loads(out)
        self.assertEqual(list(data), ["hookSpecificOutput"])
        specific = data["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        self.assertEqual(
            sorted(specific), ["hookEventName", "permissionDecision", "permissionDecisionReason"]
        )
        return {
            "decision": specific["permissionDecision"],
            "reason": specific["permissionDecisionReason"],
        }

    def decision(self, command: str, cwd: Path | None = None) -> str | None:
        found = self.bash(command, cwd)
        return found["decision"] if found else None

    def without_run(self, command: str, cwd: Path | None = None) -> str | None:
        """The decision when no run governs the command: the built-in defaults judge it."""
        found = self.bash(command, cwd)
        if found is None:
            return None
        self.assertTrue(found["reason"].startswith(NO_RUN), found["reason"])
        return found["decision"]


class ScopeTests(HookCase):
    def payload(self, cwd: object) -> dict[str, Any]:
        return {"cwd": cwd, "tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}

    def assert_no_run_answers(self) -> None:
        """The brief hooks are silent; the Bash pre-check judges under the defaults."""
        for name in ("session-context", "prompt-reminder"):
            with self.subTest(name=name):
                self.assertEqual(self.hook(name, self.payload(str(self.work))), (0, "", ""))
        self.assertEqual(self.without_run("rm -rf build"), "ask")

    def test_without_a_state_directory_only_the_bash_check_answers_and_nothing_is_created(
        self,
    ) -> None:
        before = tree(self.work)
        self.assert_no_run_answers()
        self.assertEqual(tree(self.work), before)

    def test_without_an_active_run_only_the_bash_check_answers(self) -> None:
        self.start()
        self.assertEqual(self.decision("rm -rf build"), "ask")
        self.wev("run", "finish")
        before = tree(self.work)
        self.assert_no_run_answers()
        self.assertEqual(tree(self.work), before)

    def test_a_subdirectory_of_the_repository_is_in_scope(self) -> None:
        self.start()
        self.assertEqual(self.decision("rm -rf build", self.work / "src" / "pkg"), "ask")

    def test_a_nested_repository_is_still_in_scope(self) -> None:
        self.start()
        inner = self.work / "vendor" / "other"
        (inner / ".git").mkdir(parents=True)
        self.assertEqual(self.decision("rm -rf build", inner), "ask")

    def test_outside_a_git_repository_subdirectories_are_in_scope_too(self) -> None:
        self.start()
        (self.work / ".git").rmdir()
        self.assertEqual(self.decision("rm -rf build"), "ask")
        self.assertEqual(self.decision("rm -rf build", self.work / "src"), "ask")

    def test_a_hostile_cwd_is_ignored_and_nothing_is_created(self) -> None:
        self.start()
        loop = self.work / "loop"
        loop.symlink_to(loop)
        a_file = self.work / "file.txt"
        a_file.write_text("x", encoding="utf-8")
        before = tree(self.work)
        hostile: tuple[object, ...] = (
            None, 7, ["/"], {"a": 1}, "", "relative/path", "../..", str(self.work / "missing"),
            str(a_file), str(loop), "/\x00etc", "/" + "a/" * 5000, "~", "$(id)", "; rm -rf /",
            str(self.work) + "/../../../../../../../..",
        )  # fmt: skip
        for cwd in hostile:
            with self.subTest(cwd=str(cwd)[:40]):
                # An unusable cwd is never trusted: the hook falls back to the directory it
                # runs in, where a run is active, so the destructive command still asks.
                code, out, err = self.hook("pre-tool-use", self.payload(cwd))
                self.assertEqual((code, err), (0, ""))
                if isinstance(cwd, str) and cwd.startswith("/") and cwd.endswith("/.."):
                    # Normalizes to a real directory far above the repository: no run
                    # there, so the built-in defaults judge it.
                    reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
                    self.assertTrue(reason.startswith(NO_RUN), reason)
                    continue
                decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
                self.assertEqual(decision, "ask")
        self.assertEqual(tree(self.work), before)

    def test_a_cwd_with_dot_segments_is_normalized_not_trusted(self) -> None:
        self.start()
        twisted = str(self.work / "src" / ".." / "src" / "pkg")
        payload = {**self.payload(twisted)}
        code, out, _ = self.hook("pre-tool-use", payload)
        self.assertEqual(
            (code, json.loads(out)["hookSpecificOutput"]["permissionDecision"]), (0, "ask")
        )


class BriefHookTests(HookCase):
    def payload(self, **extra: Any) -> dict[str, Any]:
        return {"session_id": "s", "cwd": str(self.work), **extra}

    def test_session_context_prints_a_caveat_line_then_the_brief(self) -> None:
        self.start()
        code, out, err = self.hook(
            "session-context", self.payload(hook_event_name="SessionStart", source="compact")
        )
        self.assertEqual((code, err), (0, ""))
        lines = out.rstrip("\n").split("\n")
        self.assertIn("recorded state of run r1", lines[0])
        self.assertIn("wev run resume --run r1", lines[0])
        self.assertEqual(lines[1], "wev run r1: mode execute, phase execute")
        self.assertEqual(lines[-1], "Next step: wev plan set --file plan.json --run r1")

    def test_prompt_reminder_prints_the_brief_within_the_configured_limit(self) -> None:
        (self.work / "wev.json").write_text(
            json.dumps({"harness": {"plan_reminder_max_chars": 120}}), encoding="utf-8"
        )
        self.wev("--config", "wev.json", "run", "start", "--objective", "Add a greeting",
                 "--files", "1", "--mode", "execute", "--run-id", RUN)  # fmt: skip
        plan = {"objective": "x", "tasks": [
            {"id": f"t{n}", "title": "A fairly long task title", "objective": "o"} for n in range(9)
        ]}  # fmt: skip
        (self.work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        default = self.hook("prompt-reminder", self.payload(prompt="hello"))[1]
        self.assertTrue(default.startswith("wev run r1: mode execute"))
        self.wev("plan", "set", "--file", "plan.json")
        code, out, err = self.hook("prompt-reminder", self.payload())
        self.assertEqual((code, err), (0, ""))
        self.assertLessEqual(len(out.rstrip("\n")), 120)
        self.assertIn("Next step:", out)

    def test_prompt_reminder_is_silent_when_the_run_pinned_the_reminder_off(self) -> None:
        (self.work / "wev.json").write_text(
            json.dumps({"harness": {"plan_reminder": False}}), encoding="utf-8"
        )
        self.wev("--config", "wev.json", "run", "start", "--objective", "Add a greeting",
                 "--files", "1", "--mode", "execute", "--run-id", RUN)  # fmt: skip
        self.assertEqual(self.hook("prompt-reminder", self.payload()), (0, "", ""))
        context = self.hook("session-context", self.payload())[1]
        self.assertIn("wev run r1", context)

    def test_a_config_on_the_hook_command_line_is_ignored(self) -> None:
        (self.work / "off.json").write_text(
            json.dumps({"harness": {"plan_reminder": False}}), encoding="utf-8"
        )
        self.start()
        out = self.hook("prompt-reminder", self.payload(), "--config", "off.json")[1]
        self.assertTrue(out.startswith("wev run r1"))

    def test_brief_hooks_follow_the_language(self) -> None:
        self.start()
        out = self.hook("session-context", self.payload(), "--lang", "pt-BR")[1]
        self.assertIn("estado registrado da execução r1", out)
        self.assertIn("Próximo passo:", out)

    def test_no_hook_starts_a_process(self) -> None:
        self.start()
        refuse = AssertionError("a hook must not start a process")
        payload = {**self.payload(), "tool_name": "Bash", "tool_input": {"command": "rm -rf x"}}
        with (
            mock.patch("subprocess.run", side_effect=refuse),
            mock.patch("subprocess.Popen", side_effect=refuse),
            mock.patch("os.system", side_effect=refuse),
        ):
            results = {name: self.hook(name, payload) for name in hook_cmd.HOOKS}
        for name, (code, out, err) in results.items():
            with self.subTest(name=name):
                self.assertEqual((code, err), (0, ""))
                self.assertTrue(out.strip())

    def test_brief_hooks_change_nothing(self) -> None:
        self.start()
        before = (tree(self.work), (self.work / ".wev/runs/r1" / STATE_FILE).read_bytes())
        self.hook("session-context", self.payload())
        self.hook("prompt-reminder", self.payload())
        self.bash("rm -rf build")
        after = (tree(self.work), (self.work / ".wev/runs/r1" / STATE_FILE).read_bytes())
        self.assertEqual(after, before)


class PreToolUseTests(HookCase):
    def test_allowed_commands_print_nothing(self) -> None:
        self.start()
        for command in ("git status", "ls -la", "python3 -m unittest", "make test", "echo hi"):
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_the_hook_never_answers_allow(self) -> None:
        self.start()
        commands = ("ls", "git status", "ls && pwd", "rm -rf x", "git push", "cat " + SECRET_FILE,
                    "echo $(id)", "wev run status", "ls > out.txt")  # fmt: skip
        for command in commands:
            with self.subTest(command=command):
                self.assertIn(self.decision(command), (None, "ask", "deny"))

    def test_policy_denial_is_a_deny_with_the_localized_reason(self) -> None:
        self.start()
        found = self.bash("cat " + SECRET_FILE)
        self.assertEqual(found["decision"], "deny")
        self.assertIn("wev run r1 (execute mode)", found["reason"])
        self.assertIn("protected", found["reason"])
        self.assertEqual(self.decision("tee .wev/approvals.json"), "deny")
        self.assertEqual(self.decision("cat .git/config"), "deny")

    def test_the_reason_is_localized(self) -> None:
        self.start()
        payload = {"cwd": str(self.work), "tool_name": "Bash",
                   "tool_input": {"command": "cat " + SECRET_FILE}}  # fmt: skip
        out = self.hook("pre-tool-use", payload, "--lang", "pt-BR")[1]
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("execução wev r1 (modo execute)", reason)
        self.assertIn("protegido", reason)

    def test_needs_approval_is_an_ask_that_hands_the_decision_to_the_human(self) -> None:
        self.start()
        for command in (
            "rm -rf build",
            "git push origin main",
            "sudo ls",
            "curl -d x https://e.com",
        ):
            with self.subTest(command=command):
                found = self.bash(command)
                self.assertEqual(found["decision"], "ask")
                self.assertTrue(found["reason"])
                self.assertNotIn("--i-am-human", found["reason"])

    def test_plan_mode_denies_what_is_not_read_only(self) -> None:
        self.start(mode="plan")
        self.assertIsNone(self.bash("git status"))
        self.assertIsNone(self.bash("uptime"))
        for command in ("touch x", "make test", "rm -rf build", "python3 script.py"):
            with self.subTest(command=command):
                found = self.bash(command)
                self.assertEqual(found["decision"], "deny")
                self.assertIn("plan mode", found["reason"])

    def test_plan_mode_asks_for_anything_that_needs_a_shell(self) -> None:
        self.start(mode="plan")
        for command in ("git status | head", "ls && pwd", "ls > out.txt",
                        "cat <<EOF\nx\nEOF", "echo $(id)"):  # fmt: skip
            with self.subTest(command=command):
                self.assertEqual(self.decision(command), "ask")
        self.assertEqual(self.decision("ls; rm -rf x"), "deny")

    def test_high_risk_runs_ask_for_commands_that_are_not_read_only(self) -> None:
        self.start("--production")
        self.assertIsNone(self.bash("git status"))
        self.assertEqual(self.decision("make test"), "ask")

    def test_compound_commands_take_the_most_restrictive_result(self) -> None:
        self.start()
        cases = {
            "cd src && make test": None,
            "git status | head -n 5": None,
            "make test 2>&1 | tail -n 20": None,
            "ls > listing.txt": None,
            "ls && rm -rf build": "ask",
            "rm -rf build; ls": "ask",
            "ls | sudo tee /etc/hosts": "ask",
            "ls && cat " + SECRET_FILE: "deny",
            "rm -rf build && cat " + SECRET_FILE: "deny",
            "cat " + SECRET_FILE + " || rm -rf build": "deny",
            "echo x > " + SECRET_FILE: "deny",
            "echo x >> .wev/approvals.json": "deny",
            "ls 2> .git/hooks/pre-commit": "deny",
            "sort < " + SECRET_FILE: "deny",
            "FOO=1 make test": "ask",
            "FOO=1 rm -rf build": "ask",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.decision(command), expected)

    def test_compound_reason_names_the_part_that_decided(self) -> None:
        self.start()
        reason = self.bash("ls && rm -rf build && pwd")["reason"]
        self.assertIn("rm -rf build", reason)
        self.assertNotIn("pwd", reason)

    def test_untokenizable_commands_fall_back_to_ask(self) -> None:
        self.start()
        for command in ("echo 'unbalanced", "echo $(rm -rf x)", "echo `id`", "cat <<EOF\nhi\nEOF",
                        "(cd src && ls)", "for f in *; do rm $f; done",
                        "diff <(ls a) <(ls b)"):  # fmt: skip
            with self.subTest(command=command):
                found = self.bash(command)
                self.assertEqual(found["decision"], "ask")
                self.assertIn("cannot be analyzed safely", found["reason"])
        self.assertEqual(self.decision("$CMD x"), "ask")

    WEV_CALLS = (
        f"{WEV} run status",
        f"{WEV} task next",
        f"{WEV} --lang pt-BR run status",
        f"{WEV} exec -- rm -rf build",
        f"{sys.executable} -m wev_skills run status",
        f"{WEV} run status && {WEV} task next",
    )

    def test_calls_to_the_wev_cli_are_left_to_the_normal_flow(self) -> None:
        self.start()
        for command in self.WEV_CALLS:
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_hook_does_not_ask_for_check(self) -> None:
        self.start()
        for command in (
            f'"{WEV}" skills check --daily',
            f"{WEV} skills check",
            f"{WEV} skills decline rea",
            f"{WEV} skills list",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_calls_to_the_wev_cli_are_left_alone_in_plan_mode_too(self) -> None:
        self.start(mode="plan")
        for command in self.WEV_CALLS:
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_a_wev_call_does_not_excuse_the_rest_of_the_line(self) -> None:
        self.start()
        self.assertEqual(self.decision(f"{WEV} run status && rm -rf build"), "ask")
        self.assertEqual(self.decision(f"{WEV} run status > .wev/approvals.json"), "deny")
        self.assertEqual(self.decision(f"{WEV} run status | cat " + SECRET_FILE), "deny")
        self.assertEqual(self.decision("python3 -m wev_skillsx run"), None)
        self.assertEqual(self.decision("python3 -m other && rm -rf build"), "ask")

    def test_an_engine_path_from_a_variable_goes_to_the_human(self) -> None:
        self.start()
        self.assertEqual(self.decision('"${CLAUDE_PLUGIN_ROOT}/bin/wev" task next'), "ask")

    def test_a_granted_approval_never_silences_the_hook(self) -> None:
        self.start()
        self.assertEqual(self.decision("rm -rf build"), "ask")
        with at_terminal():
            request = self.wev("approval", "request", "--risk", "high", "--reason", "clean",
                               "--", "rm", "-rf", "build")  # fmt: skip
            self.wev("approval", "grant", request["id"])
        self.assertEqual(self.decision("rm -rf build"), "ask")
        self.assertEqual(self.decision("rm -rf build"), "ask")
        self.assertEqual(self.wev("approval", "show", request["id"])["status"], "granted")

    def test_other_tools_and_odd_payloads_are_ignored(self) -> None:
        self.start()
        cwd = str(self.work)
        for payload in (
            {"cwd": cwd, "tool_name": "Edit", "tool_input": {"file_path": SECRET_FILE}},
            {"cwd": cwd, "tool_name": "Bash"},
            {"cwd": cwd, "tool_name": "Bash", "tool_input": "rm -rf /"},
            {"cwd": cwd, "tool_name": "Bash", "tool_input": {"command": 5}},
            {"cwd": cwd, "tool_name": "Bash", "tool_input": {"command": "   "}},
            {"cwd": cwd},
            {},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.hook("pre-tool-use", payload), (0, "", ""))


class DecideCommandTests(unittest.TestCase):
    """``decide_command`` against the real policy, without any run on disk."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.policy = wiring.build_grantless_policy(load_config(), self.root)

    def decide(
        self, command: str, mode: Mode = Mode.EXECUTE, risk: RiskLevel = RiskLevel.LOW
    ) -> str:
        root = str(self.root)
        context = bash_guard.GuardContext(mode, risk, self.policy, root, root)
        with i18n.use_language("en"):
            return bash_guard.decide_command(command, context).decision

    def test_each_mode(self) -> None:
        for mode in (Mode.EXECUTE, Mode.AUTO):
            self.assertEqual(self.decide("make test", mode), "")
            self.assertEqual(self.decide("rm -rf x", mode), "ask")
        self.assertEqual(self.decide("make test", Mode.PLAN), "deny")
        self.assertEqual(self.decide("git status", Mode.PLAN), "")
        self.assertEqual(self.decide("git status | cat", Mode.PLAN), "ask")

    def test_nothing_to_run_is_no_opinion(self) -> None:
        for command in ("", "   ", "# just a comment"):
            self.assertEqual(self.decide(command), "")

    def test_an_assignment_alone_is_not_nothing(self) -> None:
        self.assertEqual(self.decide("FOO=bar"), "ask")
        self.assertEqual(self.decide("FOO=bar", Mode.PLAN), "deny")

    def test_severity_order(self) -> None:
        self.assertEqual(bash_guard.SEVERITY, ("", "ask", "deny"))


class FailureTests(HookCase):
    """Unreadable input is silent without a run; with a run, the Bash pre-check asks."""

    BASH = {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}

    def note(self, name: str, payload: Any, *argv: str) -> str:
        code, out, err = self.hook(name, payload, *argv)
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(err.count("\n"), 1, err)
        self.assertIn(f"wev hook {name}: the engine could not act", err)
        return err

    def asked(self, payload: Any, *argv: str) -> str:
        code, out, _ = self.hook("pre-tool-use", payload, *argv)
        self.assertEqual(code, 0)
        specific = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "ask")
        return str(specific["permissionDecisionReason"])

    def test_bad_stdin_json_is_silent_without_a_run(self) -> None:
        for text in ("", "{not json", "[1, 2]", '"text"', "null", "{" * 5000):
            for name in hook_cmd.HOOKS:
                with self.subTest(text=text[:12], name=name):
                    self.assertIn("hook_bad_input", self.note(name, text))

    def test_bad_stdin_json_asks_when_a_run_is_active(self) -> None:
        self.start()
        for text in ("", "{not json", "[1, 2]", '"text"', "null", "{" * 5000):
            with self.subTest(text=text[:12]):
                self.assertIn("could not be read", self.asked(text))
            for name in ("session-context", "prompt-reminder"):
                with self.subTest(text=text[:12], name=name):
                    self.assertIn("hook_bad_input", self.note(name, text))

    def test_corrupt_state_asks_and_is_left_untouched(self) -> None:
        self.start()
        state = self.work / ".wev" / "runs" / RUN / STATE_FILE
        for broken in ("{broken", "[]", '{"phase": 3}', '{"phase": "execute"}'):
            state.write_text(broken, encoding="utf-8")
            with self.subTest(broken=broken):
                self.assertIn("cannot be read", self.asked({"cwd": str(self.work), **self.BASH}))
                for name in ("session-context", "prompt-reminder"):
                    self.assertEqual(self.hook(name, {"cwd": str(self.work)}), (0, "", ""))
            self.assertEqual(state.read_text(encoding="utf-8"), broken)

    def test_a_corrupt_approvals_file_changes_nothing_for_the_hook(self) -> None:
        self.start()
        (self.work / ".wev" / "approvals.json").write_text("{broken", encoding="utf-8")
        reason = self.asked({"cwd": str(self.work), **self.BASH})
        self.assertIn("removes files", reason)

    def test_a_bad_configuration_on_the_command_line_is_ignored(self) -> None:
        self.start()
        (self.work / "bad.json").write_text('{"harness": {"planning": "x"}}', encoding="utf-8")
        payload = {"cwd": str(self.work), **self.BASH}
        for config in ("bad.json", "missing.json"):
            self.assertIn("removes files", self.asked(payload, "--config", config))

    def test_an_unexpected_exception_leaves_a_note_without_its_message(self) -> None:
        self.start()
        payload = {"cwd": str(self.work), "tool_name": "Bash", "tool_input": {"command": "ls"}}

        def explode(*_: object) -> str:
            raise RuntimeError("secret detail")

        for name in set(hook_cmd.HOOKS) - {"pre-tool-use"}:
            with self.subTest(name=name), mock.patch.dict(hook_cmd.HOOKS, {name: explode}):
                note = self.note(name, payload)
                self.assertIn("RuntimeError", note)
                self.assertNotIn("secret detail", note)
        with mock.patch.dict(hook_cmd.HOOKS, {"pre-tool-use": explode}):
            code, out, err = self.hook("pre-tool-use", payload)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertIn("RuntimeError", out + err)
        self.assertNotIn("secret detail", out + err)
        self.assertEqual((code, err.count("\n")), (0, 1))

    def test_the_note_is_localized(self) -> None:
        self.assertIn("não conseguiu agir", self.hook("pre-tool-use", "{", "--lang", "pt-BR")[2])


class HooksFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(HOOKS_FILE.read_text(encoding="utf-8"))

    def entries(self) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
        """Every ``wev hook`` entry; the daily version check is covered separately."""
        return [
            (event, group, hook)
            for event, groups in self.data["hooks"].items()
            for group in groups
            for hook in group["hooks"]
            if " hook " in hook["command"]
        ]

    def test_hooks_json_has_startup_entry(self) -> None:
        groups = self.data["hooks"]["SessionStart"]
        startup = [g for g in groups if g.get("matcher") == "startup"]
        self.assertEqual(len(startup), 1)
        self.assertEqual(
            startup[0]["hooks"],
            [
                {
                    "type": "command",
                    "command": '"${CLAUDE_PLUGIN_ROOT}/bin/wev" skills check --daily',
                    "timeout": 15,
                }
            ],
        )
        self.assertIn("compact|resume", [g.get("matcher") for g in groups])

    def test_it_declares_the_three_events_with_their_matchers(self) -> None:
        self.assertEqual(list(self.data), ["hooks"])
        self.assertEqual(
            sorted(self.data["hooks"]), ["PreToolUse", "SessionStart", "UserPromptSubmit"]
        )
        matchers = {event: group.get("matcher") for event, group, _ in self.entries()}
        self.assertEqual(
            matchers,
            {"SessionStart": "compact|resume", "UserPromptSubmit": None, "PreToolUse": "Bash"},
        )

    def test_every_command_runs_an_existing_wev_hook_subcommand_through_the_plugin_root(
        self,
    ) -> None:
        prefix = '"${CLAUDE_PLUGIN_ROOT}/bin/wev" hook '
        expected = {
            "SessionStart": "session-context",
            "UserPromptSubmit": "prompt-reminder",
            "PreToolUse": "pre-tool-use",
        }
        seen = {}
        for event, _, hook in self.entries():
            self.assertEqual(sorted(hook), ["command", "timeout", "type"])
            self.assertEqual(hook["type"], "command")
            self.assertTrue(hook["command"].startswith(prefix), hook["command"])
            name = hook["command"][len(prefix) :]
            self.assertIn(name, hook_cmd.HOOKS)
            help_run = subprocess.run(
                [sys.executable, str(WEV), "hook", name, "--help"],
                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, check=False,
            )  # fmt: skip
            self.assertEqual(help_run.returncode, 0, help_run.stderr)
            self.assertIsInstance(hook["timeout"], int)
            self.assertTrue(1 <= hook["timeout"] <= 10)
            seen[event] = name
        self.assertEqual(seen, expected)
        self.assertEqual(sorted(seen.values()), sorted(hook_cmd.HOOKS))


class EndToEndTests(unittest.TestCase):
    """``bin/wev hook pre-tool-use`` as a subprocess, the way Claude Code would run it."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve() / "repo"
        (self.repo / ".git").mkdir(parents=True)
        self.elsewhere = Path(tmp.name).resolve() / "elsewhere"
        self.elsewhere.mkdir()

    def wev(
        self, *argv: str, stdin: str = "", cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k not in ("WEV_LANG", "WEV_DEBUG")}
        return subprocess.run(
            [sys.executable, str(WEV), "--lang", "en", *argv],
            input=stdin, capture_output=True, text=True, timeout=60, check=False,
            cwd=cwd or self.repo, env={**env, "LANG": "C"},
        )  # fmt: skip

    def hook(self, command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        payload = {
            "session_id": "abc",
            "cwd": str(cwd),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        return self.wev("hook", "pre-tool-use", stdin=json.dumps(payload), cwd=self.elsewhere)

    def test_deny_ask_silence_and_fail_safe_from_a_real_process(self) -> None:
        no_run = self.hook("rm -rf build", self.repo)
        self.assertEqual((no_run.returncode, no_run.stderr), (0, ""))
        reason = json.loads(no_run.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(reason.startswith(NO_RUN), reason)
        self.assertFalse((self.repo / ".wev").exists())
        self.assertEqual(self.hook("git status", self.repo).stdout, "")
        started = self.wev("run", "start", "--objective", "Tidy up", "--files", "1",
                           "--mode", "execute", "--run-id", "e2e")  # fmt: skip
        self.assertEqual(started.returncode, 0, started.stderr)

        allowed = self.hook("git status", self.repo)
        self.assertEqual((allowed.returncode, allowed.stdout, allowed.stderr), (0, "", ""))

        asked = self.hook("ls && rm -rf build", self.repo)
        self.assertEqual((asked.returncode, asked.stderr), (0, ""))
        decision = json.loads(asked.stdout)["hookSpecificOutput"]
        self.assertEqual(
            (decision["hookEventName"], decision["permissionDecision"]), ("PreToolUse", "ask")
        )

        denied = self.hook("cat " + SECRET_FILE, self.repo)
        self.assertEqual(denied.returncode, 0)
        self.assertEqual(
            json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"], "deny"
        )

        outside = self.hook("rm -rf build", self.elsewhere)
        self.assertEqual((outside.returncode, outside.stderr), (0, ""))
        reason = json.loads(outside.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(reason.startswith(NO_RUN), reason)

        (self.repo / ".wev" / "runs" / "e2e" / STATE_FILE).write_text("{", encoding="utf-8")
        for command in ("rm -rf build", "ls"):
            broken = self.hook(command, self.repo)
            self.assertEqual((broken.returncode, broken.stderr), (0, ""))
            answer = json.loads(broken.stdout)["hookSpecificOutput"]
            self.assertEqual(answer["permissionDecision"], "ask")
            self.assertIn("cannot be read", answer["permissionDecisionReason"])

    def test_the_brief_hooks_from_a_real_process(self) -> None:
        self.wev("run", "start", "--objective", "Tidy up", "--files", "1", "--run-id", "e2e")
        payload = json.dumps({"session_id": "abc", "cwd": str(self.repo), "source": "compact"})
        for name in ("session-context", "prompt-reminder"):
            run = self.wev("hook", name, stdin=payload, cwd=self.elsewhere)
            self.assertEqual((run.returncode, run.stderr), (0, ""), name)
            self.assertIn("wev run e2e: mode auto", run.stdout)
        finished = self.wev("run", "finish")
        self.assertEqual(finished.returncode, 0, finished.stderr)
        for name in ("session-context", "prompt-reminder"):
            run = self.wev("hook", name, stdin=payload, cwd=self.elsewhere)
            self.assertEqual((run.returncode, run.stdout, run.stderr), (0, "", ""), name)


if __name__ == "__main__":
    unittest.main()
