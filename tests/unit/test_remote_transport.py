from __future__ import annotations

import json
import subprocess
import sys
import unittest
from collections.abc import Mapping, Sequence

from tests.fixtures.fake_remote import FakeRemoteHost, mask_secret
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import RemoteError, ValidationError
from wev_skills.remote.transport import SshTransport, build_remote_command, classify_ssh_failure

NASTY_ARGS = (
    "two words",
    "single'quote",
    'double"quote',
    "$HOME",
    "$(id)",
    "`id`",
    "a;b",
    "a && b | c > d",
    "line1\nline2",
    "tab\there",
    "*",
    "~",
    "",
    "-o",
    "back\\slash",
    "#comment",
    "!bang",
)
ECHO_ARGV = "import json, sys; print(json.dumps(sys.argv[1:]))"


class ScriptedRunner:
    def __init__(self, result: RawCommandResult) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], str | None, float | None, object]] = []

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> RawCommandResult:
        self.calls.append((tuple(argv), cwd, timeout, env))
        return self.result


def result(exit_code: int | None, stderr: str = "", timed_out: bool = False) -> RawCommandResult:
    return RawCommandResult(("ssh",), exit_code, "out", stderr, 3, timed_out)


class BuildArgvTests(unittest.TestCase):
    def test_exact_local_argv(self) -> None:
        argv = SshTransport(FakeRemoteHost()).build_argv("staging-1", ["tmux", "-V"])
        expected = ("ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes")
        expected += ("-o", "ConnectTimeout=10", "--", "staging-1", "tmux -V")
        self.assertEqual(argv, expected)

    def test_connect_timeout_is_configurable_and_validated(self) -> None:
        argv = SshTransport(FakeRemoteHost(), connect_timeout=3).build_argv("h", ["true"])
        self.assertIn("ConnectTimeout=3", argv)
        for bad in (0, -1, 601, 2.5, "10", True):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                SshTransport(FakeRemoteHost(), connect_timeout=bad)  # type: ignore[arg-type]

    def test_never_adds_keys_passwords_forwarding_or_weak_host_checks(self) -> None:
        argv = SshTransport(FakeRemoteHost()).build_argv("h", ["echo", "-i", "-A"])
        options = argv[: argv.index("--")]
        for forbidden in ("-i", "-A", "-p", "-l", "-F", "-J", "-t", "-tt"):
            self.assertNotIn(forbidden, options)
        joined = " ".join(options)
        for text in ("StrictHostKeyChecking=no", "accept-new", "UserKnownHostsFile", "Forward"):
            self.assertNotIn(text, joined)
        self.assertNotIn("sshpass", argv)

    def test_alias_is_validated_before_anything_runs(self) -> None:
        runner = ScriptedRunner(result(0))
        transport = SshTransport(runner)
        for alias in ("-oProxyCommand=evil", "user@host", "a b", "host;id", ""):
            with self.subTest(alias=alias), self.assertRaises(ValidationError):
                transport.run(alias, ["true"])
        self.assertEqual(runner.calls, [])

    def test_empty_or_malformed_remote_argv_is_rejected(self) -> None:
        for bad in ([], [""], ["a", "b\x00c"], ["a", 5]):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                build_remote_command(bad)  # type: ignore[arg-type]


class RemoteQuotingTests(unittest.TestCase):
    def test_remote_string_splits_back_into_the_same_arguments(self) -> None:
        host = FakeRemoteHost()
        SshTransport(host).run("h", ["printf", *NASTY_ARGS])
        self.assertEqual(host.commands[-1], ("printf", *NASTY_ARGS))
        self.assertEqual(len(host.local_argvs[-1]), 10)

    def test_a_real_posix_shell_delivers_each_argument_intact(self) -> None:
        """The remote side hands the string to a shell: run it through a local ``sh``."""
        remote = build_remote_command([sys.executable, "-c", ECHO_ARGV, *NASTY_ARGS])
        done = subprocess.run(["sh", "-c", remote], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(done.stdout), list(NASTY_ARGS))

    def test_injection_attempt_runs_nothing_extra(self) -> None:
        marker = "wev-injection-marker"
        attack = f"x; echo {marker}; $(echo {marker}) `echo {marker}`\necho {marker}"
        remote = build_remote_command([sys.executable, "-c", ECHO_ARGV, attack])
        done = subprocess.run(["sh", "-c", remote], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(done.stdout), [attack])
        self.assertEqual(done.stdout.count("\n"), 1)


class RunTests(unittest.TestCase):
    def test_passes_timeout_and_no_cwd_or_env(self) -> None:
        runner = ScriptedRunner(result(0))
        outcome = SshTransport(runner).run("h", ["true"], timeout=7.5)
        self.assertIs(outcome, runner.result)
        self.assertEqual(runner.calls[0][1:], (None, 7.5, None))

    def test_non_zero_remote_exit_is_returned_not_raised(self) -> None:
        runner = ScriptedRunner(result(1, "can't find session"))
        self.assertEqual(SshTransport(runner).run("h", ["tmux", "has-session"]).exit_code, 1)

    def test_exit_255_is_classified(self) -> None:
        cases = {
            "Host key verification failed.": ("host_key", "remote_host_key_failed"),
            "@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @": (
                "host_key",
                "remote_host_key_failed",
            ),
            "deploy@h: Permission denied (publickey).": (
                "authentication",
                "remote_authentication_failed",
            ),
            "ssh: connect to host h port 22: Connection refused": (
                "connection",
                "remote_connection_failed",
            ),
            "": ("connection", "remote_connection_failed"),
        }
        for stderr, (reason, code) in cases.items():
            with self.subTest(stderr=stderr), self.assertRaises(RemoteError) as ctx:
                SshTransport(ScriptedRunner(result(255, stderr))).run("h", ["true"])
            self.assertEqual(ctx.exception.code, code)
            self.assertEqual(ctx.exception.details["reason"], reason)
            self.assertEqual(classify_ssh_failure(stderr), reason)

    def test_stderr_is_redacted_before_entering_the_error(self) -> None:
        runner = ScriptedRunner(result(255, "Connection closed token=SECRET"))
        with self.assertRaises(RemoteError) as ctx:
            SshTransport(runner, redactor=mask_secret).run("h", ["true"])
        self.assertEqual(ctx.exception.details["stderr"], "Connection closed token=[REDACTED]")
        self.assertNotIn("SECRET", json.dumps(ctx.exception.to_dict()))

    def test_stderr_loses_control_characters_before_redaction(self) -> None:
        noisy = "Connection\x1b[2J closed\x07\r\ntoken=SEC\x1b[0mRET\x00"
        with self.assertRaises(RemoteError) as ctx:
            SshTransport(ScriptedRunner(result(255, noisy)), redactor=mask_secret).run(
                "h", ["true"]
            )
        self.assertEqual(ctx.exception.details["stderr"], "Connection closed token=[REDACTED]")

    def test_without_a_redactor_stderr_is_left_out(self) -> None:
        runner = ScriptedRunner(result(255, "Connection closed token=SECRET"))
        with self.assertRaises(RemoteError) as ctx:
            SshTransport(runner).run("h", ["true"])
        self.assertNotIn("stderr", ctx.exception.details)
        self.assertNotIn("SECRET", json.dumps(ctx.exception.to_dict()))

    def test_timeout_is_a_remote_error_never_a_result(self) -> None:
        for outcome in (result(None, timed_out=True), result(None)):
            with self.subTest(outcome=outcome), self.assertRaises(RemoteError) as ctx:
                SshTransport(ScriptedRunner(outcome)).run("h", ["true"])
            self.assertEqual(ctx.exception.code, "remote_timeout")


if __name__ == "__main__":
    unittest.main()
