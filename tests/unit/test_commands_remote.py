"""``wev remote`` without an active run: ``--config`` names the inventory, ``--mode`` is asked."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from tests.unit._remote_tmux_helpers import HOSTS, NAME, STEM, CliBase
from wev_skills import cli
from wev_skills.commands import remote as remote_cmd

START = ("start", "--host", "staging-1", "--task", "T-1", "--mode", "execute")
WIDENING_WORDS = ("prevents", "guarantees", "ensures", "impede", "garante", "assegura")


class RemoteCliTests(CliBase):
    def test_hosts_lists_the_inventory_without_contacting_anything(self) -> None:
        code, out, _ = self.run_cli("hosts")
        self.assertEqual((code, out), (0, {"hosts": HOSTS, "config_source": self.config}))
        self.assertEqual(self.host.local_argvs, [])

    def test_preflight(self) -> None:
        code, out, _ = self.run_cli("preflight", "--host", "staging-1")
        self.assertEqual(code, 0)
        self.assertEqual((out["hostname"], out["tmux_available"]), ("fake-host", True))

    def test_unlisted_host_exits_3(self) -> None:
        for argv in (
            ("preflight", "--host", "elsewhere"),
            ("status", "--host", "elsewhere", "--task", "T-1"),
            ("start", "--host", "elsewhere", "--task", "T-1", "--mode", "execute", "--", "true"),
        ):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual((code, out), (3, {}))
                self.assertEqual(err["error"]["code"], "remote_host_not_listed")
        self.assertEqual(self.host.local_argvs, [])

    def test_read_only_command_starts_without_approval_under_the_real_policy(self) -> None:
        code, run, _ = self.run_cli(*START, "--", "ls")
        self.assertEqual((code, run["argv"]), (0, ["ls"]))
        self.assertTrue(all(argv[0] == "ssh" for argv in self.host.local_argvs))

    def test_local_ssh_needs_approval_while_the_remote_transport_does_not(self) -> None:
        code, out, _ = self.main("check-command", "--", "ssh", "staging-1", "ls")
        self.assertEqual((code, out["decision"]["outcome"]), (4, "needs_approval"))
        self.assertTrue(out["classification"]["external_effect"])
        code, _, _ = self.run_cli(*START, "--", "ls")
        self.assertEqual(code, 0)

    def test_risky_remote_command_needs_a_grant_for_the_host_qualified_action(self) -> None:
        argv = (*START, "--", "rm", "-rf", "build")
        code, _, err = self.run_cli(*argv)
        self.assertEqual((code, err["error"]["code"]), (4, "remote_approval_required"))
        self.assertEqual(err["error"]["details"]["action"], "staging-1 rm -rf build")
        self.grant("rm", "-rf", "build")  # a grant for the local command is not enough
        code, _, again = self.run_cli(*argv)
        self.assertEqual(code, 4)
        self.assertEqual(self.host.commands, [])
        self.assertEqual(
            again["error"]["details"]["approval_id"], err["error"]["details"]["approval_id"]
        )
        self.grant_id(err["error"]["details"]["approval_id"])
        code, run, _ = self.run_cli(*argv)
        self.assertEqual((code, run["argv"]), (0, ["rm", "-rf", "build"]))
        self.host.reboot()
        self.assertEqual(self.run_cli(*argv)[0], 4)  # the grant was for one start only

    def test_denied_and_state_directory_commands_never_reach_the_host(self) -> None:
        state_file = str(self.state_dir / "approvals.json")
        code, _, err = self.run_cli(*START, "--", "cat", state_file)
        self.assertEqual((code, err["error"]["code"]), (3, "remote_command_denied"))
        self.assertEqual(self.host.commands, [])

    def test_plan_mode_exits_3(self) -> None:
        code, _, err = self.run_cli(
            "start", "--host", "staging-1", "--task", "T-1", "--mode", "plan", "--", "ls"
        )
        self.assertEqual((code, err["error"]["code"]), (3, "remote_plan_mode"))

    def test_start_status_capture_stop_flow(self) -> None:
        code, run, _ = self.run_cli(
            *START,
            "--risk",
            "medium",
            "--timeout",
            "60",
            "--",
            "pytest",
            "-q",
            "--maxfail=1",
            "a b",
        )
        self.assertEqual(code, 0)
        self.assertEqual(run["argv"], ["pytest", "-q", "--maxfail=1", "a b"])
        self.assertEqual(run["session"], NAME)
        self.assertTrue(self.host.files[run["log_path"][2:-4] + ".sh"].startswith("timeout 60 "))

        code, status, _ = self.run_cli("status", "--host", "staging-1", "--task", "T-1")
        self.assertEqual((code, status["status"], status["exit_code"]), (0, "running", None))

        self.host.finish_run(NAME, 1, "bo\x1b[2Jom\x07\napi_key=abc123\n")
        code, status, _ = self.run_cli("status", "--host", "staging-1", "--task", "T-1")
        self.assertEqual((status["status"], status["exit_code"]), ("failed", 1))

        code, captured, _ = self.run_cli(
            "capture", "--host", "staging-1", "--task", "T-1", "--lines", "5"
        )
        self.assertEqual(code, 0)
        self.assertIs(captured["untrusted"], True)
        self.assertEqual(captured["source"], "remote:staging-1")
        self.assertRegex(
            captured["text"], r'^<<<WEV_UNTRUSTED_DATA id=\w+ source="remote:staging-1">>>'
        )
        self.assertIn("boom\napi_key=[REDACTED]\n", captured["text"])
        self.assertRegex(captured["text"], r"<<<END_WEV_UNTRUSTED_DATA id=\w+>>>$")
        self.assertNotIn("abc123", json.dumps(captured))
        self.assertNotIn("\\u001b", json.dumps(captured))

        code, stopped, _ = self.run_cli("stop", "--host", "staging-1", "--task", "T-1")
        self.assertEqual((code, stopped["status"], stopped["session_exists"]), (0, "failed", False))

    def test_production_needs_approval_even_for_an_allowed_command(self) -> None:
        argv = ("start", "--host", "prod-1", "--task", "T-1", "--mode", "execute", "--", "ls")
        code, _, err = self.run_cli(*argv)
        self.assertEqual((code, err["error"]["code"]), (4, "remote_approval_required"))
        self.assertEqual(self.host.commands, [])
        self.grant_id(err["error"]["details"]["approval_id"])
        self.assertEqual(self.run_cli(*argv)[0], 0)

    def test_read_only_host_refuses_a_mutating_command_even_when_approved(self) -> None:
        self.grant_remote("prod-1", "touch", "x")
        code, _, err = self.run_cli(
            "start", "--host", "prod-1", "--task", "T-1", "--mode", "execute", "--", "touch", "x"
        )
        self.assertEqual((code, err["error"]["code"]), (3, "remote_read_only_host"))

    def test_stop_refuses_a_foreign_session_with_exit_8(self) -> None:
        self.host.add_foreign_session(NAME)
        code, _, err = self.run_cli("stop", "--host", "staging-1", "--task", "T-1")
        self.assertEqual((code, err["error"]["code"]), (8, "remote_session_not_owned"))
        self.assertIn(NAME, self.host.sessions)

    def test_dropped_connection_exits_8_with_redacted_stderr(self) -> None:
        self.host.drop_connection("Permission denied (publickey). password=hunter2")
        code, _, err = self.run_cli("preflight", "--host", "staging-1")
        self.assertEqual((code, err["error"]["code"]), (8, "remote_authentication_failed"))
        self.assertNotIn("hunter2", json.dumps(err))

    def test_start_without_a_command_is_a_validation_error(self) -> None:
        code, _, err = self.run_cli(*START)
        self.assertEqual((code, err["error"]["code"]), (2, "remote_invalid_command"))

    def test_missing_required_arguments_are_usage_errors(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["remote", "status", "--host", "staging-1"]), 2)
            self.assertEqual(cli.main(["remote"]), 2)

    def test_start_without_a_mode_is_refused_when_no_run_is_active(self) -> None:
        code, _, err = self.run_cli("start", "--host", "staging-1", "--task", "T-1", "--", "ls")
        self.assertEqual((code, err["error"]["code"]), (2, "remote_mode_required"))
        self.assertEqual(self.host.local_argvs, [])

    def test_stop_in_plan_mode_is_refused_and_the_session_stays(self) -> None:
        self.assertEqual(self.run_cli(*START, "--", "ls")[0], 0)
        before = len(self.host.commands)
        code, _, err = self.run_cli(
            "stop", "--host", "staging-1", "--task", "T-1", "--mode", "plan"
        )
        self.assertEqual((code, err["error"]["code"]), (3, "remote_stop_plan_mode"))
        self.assertIn(NAME, self.host.sessions)
        self.assertEqual(len(self.host.commands), before)

    def test_every_subcommand_names_the_configuration_it_used(self) -> None:
        self.assertEqual(self.run_cli(*START, "--", "ls")[1]["config_source"], self.config)
        for argv in (
            ("hosts",),
            ("preflight", "--host", "staging-1"),
            ("status", "--host", "staging-1", "--task", "T-1"),
            ("capture", "--host", "staging-1", "--task", "T-1"),
            ("stop", "--host", "staging-1", "--task", "T-1"),
        ):
            with self.subTest(argv=argv):
                code, out, _ = self.run_cli(*argv)
                self.assertEqual((code, out["config_source"]), (0, self.config))

    def test_without_a_run_nothing_is_recorded_so_a_finished_session_is_unknown(self) -> None:
        self.assertEqual(self.run_cli(*START, "--", "ls")[0], 0)
        self.assertFalse((self.state_dir / "remote-runs.json").exists())
        self.host.finish_run(NAME, 0)
        self.host.reboot(keep_files=True)
        _, status, _ = self.run_cli("status", "--host", "staging-1", "--task", "T-1")
        self.assertEqual((status["status"], status["session_exists"]), ("unknown", False))

    def test_an_exit_file_nobody_started_is_unknown(self) -> None:
        self.host.files[f"{STEM}.exit"] = "0\n"
        code, status, _ = self.run_cli("status", "--host", "staging-1", "--task", "T-1")
        self.assertEqual((code, status["status"], status["exit_code"]), (0, "unknown", None))
        self.assertIn("recorded", status["reason"])

    def test_host_text_is_printed_without_control_characters(self) -> None:
        self.host.hostname, self.host.user = "box\x1b[2J\x07-1", "dep\x1b]0;x\x07loy\x00"
        code, out, _ = self.run_cli("preflight", "--host", "staging-1")
        self.assertEqual((code, out["hostname"], out["user"]), (0, "box-1", "deploy"))
        self.host.drop_connection("Connection\x1b[2J refused\x07")
        code, _, err = self.run_cli("preflight", "--host", "staging-1")
        self.assertEqual((code, err["error"]["details"]["stderr"]), (8, "Connection refused"))

    def help_text(self, lang: str, *argv: str) -> str:
        out = io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            self.assertRaises(SystemExit),
            remote_cmd.i18n.use_language(lang),
        ):
            cli.build_parser().parse_args(["remote", *argv, "--help"])
        return " ".join(out.getvalue().split())

    def test_help_is_available_in_both_languages(self) -> None:
        for lang, word in (("en", "approval"), ("pt-BR", "aprovação")):
            self.assertIn(word, self.help_text(lang, "start"))

    def test_help_says_where_mode_risk_and_inventory_come_from(self) -> None:
        for lang, phrase in (("en", "cannot be widened"), ("pt-BR", "não podem ser ampliados")):
            for argv in ((), ("start",), ("stop",)):
                with self.subTest(lang=lang, argv=argv):
                    self.assertIn(phrase, self.help_text(lang, *argv))

    def test_no_message_promises_more_than_the_code_does(self) -> None:
        locales = remote_cmd.i18n.LOCALES_DIR
        for name in ("remote.en.json", "remote.pt-BR.json"):
            text = (locales / name).read_text(encoding="utf-8").lower()
            for word in WIDENING_WORDS:
                with self.subTest(name=name, word=word):
                    self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
