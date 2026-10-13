"""Safety properties of the remote module, exercised against the simulated host."""

from __future__ import annotations

import copy
import shlex
import unittest
from pathlib import Path

import wev_skills.remote
from tests.fixtures.fake_remote import FakeGate, FakeRemoteHost, make_controller
from wev_skills.config import RemoteHost
from wev_skills.core.contracts import Mode, PermissionOutcome, RiskLevel, RunStatus
from wev_skills.core.errors import (
    ApprovalRequired,
    PermissionDenied,
    RemoteError,
    ValidationError,
    WevError,
)
from wev_skills.remote.inventory import Inventory
from wev_skills.remote.session import (
    RemoteRun,
    owner_token,
    remote_path,
    run_paths,
    session_name,
)

SERVER_KILL = "kill-" + "server"
STAGING = RemoteHost("staging-1", "staging", True)
PROD = RemoteHost("prod-1", "production", True)
READONLY = RemoteHost("ro-1", "staging", False)
HOSTS = (STAGING, PROD, READONLY)
ARGV = ("pytest", "-q")
BAD_ALIASES = (
    "-oProxyCommand=touch pwned",
    "-F/tmp/evil",
    "root@staging-1",
    "staging-1:22",
    "staging-1 -A",
    "staging-1;id",
    "$(id)",
    "`id`",
    "../staging-1",
    "staging-1\nprod-1",
    "",
)


def snapshot(host: FakeRemoteHost) -> tuple[object, object]:
    return copy.deepcopy(host.sessions), copy.deepcopy(host.files)


class RemoteSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = FakeRemoteHost()
        self.gate = FakeGate()
        self.ctl = make_controller(self.host, HOSTS, self.gate)

    def start(
        self, alias: str = "staging-1", mode: Mode = Mode.EXECUTE, argv: tuple[str, ...] = ARGV
    ) -> RemoteRun:
        return self.ctl.start(alias, "T-1", argv, mode, RiskLevel.LOW)

    def every_operation(self, alias: str) -> list[BaseException]:
        calls = (
            lambda: self.ctl.preflight(alias),
            lambda: self.start(alias),
            lambda: self.ctl.status(alias, "T-1"),
            lambda: self.ctl.capture(alias, "T-1"),
            lambda: self.ctl.stop(alias, "T-1"),
            lambda: self.ctl.list_owned(alias),
        )
        errors: list[BaseException] = []
        for call in calls:
            with self.assertRaises(WevError) as ctx:
                call()
            errors.append(ctx.exception)
        return errors

    # -- hosts ----------------------------------------------------------------

    def test_unlisted_alias_is_refused_by_every_operation(self) -> None:
        for error in self.every_operation("staging-2"):
            self.assertIsInstance(error, PermissionDenied)
        self.assertEqual(self.host.local_argvs, [])

    def test_hyphen_or_odd_aliases_are_refused_and_never_reach_ssh(self) -> None:
        for alias in BAD_ALIASES:
            with self.subTest(alias=alias):
                for error in self.every_operation(alias):
                    self.assertIsInstance(error, (PermissionDenied, ValidationError))
                with self.assertRaises(ValidationError):
                    Inventory((RemoteHost(alias),))
        self.assertEqual(self.host.local_argvs, [])

    def test_only_inventory_aliases_ever_reach_ssh(self) -> None:
        self.start()
        self.ctl.status("staging-1", "T-1")
        self.ctl.list_owned("staging-1")
        self.assertEqual(set(self.host.aliases), {"staging-1"})
        for argv in self.host.local_argvs:
            self.assertEqual(argv[7:9], ("--", "staging-1"))

    # -- authorization --------------------------------------------------------

    def test_plan_mode_is_refused_before_the_gate_and_the_host(self) -> None:
        with self.assertRaises(PermissionDenied) as ctx:
            self.start(mode=Mode.PLAN)
        self.assertEqual(ctx.exception.code, "remote_plan_mode")
        self.assertEqual((self.gate.calls, self.host.commands), ([], []))

    def test_check_order_alias_then_plan_then_gate(self) -> None:
        self.gate.outcome = PermissionOutcome.DENY
        with self.assertRaises(PermissionDenied) as ctx:
            self.start("nope", mode=Mode.PLAN)
        self.assertEqual(ctx.exception.code, "remote_host_not_listed")
        with self.assertRaises(PermissionDenied) as ctx:
            self.start("prod-1", mode=Mode.PLAN)
        self.assertEqual(ctx.exception.code, "remote_plan_mode")
        with self.assertRaises(PermissionDenied) as ctx:
            self.start("prod-1")
        self.assertEqual(ctx.exception.code, "remote_command_denied")

    def test_production_without_approval_is_refused_even_when_the_gate_allows(self) -> None:
        with self.assertRaises(ApprovalRequired) as ctx:
            self.start("prod-1")
        self.assertEqual(ctx.exception.details["action"], "prod-1 pytest -q")
        self.assertEqual(self.host.commands, [])

    def test_production_with_approval_for_the_exact_action_is_allowed(self) -> None:
        near_misses = {"prod-1 pytest", "staging-1 pytest -q", "prod-1 pytest -q -x", "pytest -q"}
        refused = make_controller(self.host, HOSTS, self.gate, approved=near_misses)
        with self.assertRaises(ApprovalRequired):
            refused.start("prod-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        self.assertEqual(self.host.commands, [])
        allowed = make_controller(self.host, HOSTS, self.gate, approved={"prod-1 pytest -q"})
        run = allowed.start("prod-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        self.assertIn(run.session, self.host.sessions)

    def test_approval_never_overrides_a_gate_denial(self) -> None:
        gate = FakeGate(PermissionOutcome.DENY)
        ctl = make_controller(self.host, HOSTS, gate, approved={"prod-1 pytest -q"})
        with self.assertRaises(PermissionDenied):
            ctl.start("prod-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        self.assertEqual(self.host.commands, [])

    def test_read_only_host_refuses_a_mutating_command(self) -> None:
        self.gate.plan_outcome = PermissionOutcome.DENY
        with self.assertRaises(PermissionDenied) as ctx:
            self.start("ro-1", argv=("rm", "-rf", "build"))
        self.assertEqual(ctx.exception.code, "remote_read_only_host")
        self.assertEqual(self.host.commands, [])
        self.assertEqual([call[1] for call in self.gate.calls], [Mode.EXECUTE, Mode.PLAN])
        self.gate.plan_outcome = PermissionOutcome.NEEDS_APPROVAL
        with self.assertRaises(PermissionDenied):
            self.start("ro-1", argv=("rm", "-rf", "build"))

    def test_read_only_host_accepts_a_read_only_command(self) -> None:
        self.assertIn(self.start("ro-1").session, self.host.sessions)

    def test_mutating_host_skips_the_read_only_test(self) -> None:
        self.gate.plan_outcome = PermissionOutcome.DENY
        self.start("staging-1")
        self.assertEqual([call[1] for call in self.gate.calls], [Mode.EXECUTE])

    # -- ownership ------------------------------------------------------------

    def test_foreign_session_is_never_modified_or_killed(self) -> None:
        name = session_name("T-1", "staging-1")
        markers = (None, "", "someone-else", owner_token("T-2", "staging-1"))
        for marker in markers:
            with self.subTest(marker=marker):
                host = FakeRemoteHost()
                host.add_foreign_session(name, {} if marker is None else {"@wev_owner": marker})
                ctl = make_controller(host, HOSTS)
                before = snapshot(host)
                with self.assertRaises(RemoteError) as started:
                    ctl.start("staging-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW)
                self.assertEqual(started.exception.code, "remote_session_not_owned")
                with self.assertRaises(RemoteError) as stopped:
                    ctl.stop("staging-1", "T-1")
                self.assertEqual(stopped.exception.code, "remote_session_not_owned")
                self.assertEqual(ctl.status("staging-1", "T-1").status, RunStatus.UNKNOWN)
                self.assertEqual(snapshot(host), before)
                verbs = {command[1] for command in host.commands if command[0] == "tmux"}
                self.assertEqual(verbs, {"has-session", "show-options"})

    def test_stop_on_an_unowned_session_is_refused(self) -> None:
        name = session_name("T-1", "staging-1")
        self.host.add_foreign_session(name)
        with self.assertRaises(RemoteError):
            self.ctl.stop("staging-1", "T-1")
        self.assertIn(name, self.host.sessions)
        self.assertFalse(any("kill-session" in text for text in self.host.remote_strings))

    def test_stop_never_touches_a_prefix_named_neighbour(self) -> None:
        run = self.start()
        self.host.add_foreign_session(run.session + "0")
        self.host.add_foreign_session(run.session[:-1])
        self.ctl.stop("staging-1", "T-1")
        self.assertEqual(sorted(self.host.sessions), sorted([run.session + "0", run.session[:-1]]))

    def test_every_tmux_target_uses_the_exact_match_prefix(self) -> None:
        self.start()
        self.ctl.status("staging-1", "T-1")
        self.ctl.stop("staging-1", "T-1")
        for command in self.host.commands:
            if command[0] == "tmux" and "-t" in command:
                self.assertTrue(command[command.index("-t") + 1].startswith("="), command)

    def test_duplicate_start_returns_the_existing_run(self) -> None:
        first = self.start()
        second = self.start()
        self.assertEqual(second, first)
        self.assertEqual(len(self.host.sessions), 1)
        self.assertEqual(len(self.host.sessions[first.session].keys), 1)
        news = [c for c in self.host.commands if c[:2] == ("tmux", "new-session")]
        self.assertEqual(len(news), 1)

    def test_list_owned_hides_sessions_without_the_marker(self) -> None:
        self.host.add_foreign_session("operator-shell")
        run = self.start()
        self.assertEqual(self.ctl.list_owned("staging-1"), (run.session,))

    # -- injection ------------------------------------------------------------

    def test_argument_injection_attempts_stay_single_arguments(self) -> None:
        nasty = ("pytest", "a b", "; rm -rf /", "$(reboot)", "`id`", "x' ; id '", "l1\nl2", "&& id")
        run = self.start(argv=nasty)
        self.assertEqual(run.argv, nasty)
        for command in self.host.commands:  # each local ssh argv carried one command string
            self.assertNotIn(command[0], ("rm", "reboot", "id"))
        script = self.host.files[self.host.sessions[run.session].launched_script or ""]
        self.assertEqual(tuple(shlex.split(script)[: len(nasty)]), nasty)
        typed = self.host.sessions[run.session].keys[0][0]
        self.assertRegex(typed, r"^cd && sh [A-Za-z0-9._/-]+$")

    def test_hostile_task_id_cannot_shape_session_or_paths(self) -> None:
        task = "x; tmux kill-session -t main $(id)/../.."
        run = self.ctl.start("staging-1", task, ARGV, Mode.EXECUTE, RiskLevel.LOW)
        self.assertRegex(run.session, r"^wev-[a-z0-9-]+-[0-9a-f]{8}$")
        self.assertRegex(run.log_path, r"^~/\.wev/remote/[a-z0-9.-]+\.log$")
        self.assertRegex(run.exit_path, r"^~/\.wev/remote/[a-z0-9.-]+\.exit$")

    # -- forbidden commands ---------------------------------------------------

    def run_all_scenarios(self) -> None:
        self.ctl.preflight("staging-1")
        run = self.start()
        self.start()
        self.ctl.status("staging-1", "T-1")
        self.host.finish_run(run.session, 1, "log\n")
        self.ctl.capture("staging-1", "T-1")
        self.ctl.list_owned("staging-1")
        self.ctl.stop("staging-1", "T-1")
        self.ctl.stop("staging-1", "T-1")
        self.host.reboot()
        self.ctl.status("staging-1", "T-1")
        self.host.fail("tmux send-keys")
        with self.assertRaises(RemoteError):
            self.ctl.start("staging-1", "T-2", ARGV, Mode.EXECUTE, RiskLevel.LOW, 5)
        self.host.add_foreign_session(session_name("T-3", "staging-1"))
        with self.assertRaises(RemoteError):
            self.ctl.start("staging-1", "T-3", ARGV, Mode.EXECUTE, RiskLevel.LOW)
        with self.assertRaises(RemoteError):
            self.ctl.stop("staging-1", "T-3")

    def test_no_command_ever_contains_the_server_kill_subcommand(self) -> None:
        self.run_all_scenarios()
        self.assertGreater(len(self.host.remote_strings), 25)
        for argv in self.host.local_argvs:
            self.assertNotIn(SERVER_KILL, " ".join(argv))

    def test_module_source_never_mentions_the_server_kill_subcommand(self) -> None:
        package = Path(wev_skills.remote.__file__).parent
        sources = sorted(package.glob("*.py")) + [package.parent / "commands" / "remote.py"]
        self.assertGreaterEqual(len(sources), 6)
        for path in sources:
            self.assertNotIn(SERVER_KILL, path.read_text(encoding="utf-8"), path.name)

    def test_environment_is_never_dumped_and_nothing_unexpected_is_sent(self) -> None:
        self.run_all_scenarios()
        allowed = {"tmux", "hostname", "id", "timeout", "test", "cat", "tail", "sh"}
        tmux_verbs = {"-V", "has-session", "new-session", "set-option", "show-options"}
        tmux_verbs |= {"send-keys", "list-sessions", "kill-session"}
        for command in self.host.commands:
            self.assertIn(command[0], allowed, command)
            self.assertNotIn(command[0], ("env", "printenv", "set", "export"))
            if command[0] == "tmux":
                self.assertIn(command[1], tmux_verbs, command)
        self.assertEqual(self.host.unknown, [])

    def test_ssh_options_are_always_strict_and_non_interactive(self) -> None:
        self.run_all_scenarios()
        for argv in self.host.local_argvs:
            self.assertEqual(argv[1:5], ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"))
            options = " ".join(argv[: argv.index("--")])
            for text in ("=no", "accept-new", "UserKnownHostsFile", "-i ", "-A", "Forward"):
                self.assertNotIn(text, options)

    # -- evidence -------------------------------------------------------------

    def test_status_after_a_reboot_is_unknown(self) -> None:
        self.start()
        self.host.reboot(keep_files=False)
        got = self.ctl.status("staging-1", "T-1")
        self.assertEqual(
            (got.status, got.exit_code, got.session_exists), (RunStatus.UNKNOWN, None, False)
        )
        self.assertIn("reboot", got.reason)

    def test_an_exit_file_alone_never_proves_a_result(self) -> None:
        paths = run_paths("~/.wev/remote", "T-1", "staging-1")
        for content in ("0\n", "1\n"):
            self.host.files[remote_path(paths.exit_path)] = content
            got = self.ctl.status("staging-1", "T-1")
            self.assertEqual((got.status, got.exit_code), (RunStatus.UNKNOWN, None))
        self.host.add_foreign_session(session_name("T-1", "staging-1"), {"@wev_owner": "x"})
        got = self.ctl.status("staging-1", "T-1")
        self.assertEqual((got.status, got.exit_code, got.owned), (RunStatus.UNKNOWN, None, False))

    def test_session_without_exit_file_is_running_never_passed(self) -> None:
        run = self.start()
        for _ in range(3):
            got = self.ctl.status("staging-1", "T-1")
            self.assertEqual((got.status, got.exit_code), (RunStatus.RUNNING, None))
        self.host.files[run.log_path[2:]] = "5 passed in 0.1s\nOK\nexit 0\n"
        self.assertEqual(self.ctl.status("staging-1", "T-1").status, RunStatus.RUNNING)

    def test_dropped_connection_is_unknown_never_failed_or_passed(self) -> None:
        run = self.start()
        self.host.finish_run(run.session, 0)
        self.host.drop_connection("Connection timed out")
        got = self.ctl.status("staging-1", "T-1")
        self.assertEqual((got.status, got.exit_code), (RunStatus.UNKNOWN, None))
        self.host.restore_connection()
        self.assertEqual(self.ctl.status("staging-1", "T-1").status, RunStatus.PASSED)


if __name__ == "__main__":
    unittest.main()
