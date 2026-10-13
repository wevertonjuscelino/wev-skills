"""``wev remote`` during an active run: mode, risk, inventory and task come from the run."""

from __future__ import annotations

import json
import unittest

from tests.unit._remote_tmux_helpers import HOSTS, LOCAL_AGENT, NAME, RUN_ID, CliBase
from wev_skills.core.contracts import Mode, RiskLevel
from wev_skills.state.store import STATE_FILE

START = ("start", "--host", "staging-1", "--task", "T-1")
TASK = ("--host", "staging-1", "--task", "T-1")
OTHER_INVENTORY = [{"alias": "db-primary", "environment": "live", "allow_mutating": True}]


class ModeAndRiskTests(CliBase):
    def test_execute_run_starts_without_a_mode_and_names_the_run_as_source(self) -> None:
        self.make_run()
        code, run, _ = self.run_cli(*START, "--", "ls")
        self.assertEqual((code, run["argv"], run["config_source"]), (0, ["ls"], f"run:{RUN_ID}"))
        self.assertFalse((self.repo / ".wev" / "remote-runs.json").exists())
        state = json.loads(
            (self.repo / ".wev" / "runs" / RUN_ID / STATE_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual([r["task_id"] for r in state["remote_runs"]], ["T-1"])

    def test_the_start_recorded_in_the_run_backs_the_status_after_the_session_ends(self) -> None:
        self.make_run()
        self.assertEqual(self.run_cli(*START, "--", "ls")[0], 0)
        self.host.finish_run(NAME, 0)
        self.host.reboot(keep_files=True)
        _, status, _ = self.run_cli("status", *TASK)
        self.assertEqual((status["status"], status["session_exists"]), ("passed", False))

    def test_plan_run_refuses_a_start_that_asks_for_execute(self) -> None:
        self.make_run(Mode.PLAN)
        for mode in ("execute", "auto", "resume"):
            with self.subTest(mode=mode):
                code, _, err = self.run_cli(*START, "--mode", mode, "--", "ls")
                self.assertEqual((code, err["error"]["code"]), (3, "remote_mode_widened"))
                self.assertIn(RUN_ID, err["error"]["message"])
        self.assertEqual(self.host.local_argvs, [])

    def test_plan_run_never_starts_or_stops(self) -> None:
        self.make_run(Mode.PLAN)
        self.host.add_foreign_session(NAME)
        code, _, err = self.run_cli(*START, "--", "ls")
        self.assertEqual((code, err["error"]["code"]), (3, "remote_plan_mode"))
        for extra in ((), ("--mode", "plan"), ("--mode", "execute")):
            with self.subTest(extra=extra):
                code, _, err = self.run_cli("stop", *TASK, *extra)
                self.assertEqual(code, 3)
                self.assertIn(
                    err["error"]["code"], ("remote_stop_plan_mode", "remote_mode_widened")
                )
        self.assertEqual(self.host.local_argvs, [])

    def test_execute_run_accepts_the_more_restrictive_plan_mode(self) -> None:
        self.make_run()
        code, _, err = self.run_cli(*START, "--mode", "plan", "--", "ls")
        self.assertEqual((code, err["error"]["code"]), (3, "remote_plan_mode"))
        self.assertEqual(self.run_cli(*START, "--mode", "execute", "--", "ls")[0], 0)

    def test_risk_below_the_run_is_refused_and_equal_or_higher_is_accepted(self) -> None:
        self.make_run(risk=RiskLevel.MEDIUM)
        code, _, err = self.run_cli(*START, "--risk", "low", "--", "ls")
        self.assertEqual((code, err["error"]["code"]), (3, "remote_risk_widened"))
        code, _, err = self.run_cli("stop", *TASK, "--risk", "low")
        self.assertEqual((code, err["error"]["code"]), (3, "remote_risk_widened"))
        self.assertEqual(self.host.local_argvs, [])
        for risk in ("medium", "high"):
            self.host.reboot()
            self.assertEqual(self.run_cli(*START, "--risk", risk, "--", "ls")[0], 0)

    def test_unreadable_run_state_refuses_start_and_stop_naming_the_problem(self) -> None:
        store = self.make_run()
        (store.run_dir / STATE_FILE).write_text("{ not json", encoding="utf-8")
        for argv in ((*START, "--mode", "execute", "--", "ls"), (*START, "--", "ls")):
            code, _, err = self.run_cli(*argv)
            self.assertEqual((code, err["error"]["code"]), (3, "remote_run_state_unreadable"))
            self.assertTrue(err["error"]["details"]["state_error"])
            self.assertIn(err["error"]["details"]["state_error"], err["error"]["message"])
        code, _, err = self.run_cli("stop", *TASK)
        self.assertEqual((code, err["error"]["code"]), (3, "remote_run_state_unreadable"))
        self.assertEqual(self.host.local_argvs, [])


class InventoryTests(CliBase):
    def other_config(self) -> str:
        path = self.tmp / "agent.json"
        path.write_text(json.dumps({"remote": {"hosts": OTHER_INVENTORY}}), encoding="utf-8")
        return str(path)

    def test_another_config_cannot_swap_the_inventory_during_a_run(self) -> None:
        self.make_run()
        self.config = self.other_config()
        for argv in (
            ("hosts",),
            ("preflight", "--host", "db-primary"),
            (
                "start",
                "--host",
                "db-primary",
                "--task",
                "T-1",
                "--risk",
                "low",
                "--",
                "mv",
                "a",
                "b",
            ),
            ("status", "--host", "db-primary", "--task", "T-1"),
            ("capture", "--host", "db-primary", "--task", "T-1"),
            ("stop", "--host", "db-primary", "--task", "T-1"),
        ):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual((code, out, err["error"]["code"]), (2, {}, "config_pinned"))
        self.assertEqual(self.host.local_argvs, [])

    def test_the_inventory_is_the_one_the_run_pinned(self) -> None:
        self.make_run()
        code, out, _ = self.run_cli("hosts")
        self.assertEqual((code, out), (0, {"hosts": HOSTS, "config_source": f"run:{RUN_ID}"}))
        code, _, err = self.run_cli("start", "--host", "db-primary", "--task", "T-1", "--", "ls")
        self.assertEqual((code, err["error"]["code"]), (3, "remote_host_not_listed"))
        self.assertEqual(self.host.local_argvs, [])

    def test_a_grant_through_the_cli_works_for_the_pinned_inventory(self) -> None:
        self.make_run()
        argv = (*START, "--", "rm", "-rf", "build")
        code, _, err = self.run_cli(*argv)
        self.assertEqual((code, err["error"]["code"]), (4, "remote_approval_required"))
        self.grant_id(err["error"]["details"]["approval_id"])
        self.assertEqual(self.run_cli(*argv)[0], 0)
        self.assertEqual(self.run_cli(*START, "--", "rm", "-rf", "dist")[0], 4)

    def test_a_denied_remote_action_is_not_asked_again(self) -> None:
        self.make_run()
        argv = (*START, "--", "rm", "-rf", "build")
        code, _, err = self.run_cli(*argv)
        self.assertEqual((code, err["error"]["code"]), (4, "remote_approval_required"))
        approval = err["error"]["details"]["approval_id"]
        code, _, err = self.main("approval", "deny", approval)
        self.assertEqual((code, err), (0, {}))
        code, _, err = self.run_cli(*argv)
        self.assertEqual((code, err["error"]["code"]), (3, "approval_denied"))
        self.assertIn("already denied", err["error"]["message"])
        self.assertNotIn("approval grant", json.dumps(err))
        code, out, _ = self.main("approval", "list")
        self.assertEqual([item["status"] for item in out["approvals"]], ["denied"])
        self.assertEqual(self.host.local_argvs, [])


class TaskGateTests(CliBase):
    def every_task_command(self, task: str) -> list[tuple[int, dict, dict]]:  # type: ignore[type-arg]
        target = ("--host", "staging-1", "--task", task)
        return [
            self.run_cli("start", *target, "--", "ls"),
            self.run_cli("status", *target),
            self.run_cli("capture", *target),
            self.run_cli("stop", *target),
        ]

    def test_a_task_outside_the_run_plan_is_refused(self) -> None:
        self.make_run()
        for code, out, err in self.every_task_command("T-9"):
            self.assertEqual((code, out, err["error"]["code"]), (3, {}, "remote_task_not_in_run"))
            self.assertIn("T-9", err["error"]["message"])
        self.assertEqual(self.host.local_argvs, [])

    def test_an_agent_without_remote_permission_is_refused_by_name(self) -> None:
        self.make_run(agent=LOCAL_AGENT)
        for code, out, err in self.every_task_command("T-1"):
            self.assertEqual((code, out), (3, {}))
            self.assertEqual(err["error"]["code"], "remote_agent_not_allowed")
            self.assertIn(LOCAL_AGENT, err["error"]["message"])
            self.assertIn("may_use_remote", err["error"]["message"])
            self.assertEqual(err["error"]["details"]["agent_id"], LOCAL_AGENT)
        self.assertEqual(self.host.local_argvs, [])

    def test_a_task_nobody_is_assigned_to_is_refused(self) -> None:
        self.make_run(agent="")
        for code, _, err in self.every_task_command("T-1"):
            self.assertEqual((code, err["error"]["code"]), (3, "remote_task_unassigned"))
        self.assertEqual(self.host.local_argvs, [])

    def test_an_unknown_agent_is_refused_with_the_reason(self) -> None:
        self.make_run(agent="nobody-here")
        code, _, err = self.run_cli(*START, "--", "ls")
        self.assertEqual((code, err["error"]["code"]), (3, "remote_task_not_in_run"))
        self.assertIn("nobody-here", json.dumps(err))
        self.assertEqual(self.host.local_argvs, [])

    def test_the_allowed_agent_runs_the_whole_flow(self) -> None:
        self.make_run()
        self.assertEqual(self.run_cli(*START, "--", "ls")[0], 0)
        self.host.finish_run(NAME, 0, "ok\n")
        for name, expected in (("status", "passed"), ("stop", "passed")):
            code, out, _ = self.run_cli(name, *TASK)
            self.assertEqual((code, out["status"]), (0, expected))
        code, out, _ = self.run_cli("capture", *TASK)
        self.assertEqual((code, out["config_source"]), (0, f"run:{RUN_ID}"))


if __name__ == "__main__":
    unittest.main()
