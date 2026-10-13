"""Smaller defects and ``next_step`` friction the second independent pass reported.

Each ``next_step`` test follows the printed step literally: when the step is a command it is
run as printed; when only a person may act, the step must be an instruction, not a command.
"""

from __future__ import annotations

from typing import Any

from tests.unit._orchestrator_helpers import RUN_ID, OrchestratorCase
from wev_skills.core.contracts import Mode, TaskStatus
from wev_skills.core.errors import (
    ApprovalRequired,
    GuardTripped,
    PermissionDenied,
    ValidationError,
)
from wev_skills.core.report_markdown import render_markdown

INLINE = "python3 -c 'import calc'"
MUL = {"id": "mul", "files": ["calc.py"], "acceptance_criteria": ["mul works"], "checks": ["unit"]}
FINAL = {"id": "final", "depends_on": ["mul"], "files": ["z.txt"], "checks": ["unit"]}


class ExhaustedTests(OrchestratorCase):
    def exhaust(self) -> None:
        self.overrides = {"limits": {"max_attempts": 2}}
        self.start("two things", files_touched_estimate=6, independent_subtasks=3)
        self.set_plan(MUL, FINAL)
        for summary in ("first", "second, different"):
            self.orch().next_tasks()
            self.orch().start_task("mul")
            self.orch().record_task("mul", TaskStatus.FAILED, summary)

    def test_an_exhausted_task_cannot_be_recorded_not_executed(self) -> None:
        self.exhaust()
        with self.assertRaises(ValidationError) as caught:
            self.orch().record_task("mul", TaskStatus.NOT_EXECUTED, "reset?")
        self.assertEqual(caught.exception.code, "attempts_exhausted")
        self.assertIn("wev task reopen mul", caught.exception.details["next_step"])
        self.assertEqual(self.status_of("mul"), TaskStatus.BLOCKED)
        report = self.orch().report()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["tasks"][0]["blocked_because"], "attempts_exhausted")
        self.assertTrue(any("used all its attempts" in reason for reason in report["reasons"]))

    def test_the_primary_step_of_an_exhausted_task_is_the_reopen_instruction(self) -> None:
        self.exhaust()
        for out in (self.orch().status(), self.orch().next_tasks(), self.orch().report()):
            step = out["next_step"]
            self.assertIn("Stop and ask the human", step)
            self.assertIn("wev task reopen mul", step)
            self.assertFalse(step.startswith("wev "), step)

    def test_other_startable_work_still_comes_first(self) -> None:
        self.overrides = {"limits": {"max_attempts": 1}}
        self.start("two things", files_touched_estimate=6, independent_subtasks=3)
        self.set_plan(MUL, {"id": "free", "files": ["free.txt"], "checks": ["unit"]})
        self.orch().next_tasks()
        self.orch().start_task("mul")
        self.orch().record_task("mul", TaskStatus.FAILED, "boom")
        out = self.orch().status()
        self.assertTrue(out["next_step"].startswith("wev task"), out["next_step"])
        self.assertTrue(any("wev task reopen mul" in step for step in out["next_steps"]))


class NoProgressTests(OrchestratorCase):
    READS = [("ls",), ("git", "status"), ("git", "log", "--oneline"), ("cat", "calc.py")]
    FILES = [("cat", f"src/{name}.py") for name in "abcdefghij"]

    def test_plan_mode_reading_never_trips_no_progress(self) -> None:
        self.start(mode=Mode.PLAN)
        for argv in (*self.READS, *self.FILES):
            payload, code = self.orch().exec_command(argv)
            self.assertEqual((code, payload["guard"]["action"]), (0, "continue"), argv)
        self.assertEqual(self.orch().status()["guard"]["action"], "continue")

    def test_reading_before_the_first_edit_never_trips_no_progress(self) -> None:
        self.start()
        self.run_task(work=False)
        for argv in (*self.READS, *self.FILES):
            payload, code = self.orch().exec_command(argv)
            self.assertEqual((code, payload["guard"]["action"]), (0, "continue"), argv)
        self.runner.edit("the fix")
        payload, code = self.orch().exec_command(("make", "test"))
        self.assertEqual((code, payload["guard"]["action"]), (0, "continue"))
        self.assertTrue(self.orch().check_task("task-1")["all_met"])

    def test_commands_that_can_change_the_tree_still_count(self) -> None:
        self.start()
        self.run_task(work=False)
        actions = []
        for index in range(9):
            payload, _ = self.orch().exec_command(("touch", f"f{index}"))
            actions.append(payload["guard"]["rule"])
        self.assertIn("no_progress", actions)

    def test_a_repeated_read_is_still_a_loop(self) -> None:
        self.start()
        self.run_task(work=False)
        self.runner.on(("ls", "/nonexistent"), exit_code=1)
        rules = []
        with self.assertRaises(GuardTripped):
            for _ in range(8):
                payload, _ = self.orch().exec_command(("ls", "/nonexistent"))
                rules.append(payload["guard"]["rule"])
        self.assertIn("identical_commands", rules)


class VerifiedThenChangedTests(OrchestratorCase):
    def verified_run(self) -> None:
        self.start()
        self.run_task()
        self.verify(work=False)

    def test_a_change_after_verified_makes_the_report_incomplete(self) -> None:
        self.verified_run()
        self.assertEqual(self.orch().report()["status"], "complete")
        self.runner.edit("broken afterwards")
        report = self.orch().report()
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["tasks"][0]["verified_then_changed"])
        self.assertTrue(any("verified, then changed" in reason for reason in report["reasons"]))
        self.assertIn("wev task check task-1", report["next_step"])
        self.assertIn("verified, then changed", render_markdown(report, "en"))
        self.assertIn(
            "verificada, depois alterada", render_markdown(self.orch().report("pt-BR"), "pt-BR")
        )

    def test_finish_reports_incomplete_and_keeps_saying_so(self) -> None:
        self.verified_run()
        self.runner.edit("broken afterwards")
        finished = self.orch().finish()
        self.assertFalse(finished["complete"])
        self.assertEqual(finished["changed_after_verification"], ["task-1"])
        self.runner.edit("the next day")
        report = self.orch().report()
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["tasks"][0]["verified_then_changed"])

    def test_a_finished_run_is_not_judged_by_later_changes(self) -> None:
        self.verified_run()
        self.assertTrue(self.orch().finish()["complete"])
        self.runner.edit("the next day")
        report = self.orch().report()
        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["tasks"][0]["verified_then_changed"])

    def test_checking_again_on_the_new_tree_clears_it(self) -> None:
        self.verified_run()
        self.runner.edit("a harmless later edit")
        self.assertEqual(self.orch().report()["status"], "incomplete")
        self.assertTrue(self.orch().check_task("task-1")["all_met"])
        report = self.orch().report()
        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["tasks"][0]["verified_then_changed"])
        self.assertTrue(self.orch().finish()["complete"])

    def test_a_failing_recheck_keeps_it_incomplete(self) -> None:
        self.verified_run()
        self.runner.edit("broken afterwards")
        self.runner.on(("make", "test"), exit_code=1)
        self.assertFalse(self.orch().check_task("task-1")["all_met"])
        self.assertEqual(self.orch().report()["status"], "incomplete")

    def test_work_of_a_later_task_does_not_mark_an_earlier_one(self) -> None:
        self.start("two things", files_touched_estimate=6, independent_subtasks=3)
        self.set_plan({"id": "a"}, {"id": "b", "depends_on": ["a"]})
        for task_id in ("a", "b"):
            self.orch().next_tasks()
            self.orch().start_task(task_id)
            self.verify(task_id)
            self.orch().review_task(task_id, "reviewer", True, "ok")
        report = self.orch().report()
        self.assertEqual(report["status"], "complete", report["reasons"])
        self.assertEqual([t["verified_then_changed"] for t in report["tasks"]], [False, False])

    def test_a_running_task_owns_the_changes_made_meanwhile(self) -> None:
        self.start("two things", files_touched_estimate=6, independent_subtasks=3)
        self.set_plan({"id": "a"}, {"id": "b", "depends_on": ["a"]})
        self.orch().next_tasks()
        self.orch().start_task("a")
        self.verify("a")
        self.orch().review_task("a", "reviewer", True, "ok")
        self.orch().next_tasks()
        self.orch().start_task("b")
        self.runner.edit("b in progress")
        self.assertFalse(self.orch().report()["tasks"][0]["verified_then_changed"])


class StaleApprovalTests(OrchestratorCase):
    def test_a_replaced_check_does_not_leave_its_approval_blocking(self) -> None:
        self.start("planned", files_touched_estimate=6)
        task: dict[str, Any] = {
            "id": "sub",
            "acceptance_criteria": ["sub works"],
            "checks": [INLINE],
        }
        self.set_plan(task)
        self.orch().next_tasks()
        self.orch().start_task("sub")
        self.runner.edit("sub")
        first = self.orch().check_task("sub")
        self.assertFalse(first["all_met"])
        self.assertEqual(len(first["pending_approvals"]), 1)
        self.assertIn("Stop and ask the human", first["next_step"])
        amended = {**task, "checks": ["unit test_sub"]}
        self.orch().set_plan(self.plan_file(amended), amend_reason="a named test instead")
        second = self.orch().check_task("sub")
        self.assertTrue(second["all_met"])
        self.assertEqual(second["next_step"].split()[:4], ["wev", "task", "record", "sub"])
        status = self.orch().status()
        self.assertEqual(status["pending_approvals"], [])
        self.assertEqual(status["stale_approvals"], first["pending_approvals"])
        recorded = self.orch().record_task("sub", TaskStatus.VERIFIED, "done")
        self.assertTrue(recorded["next_step"].startswith("wev "), recorded["next_step"])


class DeniedGateTests(OrchestratorCase):
    def denied(self) -> str:
        self.start()
        self.set_plan({"id": "a", "risk": "high"})
        with self.assertRaises(ApprovalRequired) as gate:
            self.orch().start_task("a")
        approval = gate.exception.details["approval_ids"][0]
        self.services().approvals.deny(approval, "ana")
        return str(approval)

    def assert_denied_step(self, step: str, approval: str) -> None:
        self.assertIn("denied by the operator", step)
        self.assertIn("--reopen-denied", step)
        self.assertIn(approval, step)
        self.assertNotIn("approval grant", step)
        self.assertFalse(step.startswith("wev "), step)

    def test_starting_a_denied_task_says_it_was_denied_and_how_to_reopen(self) -> None:
        approval = self.denied()
        with self.assertRaises(PermissionDenied) as caught:
            self.orch().start_task("a")
        error = caught.exception
        self.assertEqual(error.code, "approval_denied")
        self.assertIn("denied", error.message)
        self.assert_denied_step(error.details["next_step"], approval)
        self.assertEqual(self.orch().status()["pending_approvals"], [])

    def test_task_next_and_status_say_the_same(self) -> None:
        approval = self.denied()
        out = self.orch().next_tasks()
        self.assertEqual(out["tasks"], [])
        self.assertIn("denied", out["deferred"][0]["reason"])
        self.assert_denied_step(out["next_step"], approval)
        self.assert_denied_step(self.orch().status()["next_step"], approval)


class PlanModeStepTests(OrchestratorCase):
    def test_once_the_plan_is_set_the_step_is_review_then_a_new_run(self) -> None:
        started = self.start(mode=Mode.PLAN)
        self.assertEqual(started["next_step"], f"wev plan set --file plan.json --run {RUN_ID}")
        planned = self.set_plan({"id": "a", "checks": ["make test"]})
        for step in (planned["next_step"], self.orch().status()["next_step"]):
            self.assertIn("ready for human review", step)
            self.assertIn(f"wev plan show --run {RUN_ID}", step)
            self.assertIn(f"wev run finish --run {RUN_ID}", step)
            self.assertIn("--mode execute", step)
            self.assertFalse(step.startswith("wev "), step)


class NoChangeStepTests(OrchestratorCase):
    def test_a_check_on_an_untouched_tree_points_to_the_work_or_read_only(self) -> None:
        self.start()
        self.run_task(work=False)
        checked = self.orch().check_task("task-1")
        self.assertFalse(checked["all_met"])
        step = checked["next_step"]
        self.assertFalse(step.startswith("wev task check"), step)
        self.assertIn("No file changed", step)
        self.assertIn("read_only", step)
        self.assertIn("wev task check task-1", step)
        self.assertEqual(self.orch().status()["next_step"], step)
        self.runner.edit("the work")
        after = self.orch().check_task("task-1")
        self.assertTrue(after["all_met"])
        self.assertEqual(after["next_step"].split()[:4], ["wev", "task", "record", "task-1"])


class PlanWarningTests(OrchestratorCase):
    def test_a_check_that_will_need_approval_is_announced_at_plan_set(self) -> None:
        self.start("planned", files_touched_estimate=6)
        out = self.set_plan(
            {"id": "sub", "checks": [INLINE, "make test"]},
            {"id": "clean", "checks": ["rm -rf build"]},
        )
        text = "\n".join(out["warnings"])
        self.assertEqual(len(out["warnings"]), 2, out["warnings"])
        self.assertIn("sub", text)
        self.assertIn(INLINE, text)
        self.assertIn("approval", text)
        self.assertIn("script file", text)
        self.assertNotIn("make test", text)

    def test_a_plan_without_such_checks_has_no_warning(self) -> None:
        self.start("planned", files_touched_estimate=6)
        self.assertEqual(self.set_plan({"id": "a", "checks": ["make test"]})["warnings"], [])
