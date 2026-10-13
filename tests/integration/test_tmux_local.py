"""The real tmux command lines of ``TmuxController``, run against a local tmux without SSH.

The transport here runs the exact string that ``build_remote_command`` would hand to sshd
through ``sh -c`` on this machine, with a temporary HOME and a tmux server that lives in a
temporary ``TMUX_TMPDIR``. The default tmux server and any session in it are never touched,
and cleanup kills only the isolated server, addressed by its socket path.

The whole module is skipped when ``tmux`` is not on PATH. It is the only test that runs the
controller against a real tmux and a real shell; with tmux missing, that coverage is absent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from collections.abc import Sequence
from pathlib import Path

from tests.fixtures.fake_remote import FakeClock, FakeGate, mask_secret
from wev_skills.config import RemoteHost
from wev_skills.core.contracts import Mode, RawCommandResult, RiskLevel, RunStatus
from wev_skills.core.errors import RemoteError
from wev_skills.remote.inventory import Inventory
from wev_skills.remote.session import RemoteRun, RemoteStatus, session_name
from wev_skills.remote.tmux import TmuxController
from wev_skills.remote.transport import build_remote_command

ALIAS = "local-1"
TASK = "T-1"
HOST = RemoteHost(ALIAS, "staging", True)
COMMAND_TIMEOUT_SECONDS = 30.0
SETTLE_SECONDS = 20.0
POLL_SECONDS = 0.1
LEFTOVER_ENV = ("TMUX", "TMUX_PANE", "TMUX_TMPDIR")


class IsolatedTmuxTransport:
    """``Transport`` that runs the remote command string locally, inside one private tmux."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.tmux_dir = root / "tmux"
        self.home.mkdir()
        self.tmux_dir.mkdir()
        env = {key: value for key, value in os.environ.items() if key not in LEFTOVER_ENV}
        env.update(HOME=str(self.home), TMUX_TMPDIR=str(self.tmux_dir), SHELL="/bin/sh")
        self.env = env

    @property
    def socket(self) -> Path:
        """Where tmux puts the default socket of this private ``TMUX_TMPDIR``."""
        return self.tmux_dir / f"tmux-{os.getuid()}" / "default"

    def run(
        self, alias: str, remote_argv: Sequence[str], timeout: float | None = None
    ) -> RawCommandResult:
        command = build_remote_command(remote_argv)
        started = time.monotonic()
        proc = subprocess.run(
            ["sh", "-c", command],
            cwd=self.home,
            env=self.env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return RawCommandResult(
            tuple(remote_argv), proc.returncode, proc.stdout, proc.stderr, elapsed
        )

    def close(self) -> None:
        """Kill the private server by socket path; refuse any socket outside ``root``."""
        socket = self.socket
        if not socket.is_relative_to(self.root) or not socket.exists():
            return
        subprocess.run(
            ["tmux", "-S", str(socket), "kill-server"],
            env=self.env,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )


@unittest.skipUnless(shutil.which("tmux"), "tmux is not installed; the local tmux test is skipped")
class LocalTmuxTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.mkdtemp(prefix="wev-tmux-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.transport = IsolatedTmuxTransport(Path(tmp).resolve())
        self.addCleanup(self.transport.close)
        self.ctl = TmuxController(
            self.transport,
            Inventory([HOST]),
            FakeGate(),
            lambda action: False,
            mask_secret,
            FakeClock(),
            command_timeout=COMMAND_TIMEOUT_SECONDS,
        )

    def start(self, *argv: str, task: str = TASK) -> RemoteRun:
        return self.ctl.start(ALIAS, task, argv, Mode.EXECUTE, RiskLevel.LOW)

    def settle(self, task: str = TASK) -> RemoteStatus:
        """Poll until the run reports something other than RUNNING."""
        deadline = time.monotonic() + SETTLE_SECONDS
        status = self.ctl.status(ALIAS, task)
        while status.status is RunStatus.RUNNING and time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
            status = self.ctl.status(ALIAS, task)
        return status

    def tmux(self, *args: str) -> RawCommandResult:
        return self.transport.run(ALIAS, ("tmux", *args), COMMAND_TIMEOUT_SECONDS)

    def test_the_private_server_does_not_use_the_default_socket(self) -> None:
        self.start("sleep", "30")
        self.assertTrue(self.transport.socket.exists())
        self.assertTrue(self.transport.socket.is_relative_to(self.transport.root))

    def test_a_long_command_is_running_with_an_owned_session(self) -> None:
        run = self.start("sleep", "30")
        status = self.ctl.status(ALIAS, TASK)
        self.assertEqual(
            (status.status, status.owned, status.session_exists), (RunStatus.RUNNING, True, True)
        )
        self.assertEqual(run.session, session_name(TASK, ALIAS))
        self.assertEqual(self.ctl.list_owned(ALIAS), (run.session,))

    def test_a_command_that_succeeds_ends_passed_with_exit_zero(self) -> None:
        self.start("sh", "-c", "sleep 1; echo done")
        self.assertEqual(self.ctl.status(ALIAS, TASK).status, RunStatus.RUNNING)
        final = self.settle()
        self.assertEqual((final.status, final.exit_code), (RunStatus.PASSED, 0))

    def test_a_failing_command_ends_failed_with_its_exit_code(self) -> None:
        self.start("sh", "-c", "exit 3")
        final = self.settle()
        self.assertEqual((final.status, final.exit_code), (RunStatus.FAILED, 3))

    def test_capture_returns_the_output_of_the_command(self) -> None:
        self.start("sh", "-c", "echo hello-from-tmux; echo oops >&2")
        self.settle()
        text = self.ctl.capture(ALIAS, TASK)
        self.assertIn("hello-from-tmux", text)
        self.assertIn("oops", text)

    def test_starting_the_same_task_twice_reuses_the_session(self) -> None:
        first = self.start("sleep", "30")
        second = self.start("sleep", "30")
        self.assertEqual((second.session, second.owner_token), (first.session, first.owner_token))
        self.assertEqual(second.argv, first.argv)
        self.assertEqual(self.ctl.list_owned(ALIAS), (first.session,))

    def test_stop_removes_the_owned_session(self) -> None:
        run = self.start("sleep", "30")
        stopped = self.ctl.stop(ALIAS, TASK)
        self.assertFalse(stopped.session_exists)
        self.assertNotEqual(stopped.status, RunStatus.PASSED)
        self.assertEqual(self.tmux("has-session", "-t", f"={run.session}").exit_code, 1)
        self.assertEqual(self.ctl.list_owned(ALIAS), ())

    def test_a_foreign_session_is_never_started_over_stopped_or_listed(self) -> None:
        name = session_name(TASK, ALIAS)
        self.assertEqual(self.tmux("new-session", "-d", "-s", name).exit_code, 0)
        with self.assertRaises(RemoteError) as started:
            self.start("sleep", "30")
        self.assertEqual(started.exception.code, "remote_session_not_owned")
        with self.assertRaises(RemoteError) as stopped:
            self.ctl.stop(ALIAS, TASK)
        self.assertEqual(stopped.exception.code, "remote_session_not_owned")
        status = self.ctl.status(ALIAS, TASK)
        self.assertEqual((status.status, status.owned), (RunStatus.UNKNOWN, False))
        self.assertEqual(self.ctl.list_owned(ALIAS), ())
        self.assertEqual(self.tmux("has-session", "-t", f"={name}").exit_code, 0)


if __name__ == "__main__":
    unittest.main()
