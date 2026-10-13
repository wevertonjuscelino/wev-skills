from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.fixtures.fake_remote import FakeRemoteHost, MemoryRunRecords, make_controller
from tests.unit._remote_tmux_helpers import ARGV, NAME, STAGING, STEM, Base
from wev_skills.core.contracts import Mode, RiskLevel, RunStatus
from wev_skills.core.errors import (
    NotFound,
    PermissionDenied,
    RemoteError,
    ValidationError,
)
from wev_skills.remote.session import (
    RemoteRun,
    RemoteStatus,
    build_wrapper_script,
    owner_token,
    run_paths,
)


class WrapperScriptTests(unittest.TestCase):
    """Runs the generated script with a real local ``sh`` (no tmux, no network)."""

    def run_wrapper(self, argv: tuple[str, ...]) -> tuple[Path, str]:
        host = FakeRemoteHost()
        ctl = make_controller(host, (STAGING,))
        ctl.start("staging-1", "T-1", argv, Mode.EXECUTE, RiskLevel.LOW)
        prepare = next(s for s in host.remote_strings if s.startswith("sh -c"))
        launch = host.sessions[NAME].keys[0][0]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
        subprocess.run(["sh", "-c", prepare], cwd=home, env=env, check=True)
        subprocess.run(["sh", "-c", launch], cwd="/", env=env, check=False)
        return home, STEM

    def test_exit_status_and_output_are_recorded(self) -> None:
        home, stem = self.run_wrapper(("sh", "-c", "echo out; echo err >&2; exit 3"))
        self.assertEqual((home / f"{stem}.exit").read_text(), "3\n")
        self.assertEqual((home / f"{stem}.log").read_text(), "out\nerr\n")
        self.assertFalse((home / f"{stem}.exit.tmp").exists())
        self.assertEqual((home / f"{stem}.log").stat().st_mode & 0o077, 0)

    def test_success_records_zero(self) -> None:
        home, stem = self.run_wrapper(("true",))
        self.assertEqual((home / f"{stem}.exit").read_text(), "0\n")

    def test_missing_program_records_127(self) -> None:
        home, stem = self.run_wrapper(("wev-no-such-program-xyz",))
        self.assertEqual((home / f"{stem}.exit").read_text(), "127\n")

    def test_hostile_arguments_stay_single_arguments(self) -> None:
        nasty = ("a b", "x; touch pwned", "$(touch pwned)", "`touch pwned`", "q'q\"q", "l1\nl2")
        home, stem = self.run_wrapper(("printf", "[%s]", *nasty))
        self.assertEqual((home / f"{stem}.log").read_text(), "".join(f"[{a}]" for a in nasty))
        self.assertEqual((home / f"{stem}.exit").read_text(), "0\n")
        self.assertFalse((home / "pwned").exists())

    def test_script_text_with_timeout(self) -> None:
        paths = run_paths("/var/tmp/wev", "T-1", "staging-1")
        script = build_wrapper_script(("make", "test target"), paths, 30)
        self.assertTrue(script.startswith("timeout 30 make 'test target' >> /var/tmp/wev/"))


class StatusTests(Base):
    def status(self) -> RemoteStatus:
        return self.ctl.status("staging-1", "T-1")

    def test_running_then_passed_then_failed(self) -> None:
        self.start()
        running = self.status()
        self.assertEqual(
            (running.status, running.exit_code, running.session_exists, running.owned),
            (RunStatus.RUNNING, None, True, True),
        )
        self.host.finish_run(NAME, 0)
        self.assertEqual((self.status().status, self.status().exit_code), (RunStatus.PASSED, 0))
        self.host.finish_run(NAME, 2)
        self.assertEqual((self.status().status, self.status().exit_code), (RunStatus.FAILED, 2))

    def test_exact_commands_sent(self) -> None:
        self.start()
        before = len(self.host.remote_strings)
        self.status()
        expected = [
            f"tmux has-session -t ={NAME}",
            f"tmux show-options -qv -t ={NAME}: @wev_owner",
            f"cat -- {STEM}.exit",
        ]
        self.assertEqual(self.host.remote_strings[before:], expected)

    def test_exit_file_after_the_session_is_gone_needs_a_recorded_start(self) -> None:
        self.start()
        self.host.finish_run(NAME, 1)
        self.host.reboot(keep_files=True)
        got = self.status()
        self.assertEqual(
            (got.status, got.exit_code, got.session_exists), (RunStatus.UNKNOWN, None, False)
        )
        self.assertIn("recorded", got.reason)

    def test_exit_file_decides_after_the_session_is_gone_when_the_start_was_recorded(self) -> None:
        records = MemoryRunRecords()
        ctl = make_controller(self.host, (STAGING,), self.gate, records=records)
        run = ctl.start("staging-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        self.assertEqual(records.find("T-1", "staging-1"), run)
        self.host.finish_run(NAME, 1)
        self.host.reboot(keep_files=True)
        got = ctl.status("staging-1", "T-1")
        self.assertEqual(
            (got.status, got.exit_code, got.session_exists), (RunStatus.FAILED, 1, False)
        )

    def test_planted_exit_file_is_never_passed_or_failed(self) -> None:
        records = MemoryRunRecords()
        ctl = make_controller(self.host, (STAGING,), self.gate, records=records)
        self.host.files[f"{STEM}.exit"] = "0\n"
        nothing = ctl.status("staging-1", "T-1")
        self.assertEqual((nothing.status, nothing.exit_code), (RunStatus.UNKNOWN, None))
        self.assertIn("recorded", nothing.reason)
        self.host.add_foreign_session(NAME, {"@wev_owner": owner_token("T-2", "staging-1")})
        foreign = ctl.status("staging-1", "T-1")
        self.assertEqual((foreign.status, foreign.exit_code), (RunStatus.UNKNOWN, None))
        self.assertIn("not owned", foreign.reason)

    def test_a_record_for_another_task_or_host_is_not_evidence(self) -> None:
        records = MemoryRunRecords()
        ctl = make_controller(self.host, (STAGING,), self.gate, records=records)
        ctl.start("staging-1", "T-2", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        self.host.reboot(keep_files=True)
        self.host.files[f"{STEM}.exit"] = "0\n"
        self.assertEqual(ctl.status("staging-1", "T-1").status, RunStatus.UNKNOWN)

    def test_a_failed_launch_records_nothing(self) -> None:
        records = MemoryRunRecords()
        ctl = make_controller(self.host, (STAGING,), self.gate, records=records)
        self.host.fail("tmux send-keys")
        with self.assertRaises(RemoteError):
            ctl.start("staging-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        self.assertEqual(records.runs, {})

    def test_unreadable_records_make_the_status_unknown_with_the_reason(self) -> None:
        class Broken(MemoryRunRecords):
            def find(self, task_id: str, alias: str) -> RemoteRun | None:
                raise ValidationError("remote_records_unreadable", "records are damaged")

        self.host.files[f"{STEM}.exit"] = "0\n"
        ctl = make_controller(self.host, (STAGING,), self.gate, records=Broken())
        got = ctl.status("staging-1", "T-1")
        self.assertEqual((got.status, got.exit_code), (RunStatus.UNKNOWN, None))
        self.assertIn("records are damaged", got.reason)
        with self.assertRaises(ValidationError):
            ctl.start("staging-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        self.assertEqual(self.host.sessions, {})

    def test_unparseable_exit_file_is_unknown(self) -> None:
        self.start()
        for content in ("", "ok\n", "0 extra\n", "999\n"):
            with self.subTest(content=content):
                self.host.files[f"{STEM}.exit"] = content
                self.assertEqual(self.status().status, RunStatus.UNKNOWN)

    def test_foreign_session_is_unknown_with_reason(self) -> None:
        self.host.add_foreign_session(NAME)
        got = self.status()
        self.assertEqual(
            (got.status, got.session_exists, got.owned), (RunStatus.UNKNOWN, True, False)
        )
        self.assertIn("not owned", got.reason)

    def test_nothing_there_is_unknown_and_mentions_reboot(self) -> None:
        got = self.status()
        self.assertEqual((got.status, got.session_exists), (RunStatus.UNKNOWN, False))
        self.assertIn("reboot", got.reason)

    def test_transport_failure_is_unknown_not_failed(self) -> None:
        self.start()
        self.host.finish_run(NAME, 1)
        self.host.drop_connection("ssh: connect to host: Connection refused token=SECRET")
        got = self.status()
        self.assertEqual((got.status, got.exit_code), (RunStatus.UNKNOWN, None))
        self.assertIn("SSH connection failed", got.reason)
        self.assertNotIn("SECRET", got.reason)

    def test_failure_midway_through_the_check_is_unknown(self) -> None:
        self.start()
        self.host.finish_run(NAME, 0)
        self.host.fail("cat", exit_code=255, stderr="")  # connection lost on the last step
        self.assertEqual(self.status().status, RunStatus.UNKNOWN)
        self.host.fail_steps.clear()
        self.assertEqual(self.status().status, RunStatus.PASSED)
        self.host.fail("tmux has-session", exit_code=127)
        self.assertEqual(self.status().status, RunStatus.UNKNOWN)

    def test_unlisted_host_raises(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.ctl.status("other", "T-1")


class CaptureStopListTests(Base):
    def test_capture_tails_and_redacts(self) -> None:
        self.start()
        self.host.finish_run(NAME, 0, "".join(f"line {i}\n" for i in range(300)) + "key SECRET\n")
        text = self.ctl.capture("staging-1", "T-1", lines=3)
        self.assertEqual(text, "line 298\nline 299\nkey [REDACTED]\n")
        self.assertEqual(self.host.remote_strings[-1], f"tail -n 3 -- {STEM}.log")

    def test_capture_line_count_is_bounded(self) -> None:
        self.start()
        for asked, sent in ((10**9, "2000"), (0, "1"), (-4, "1"), (True, "1"), ("9", "1")):
            with self.subTest(asked=asked):
                self.ctl.capture("staging-1", "T-1", lines=asked)  # type: ignore[arg-type]
                self.assertEqual(self.host.commands[-1][2], sent)
        self.ctl.capture("staging-1", "T-1")
        self.assertEqual(self.host.commands[-1][2], "200")

    def test_capture_without_a_log_is_not_found(self) -> None:
        with self.assertRaises(NotFound):
            self.ctl.capture("staging-1", "T-1")

    def test_stop_kills_only_the_exact_owned_session(self) -> None:
        self.start()
        self.host.add_foreign_session(NAME + "-2")
        got = self.ctl.stop("staging-1", "T-1")
        self.assertEqual((got.status, got.session_exists), (RunStatus.UNKNOWN, False))
        self.assertIn("stopped", got.reason)
        kills = [s for s in self.host.remote_strings if "kill-session" in s]
        self.assertEqual(kills, [f"tmux kill-session -t ={NAME}"])
        self.assertEqual(list(self.host.sessions), [NAME + "-2"])

    def test_stop_after_completion_keeps_the_recorded_result(self) -> None:
        self.start()
        self.host.finish_run(NAME, 0)
        self.assertEqual(self.ctl.stop("staging-1", "T-1").status, RunStatus.PASSED)

    def test_stop_without_a_session_kills_nothing(self) -> None:
        got = self.ctl.stop("staging-1", "T-1")
        self.assertEqual(got.status, RunStatus.UNKNOWN)
        self.assertFalse(any("kill-session" in s for s in self.host.remote_strings))

    def test_stop_refuses_an_unowned_session(self) -> None:
        self.host.add_foreign_session(NAME, {"@wev_owner": owner_token("T-2", "staging-1")})
        with self.assertRaises(RemoteError) as ctx:
            self.ctl.stop("staging-1", "T-1")
        self.assertEqual(ctx.exception.code, "remote_session_not_owned")
        self.assertIn(NAME, self.host.sessions)

    def test_list_owned_returns_only_marked_sessions(self) -> None:
        self.assertEqual(self.ctl.list_owned("staging-1"), ())
        self.start()
        self.host.add_foreign_session("main")
        self.host.add_foreign_session("wev-looks-like-ours-00000000")
        self.host.add_foreign_session("fake|wev1-0123456789abcdef", {"@wev_owner": "nope"})
        self.host.add_foreign_session("other-task", {"@wev_owner": owner_token("T-9", "staging-1")})
        self.assertEqual(self.ctl.list_owned("staging-1"), (NAME, "other-task"))
        self.assertEqual(
            self.host.remote_strings[-1], "tmux list-sessions -F '#{session_name}|#{@wev_owner}'"
        )

    def test_list_owned_error_is_raised(self) -> None:
        self.host.tmux_installed = False
        with self.assertRaises(RemoteError):
            self.ctl.list_owned("staging-1")


if __name__ == "__main__":
    unittest.main()
