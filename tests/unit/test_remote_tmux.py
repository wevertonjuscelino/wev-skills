from __future__ import annotations

import json
import unittest

from tests.fixtures.fake_remote import FakeGate, make_controller
from tests.unit._remote_tmux_helpers import ARGV, NAME, STAGING, STEM, TOKEN, Base
from wev_skills.core.contracts import Mode, PermissionOutcome, RiskLevel, RunStatus
from wev_skills.core.errors import (
    ApprovalRequired,
    PermissionDenied,
    RemoteError,
    ValidationError,
)
from wev_skills.remote.session import (
    RemoteRun,
    derive_status,
    owner_token,
    parse_exit_code,
    run_paths,
    session_name,
    validate_base_dir,
)


class NamingTests(unittest.TestCase):
    def test_session_name_shape(self) -> None:
        self.assertRegex(NAME, r"^wev-t-1-[0-9a-f]{8}$")
        messy = session_name("Fix: Login / Bug #42!", "h")
        self.assertEqual(messy, session_name("fix-login-bug-42", "h"))
        self.assertNotEqual(session_name("t", "host-a"), session_name("t", "host-b"))

    def test_task_slug_is_truncated(self) -> None:
        name = session_name("x" * 200, "h")
        self.assertEqual(len(name), len("wev-") + 32 + len("-") + 8)

    def test_task_ids_that_reduce_to_nothing_are_rejected(self) -> None:
        for bad in ("", "---", "!!!", " ", "çã"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                session_name(bad, "h")

    def test_token_separates_task_ids_sharing_a_slug(self) -> None:
        self.assertEqual(session_name("a b", "h"), session_name("a-b", "h"))
        self.assertNotEqual(owner_token("a b", "h"), owner_token("a-b", "h"))
        self.assertNotEqual(run_paths("~/x", "a b", "h"), run_paths("~/x", "a-b", "h"))

    def test_base_dir_validation(self) -> None:
        self.assertEqual(validate_base_dir("~/.wev/remote/"), "~/.wev/remote")
        self.assertEqual(validate_base_dir("/var/tmp/wev"), "/var/tmp/wev")
        for bad in ("", "~", "~/../etc", "/a/../b", "a b", "$HOME/x", "-x", "~/a;b", "~user/x"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate_base_dir(bad)

    def test_remote_run_round_trips(self) -> None:
        run = RemoteRun("T-1", "h", "wev-t-1-x", ("a", "b c"), 1.5, "l", "e", "tok")
        self.assertEqual(RemoteRun.from_dict(json.loads(json.dumps(run.to_dict()))), run)


class StatusRuleTests(unittest.TestCase):
    def test_exit_file_parsing(self) -> None:
        self.assertEqual(parse_exit_code("0\n"), 0)
        self.assertEqual(parse_exit_code(" 124 "), 124)
        for bad in ("", "\n", "abc", "-1", "1 2", "256", "0x0", "1.0", "0\n0"):
            with self.subTest(bad=bad):
                self.assertIsNone(parse_exit_code(bad))

    def test_decision_table(self) -> None:
        cases = [
            ((True, True, "0\n"), (RunStatus.PASSED, 0)),
            ((True, True, "3\n", True), (RunStatus.FAILED, 3)),
            ((False, False, "0\n", True), (RunStatus.PASSED, 0)),
            ((False, False, "1", True), (RunStatus.FAILED, 1)),
            ((False, False, "0\n"), (RunStatus.UNKNOWN, None)),
            ((False, False, "1", False), (RunStatus.UNKNOWN, None)),
            ((True, False, "0\n"), (RunStatus.UNKNOWN, None)),
            ((True, False, "3\n", True), (RunStatus.UNKNOWN, None)),
            ((False, False, "garbage", True), (RunStatus.UNKNOWN, None)),
            ((True, True, None), (RunStatus.RUNNING, None)),
            ((True, False, None), (RunStatus.UNKNOWN, None)),
            ((False, False, None), (RunStatus.UNKNOWN, None)),
            ((True, True, "garbage"), (RunStatus.UNKNOWN, None)),
            ((True, True, ""), (RunStatus.UNKNOWN, None)),
        ]
        for args, (status, code) in cases:
            with self.subTest(args=args):
                got = derive_status(*args)
                self.assertEqual((got.status, got.exit_code), (status, code))
                self.assertTrue(got.reason)

    def test_an_untrusted_exit_file_says_which_evidence_is_missing(self) -> None:
        self.assertIn("not owned", derive_status(True, False, "0\n").reason)
        self.assertIn("recorded", derive_status(False, False, "0\n").reason)


class PreflightTests(Base):
    def test_reports_host_facts(self) -> None:
        report = self.ctl.preflight("staging-1")
        self.assertEqual((report.hostname, report.user), ("fake-host", "deploy"))
        self.assertEqual((report.tmux_available, report.tmux_version), (True, "tmux 3.4"))
        self.assertTrue(report.timeout_available)
        self.assertEqual(report.base_dir, "~/.wev/remote")
        self.assertEqual((report.base_dir_exists, report.base_dir_writable), (False, False))
        self.host.dirs.add(".wev/remote")
        self.assertTrue(self.ctl.preflight("staging-1").base_dir_writable)

    def test_sends_only_harmless_commands(self) -> None:
        self.ctl.preflight("staging-1")
        expected = [
            "tmux -V",
            "hostname",
            "id -un",
            "timeout --version",
            "test -d .wev/remote",
            "test -w .wev/remote",
        ]
        self.assertEqual(self.host.remote_strings, expected)

    def test_missing_tmux_is_reported_and_never_installed(self) -> None:
        self.host.tmux_installed = False
        report = self.ctl.preflight("staging-1")
        self.assertEqual((report.tmux_available, report.tmux_version), (False, ""))
        text = " ".join(self.host.remote_strings)
        for word in ("install", "apt", "yum", "dnf", "brew", "apk", "sudo", "curl", "wget"):
            self.assertNotIn(word, text)

    def test_unlisted_host_and_dropped_connection(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.ctl.preflight("other")
        self.assertEqual(self.host.commands, [])
        self.host.drop_connection("Host key verification failed.")
        with self.assertRaises(RemoteError) as ctx:
            self.ctl.preflight("staging-1")
        self.assertEqual(ctx.exception.code, "remote_host_key_failed")


class StartTests(Base):
    def test_exact_commands_sent(self) -> None:
        run = self.start()
        script = (
            f"pytest -q tests/unit >> {STEM}.log 2>&1 < /dev/null\n"
            "rc=$?\n"
            f"printf '%s\\n' \"$rc\" > {STEM}.exit.tmp && mv -f -- {STEM}.exit.tmp {STEM}.exit"
        )
        prepare = (
            "sh",
            "-c",
            'umask 077 && mkdir -p -- "$1" && rm -f -- "$2" "$3" && : >> "$4" '
            '&& printf \'%s\\n\' "$6" > "$5"',
            "wev",
            ".wev/remote",
            f"{STEM}.exit",
            f"{STEM}.exit.tmp",
            f"{STEM}.log",
            f"{STEM}.sh",
            script,
        )
        meta = json.dumps({"argv": list(ARGV), "started_at": 1000.0})
        expected = [
            ("tmux", "has-session", "-t", f"={NAME}"),
            prepare,
            ("tmux", "new-session", "-d", "-s", NAME),
            ("tmux", "set-option", "-t", f"={NAME}:", "@wev_owner", TOKEN),
            ("tmux", "set-option", "-t", f"={NAME}:", "@wev_meta", meta),
            ("tmux", "send-keys", "-t", f"={NAME}:", f"cd && sh {STEM}.sh", "Enter"),
        ]
        self.assertEqual(self.host.commands, expected)
        self.assertEqual(self.host.unknown, [])
        self.assertEqual(self.host.sessions[NAME].launched_script, f"{STEM}.sh")
        want = RemoteRun(
            "T-1", "staging-1", NAME, ARGV, 1000.0,
            f"~/{STEM}.log", f"~/{STEM}.exit", TOKEN,
        )  # fmt: skip
        self.assertEqual(run, want)

    def test_gate_is_asked_with_the_real_mode_and_risk(self) -> None:
        self.start()
        self.assertEqual(self.gate.calls, [(ARGV, Mode.EXECUTE, RiskLevel.LOW)])

    def test_gate_deny_and_needs_approval(self) -> None:
        self.gate.outcome = PermissionOutcome.DENY
        with self.assertRaises(PermissionDenied) as denied:
            self.start()
        self.assertEqual(denied.exception.code, "remote_command_denied")
        self.gate.outcome = PermissionOutcome.NEEDS_APPROVAL
        with self.assertRaises(ApprovalRequired) as needed:
            self.start()
        self.assertEqual(needed.exception.details["action"], "staging-1 pytest -q tests/unit")
        self.assertEqual(self.host.commands, [])

    def test_needs_approval_proceeds_only_with_the_exact_action_approved(self) -> None:
        gate = FakeGate(PermissionOutcome.NEEDS_APPROVAL)
        wrong = make_controller(self.host, (STAGING,), gate, approved={"staging-1 pytest -q"})
        with self.assertRaises(ApprovalRequired):
            wrong.start("staging-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        right = make_controller(
            self.host, (STAGING,), gate, approved={"staging-1 pytest -q tests/unit"}
        )
        self.assertEqual(
            right.start("staging-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW).session, NAME
        )

    def test_invalid_input_is_rejected_before_any_remote_command(self) -> None:
        bad_calls = [
            ("T-1", [], None),
            ("T-1", [""], None),
            ("T-1", ["-rf"], None),
            ("T-1", "pytest -q", None),
            ("T-1", ["a\x00b"], None),
            ("!!!", ["true"], None),
            ("T-1", ["true"], 0),
            ("T-1", ["true"], -5),
            ("T-1", ["true"], True),
            ("T-1", ["true"], 1.5),
        ]
        for task, argv, timeout in bad_calls:
            with (
                self.subTest(task=task, argv=argv, timeout=timeout),
                self.assertRaises(ValidationError),
            ):
                self.ctl.start(  # type: ignore[call-overload]
                    "staging-1",
                    task,
                    argv,
                    Mode.EXECUTE,
                    RiskLevel.LOW,
                    timeout,  # type: ignore
                )
        self.assertEqual(self.host.commands, [])

    def test_timeout_prefix_when_available(self) -> None:
        self.start(timeout_seconds=90)
        self.assertIn(("timeout", "--version"), self.host.commands)
        script = self.host.files[f"{STEM}.sh"]
        self.assertTrue(script.startswith("timeout 90 pytest -q tests/unit >> "))

    def test_timeout_requested_but_unavailable_starts_nothing(self) -> None:
        self.host.has_timeout = False
        with self.assertRaises(RemoteError) as ctx:
            self.start(timeout_seconds=90)
        self.assertEqual(ctx.exception.code, "remote_timeout_unavailable")
        self.assertEqual(self.host.sessions, {})

    def test_no_timeout_probe_or_prefix_without_a_timeout(self) -> None:
        self.start()
        self.assertNotIn(("timeout", "--version"), self.host.commands)
        self.assertFalse(self.host.files[f"{STEM}.sh"].startswith("timeout"))

    def test_start_clears_a_stale_exit_file(self) -> None:
        self.host.files[f"{STEM}.exit"] = "0\n"
        self.start()
        self.assertNotIn(f"{STEM}.exit", self.host.files)
        self.assertEqual(self.ctl.status("staging-1", "T-1").status, RunStatus.RUNNING)

    def test_duplicate_start_returns_recorded_run(self) -> None:
        first = self.start()
        before = len(self.host.commands)
        again = self.ctl.start("staging-1", "T-1", ["other", "cmd"], Mode.EXECUTE, RiskLevel.LOW)
        self.assertEqual(again, first)
        sent = self.host.commands[before:]
        self.assertEqual([c[1] for c in sent], ["has-session", "show-options", "show-options"])
        self.assertEqual(len(self.host.sessions[NAME].keys), 1)

    def test_damaged_meta_yields_unknown_argv_not_a_guess(self) -> None:
        first = self.start()
        self.host.sessions[NAME].options["@wev_meta"] = "{not json"
        again = self.start()
        self.assertEqual((again.argv, again.started_at), ((), 0.0))
        self.assertEqual(again.session, first.session)

    def test_tmux_missing_is_an_error_and_nothing_is_installed(self) -> None:
        self.host.tmux_installed = False
        with self.assertRaises(RemoteError) as ctx:
            self.start()
        self.assertEqual(ctx.exception.code, "remote_command_failed")
        self.assertEqual(len(self.host.commands), 1)

    def test_failure_before_the_marker_leaves_the_session_untouched(self) -> None:
        self.host.fail("tmux set-option")
        with self.assertRaises(RemoteError) as ctx:
            self.start()
        self.assertEqual(ctx.exception.details["step"], "set-owner")
        self.assertIn(NAME, self.host.sessions)
        self.assertFalse(any(c[1] == "kill-session" for c in self.host.commands))

    def test_failure_after_the_marker_removes_the_never_launched_session(self) -> None:
        self.host.fail("tmux send-keys")
        with self.assertRaises(RemoteError) as ctx:
            self.start()
        self.assertEqual(ctx.exception.details["step"], "send-keys")
        self.assertIs(ctx.exception.details["session_removed"], True)
        self.assertEqual(self.host.sessions, {})

    def test_host_text_in_reports_and_errors_loses_control_characters(self) -> None:
        self.host.hostname = "box\x1b[2J\x1b]0;owned\x07-1\x00"
        self.host.tmux_version = "tmux\x1b[31m 3.4\r"
        report = self.ctl.preflight("staging-1")
        self.assertEqual((report.hostname, report.tmux_version), ("box-1", "tmux 3.4"))
        self.host.fail("tmux new-session", stderr="bad\x1b[2K\x07 thing\nline two")
        with self.assertRaises(RemoteError) as ctx:
            self.start()
        self.assertEqual(ctx.exception.details["stderr"], "bad thing line two")

    def test_error_details_are_redacted(self) -> None:
        self.host.fail("tmux new-session", stderr="boom password=SECRET")
        with self.assertRaises(RemoteError) as ctx:
            self.start()
        self.assertNotIn("SECRET", json.dumps(ctx.exception.to_dict()))


if __name__ == "__main__":
    unittest.main()
