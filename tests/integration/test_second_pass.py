"""The reproductions of the second independent pass, through the real CLI and a real git
repository. Where a test follows ``next_step`` it runs the printed step as printed; a step
that is an instruction for a person is checked for what it says and is never run."""

from __future__ import annotations

import json
from typing import Any

from tests.integration.test_cli_flow import GREETING_MAKEFILE, CliFlowCase

RM_BUILD = ("rm", "-rf", "build")
NOTES = {
    "id": "notes",
    "files": ["NOTES.md"],
    "acceptance_criteria": ["NOTES.md exists", "NOTES.md mentions sub"],
    "checks": [
        {"command": "test -f NOTES.md", "criteria": [0]},
        {"command": "grep -q sub NOTES.md", "criteria": [1]},
    ],
}
EASY = {**NOTES, "acceptance_criteria": ["work is done"], "checks": ["make test"]}


class DenialTests(CliFlowCase):
    def statuses(self) -> list[tuple[str, int]]:
        listed = self.ok("approval", "list")["approvals"]
        return [(item["status"], item["generation"]) for item in listed]

    def test_a_denied_command_stays_denied_whatever_is_asked_again(self) -> None:
        (self.work / "build").mkdir()
        self.begin()
        code, _, err = self.wev("exec", "--", *RM_BUILD)
        self.assertEqual(code, 4)
        approval = err["details"]["approval_id"]
        code, out, err = self.as_operator("approval", "deny", approval)
        self.assertEqual((code, out["status"]), (0, "denied"), err)
        request = ("approval", "request", "--risk", "low", "--reason", "x")
        for extra in ((), ("--cwd", "/tmp"), ("--cwd", str(self.work / "build"))):
            with self.subTest(extra=extra):
                again = self.ok(*request, *extra, "--", *RM_BUILD)
                self.assertEqual((again["status"], again["generation"]), ("denied", 1))
        self.assertEqual(
            self.ok(*request, "--cwd", "/tmp", "--", "rm -rf build")["status"], "denied"
        )
        code, _, err = self.wev("exec", "--", *RM_BUILD)
        self.assertEqual((code, err["code"]), (3, "permission_denied"))
        self.assertIn("denied this exact action", err["message"])
        self.assertEqual(self.statuses(), [("denied", 1)])
        self.assertTrue((self.work / "build").is_dir())
        verify = self.ok("approval", "verify")
        self.assertEqual((verify["ok"], verify["mismatches"]), (True, []))


class PlanRewriteTests(CliFlowCase):
    def test_a_started_tasks_criteria_cannot_be_swapped_for_trivial_ones(self) -> None:
        self.ok("run", "start", "--objective", "Add notes", "--files", "6", "--subtasks", "2")
        self.plan(NOTES)
        self.ok("task", "next")
        self.ok("task", "start", "notes")
        self.assertFalse(self.ok("task", "check", "notes")["all_met"])
        self.write("plan.json", json.dumps({"objective": "notes", "tasks": [self.filled(EASY)]}))
        code, _, err = self.wev("plan", "set", "--file", "plan.json")
        self.assertEqual((code, err["code"]), (2, "plan_amendment_required"))
        self.assertIn("--amend --reason", err["details"]["next_step"])
        self.write("scratch.txt", "scratch\n")
        code, _, err = self.wev(
            "task", "record", "notes", "--status", "verified", "--summary", "done"
        )
        self.assertEqual((code, err["code"]), (2, "verification_required"))
        self.assertNotEqual(self.ok("run", "report")["status"], "complete")
        code, _, err = self.wev("plan", "set", "--file", "plan.json", "--amend")
        self.assertEqual((code, err["code"]), (2, "amend_reason_required"))
        amend = ("plan", "set", "--file", "plan.json", "--amend", "--reason", "criteria were wrong")
        self.ok(*amend)
        report = self.ok("run", "report")
        (row,) = report["plan_amendments"]
        self.assertEqual((row["task_id"], row["reason"]), ("notes", "criteria were wrong"))
        before = {change["field"]: change["before"] for change in row["changes"]}
        self.assertEqual(before["acceptance_criteria"], NOTES["acceptance_criteria"])
        code, text, _ = self.raw("run", "report", "--format", "md")
        self.assertIn("## Plan amendments", text)
        self.assertIn("NOTES.md mentions sub", text)
        self.assertIn("plan.amended", self.state_text())

    def filled(self, task: dict[str, Any]) -> dict[str, Any]:
        return {"title": task["id"], "objective": f"do {task['id']}", **task}

    def raw(self, *args: str) -> tuple[int, str, str]:
        import subprocess

        proc = subprocess.run(
            self.command(*args), cwd=self.work, capture_output=True, text=True, check=False
        )
        return proc.returncode, proc.stdout, proc.stderr


class ExecBindingTests(CliFlowCase):
    def test_exec_acts_for_a_running_task_only(self) -> None:
        self.ok("run", "start", "--objective", "Add sub and review it", "--files", "6")
        self.plan(
            {"id": "impl", "files": ["calc.py"], "agent_hint": "senior-engineer"},
            {
                "id": "audit",
                "files": ["notes.md"],
                "agent_hint": "code-reviewer",
                "read_only": True,
            },
        )
        code, _, err = self.wev("exec", "--", "touch", "before.txt")
        self.assertEqual((code, err["code"]), (3, "exec_no_running_task"))
        self.assertEqual(self.wev("exec", "--", "ls")[0], 0)
        self.ok("task", "next")
        self.ok("task", "start", "audit")
        for args in (("--task", "audit"), ()):
            code, _, err = self.wev("exec", *args, "--", "touch", "x.txt")
            self.assertEqual((code, err["code"]), (3, "agent_read_only"), args)
        code, _, err = self.wev("exec", "--task", "impl", "--", "touch", "x.txt")
        self.assertEqual((code, err["code"]), (3, "exec_task_not_running"))
        self.assertIn("audit", err["message"])
        code, _, err = self.wev("exec", "--task", "ghost", "--", "ls")
        self.assertEqual((code, err["code"]), (3, "exec_task_not_running"))
        self.assertFalse((self.work / "x.txt").exists())
        code, out, _ = self.wev("exec", "--", "make", "test")
        self.assertEqual((code, out["task_id"], out["task_implied"]), (0, "audit", True))
        self.assertIn("only running task", out["task_note"])
        code, _, err = self.wev("exec", "--task", "audit", "--", "make", "deploy")
        self.assertEqual((code, err["code"]), (3, "agent_read_only"))


class HonestDirectPathTests(CliFlowCase):
    makefile = GREETING_MAKEFILE

    def test_a_direct_run_never_loops_on_its_printed_step(self) -> None:
        started = self.ok("run", "start", "--objective", "Add a greeting", "--files", "1")
        offered = self.ok(*self.follow(started["next_step"]))
        begun = self.ok(*self.follow(offered["next_step"]))
        self.assertEqual(self.follow(begun["next_step"])[:2], ["task", "check"])
        early = self.ok(*self.follow(begun["next_step"]))
        self.assertFalse(early["all_met"])
        instruction = early["next_step"]
        self.assertFalse(instruction.startswith("wev "), instruction)
        self.assertIn("Do the work", instruction)
        again = "wev task check task-1 --run " + started["run_id"]
        self.assertIn(f"'{again}'", instruction)
        self.work_on()
        checked = self.ok(*self.follow(again))
        self.assertTrue(checked["all_met"])
        record = [word.replace("<text>", "added") for word in self.follow(checked["next_step"])]
        recorded = self.ok(*record)
        finished = self.ok(*self.follow(recorded["next_step"]))
        self.assertTrue(finished["complete"])
        self.assertEqual(self.ok(*self.follow(finished["next_step"]))["status"], "complete")

    def test_checks_that_already_pass_point_to_the_work_not_to_another_check(self) -> None:
        self.write("greeting.txt", "hello\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "greeting exists")
        self.begin()
        checked = self.ok("task", "check", "task-1")
        self.assertFalse(checked["all_met"])
        step = checked["next_step"]
        self.assertFalse(step.startswith("wev "), step)
        self.assertIn("No file changed", step)
        self.assertIn("read_only", step)
        self.assertEqual(self.ok("run", "status")["next_step"], step)

    def test_plan_mode_ends_at_a_review_instruction(self) -> None:
        started = self.ok("run", "start", "--mode", "plan", "--objective", "Investigate")
        task = {"id": "a", "title": "profile", "objective": "a", "checks": ["make test"]}
        self.write("plan.json", json.dumps({"objective": "x", "tasks": [task]}))
        planned = self.ok(*self.follow(started["next_step"]))
        step = planned["next_step"]
        self.assertFalse(step.startswith("wev "), step)
        self.assertIn("ready for human review", step)
        self.assertIn("wev run finish", step)
        self.assertIn("--mode execute", step)
        names = [f"f{index}.txt" for index in range(10)]
        for name in names:
            self.write(name, "text\n")
        reads = [("ls",), ("git", "status"), ("git", "log", "--oneline"), ("git", "diff")]
        for argv in (*reads, *(("cat", name) for name in names)):
            code, out, _ = self.wev("exec", "--", *argv)
            self.assertEqual((code, out["guard"]["action"]), (0, "continue"), argv)
        self.assertEqual(self.ok("run", "status")["guard"]["action"], "continue")


class VerifiedThenChangedTests(CliFlowCase):
    makefile = GREETING_MAKEFILE

    def test_a_change_after_verified_is_reported_until_checked_again(self) -> None:
        self.begin()
        self.work_on()
        self.ok("task", "check", "task-1")
        self.assertEqual(self.verified()[0], 0)
        self.assertEqual(self.ok("run", "report")["status"], "complete")
        self.write("Makefile", GREETING_MAKEFILE + "# changed after verification\n")
        report = self.ok("run", "report")
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["tasks"][0]["verified_then_changed"])
        self.assertTrue(any("verified, then changed" in reason for reason in report["reasons"]))
        self.ok(*self.follow(report["next_step"]))
        self.assertEqual(self.ok("run", "report")["status"], "complete")
        self.work_on("greeting.txt", "changed again\n")
        finished = self.ok("run", "finish")
        self.assertEqual(
            (finished["complete"], finished["changed_after_verification"]), (False, ["task-1"])
        )

    def test_an_ignored_file_is_outside_the_fingerprint_and_the_plan_says_so(self) -> None:
        self.write(".gitignore", "local_settings.py\n")
        self.write("local_settings.py", "K = 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "ignore local settings")
        self.ok("run", "start", "--objective", "Add a greeting", "--files", "6")
        planned = self.plan({"id": "a", "files": ["greeting.txt", "local_settings.py"]})
        self.assertEqual(len(planned["warnings"]), 1)
        self.assertIn("local_settings.py", planned["warnings"][0])
        self.ok("task", "next")
        self.ok("task", "start", "a")
        self.work_on()
        checked = self.ok("task", "check", "a")
        self.assertIn("ignores are outside", checked["fingerprint_notice"])
        self.assertEqual(self.verified("a")[0], 0)
        self.write("local_settings.py", "K = 5\n")
        report = self.ok("run", "report")
        self.assertFalse(report["tasks"][0]["verified_then_changed"])
        self.assertTrue(any("ignores are outside" in notice for notice in report["notices"]))


class ExhaustedTests(CliFlowCase):
    config = {"state_dir": ".wev", "limits": {"max_attempts": 1}}

    def test_an_exhausted_task_cannot_be_hidden_as_not_executed(self) -> None:
        self.begin()
        failed = self.ok("task", "record", "task-1", "--status", "failed", "--summary", "boom")
        self.assertTrue(failed["attempts_exhausted"])
        self.assertFalse(failed["next_step"].startswith("wev "), failed["next_step"])
        code, _, err = self.wev(
            "task", "record", "task-1", "--status", "not_executed", "--summary", "reset?"
        )
        self.assertEqual((code, err["code"]), (2, "attempts_exhausted"))
        report = self.ok("run", "report")
        self.assertEqual(report["status"], "blocked")
        self.assertIn("wev task reopen task-1", report["next_step"])
