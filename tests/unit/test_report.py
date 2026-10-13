from __future__ import annotations

import json

from tests.unit._orchestrator_helpers import RUN_ID, OrchestratorCase
from wev_skills.core.contracts import Evidence, EvidenceLabel, Mode, TaskStatus
from wev_skills.core.errors import ApprovalRequired
from wev_skills.core.report_markdown import render_markdown

TESTS = ("make", "test")
LABELS = {"tested", "untested", "mocked", "documented_only", "blocked"}


class ReportCase(OrchestratorCase):
    def running(self, **signals: object) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start(**signals)
        self.run_task()

    def task(self, index: int = 0) -> dict:  # type: ignore[type-arg]
        return self.orch().report()["tasks"][index]  # type: ignore[no-any-return]


class StatusTests(ReportCase):
    def test_complete_only_when_every_task_is_verified(self) -> None:
        self.running()
        report = self.orch().report()
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("Task task-1 is running, not verified.", report["reasons"])
        self.verify()
        report = self.orch().report()
        self.assertEqual((report["status"], report["reasons"]), ("complete", []))
        self.assertEqual((report["objective"], report["run_id"]), ("Add a greeting", RUN_ID))
        self.assertEqual(report["classification"]["risk"], "low")
        self.assertEqual(report["strategy"]["flow"], "direct")

    def test_run_without_tasks_or_in_plan_mode_is_incomplete(self) -> None:
        self.start(mode=Mode.PLAN)
        report = self.orch().report()
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("Plan mode: nothing was executed.", report["reasons"])
        self.assertIn("The run has no tasks yet.", report["reasons"])

    def test_a_blocked_task_and_its_blockers_block_the_run(self) -> None:
        self.running()
        self.orch().record_task("task-1", TaskStatus.BLOCKED, "stuck", blockers=["no access"])
        report = self.orch().report()
        self.assertEqual(report["status"], "blocked")
        self.assertIn("Blocker: no access", report["reasons"])
        self.assertEqual(report["tasks"][0]["evidence"], "blocked")

    def test_pending_approval_blocks_and_is_listed_with_its_action(self) -> None:
        self.start(touches_production=True)
        self.set_plan({"id": "a"})
        with self.assertRaises(ApprovalRequired) as caught:
            self.orch().next_tasks()
        approval = caught.exception.details["approval_ids"][0]
        report = self.orch().report()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["pending_approvals"], [approval])
        listed = report["approvals"][0]
        self.assertEqual((listed["id"], listed["status"]), (approval, "pending"))
        self.assertEqual(listed["action"], f"wev task {RUN_ID} a")

    def test_guard_trips_are_listed(self) -> None:
        self.running()
        self.runner.on(("false",), exit_code=1)
        for _ in range(5):
            self.orch().exec_command(("false",))
        report = self.orch().report()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["guard"]["verdict"]["action"], "ask_human")
        self.assertEqual(report["guard"]["trips"][0]["task_id"], "task-1")


class EvidenceTests(ReportCase):
    def test_verified_task_shows_checks_with_exit_codes_logs_and_labels(self) -> None:
        self.running()
        self.orch().check_task("task-1")
        self.orch().record_task("task-1", TaskStatus.VERIFIED, "done", changed_files=["g.py"])
        task = self.task()
        self.assertEqual(
            (task["status"], task["evidence"], task["attempts"]), ("verified", "tested", 1)
        )
        self.assertEqual((task["agent_id"], task["model"]), ("builder", "claude-sonnet-5-5"))
        self.assertEqual(task["criteria"][0]["status"], "met")
        check = task["checks_run"][0]
        self.assertEqual(
            (check["command"], check["exit_code"], check["evidence"]), ("make test", 0, "tested")
        )
        self.assertTrue(check["log_ref"].endswith(".stdout.log"))
        self.assertEqual(task["checks_not_run"], [])
        self.assertEqual(self.orch().report()["changed_files"], ["g.py"])

    def test_nothing_is_called_tested_without_evidence(self) -> None:
        self.running()
        task = self.task()
        self.assertEqual((task["evidence"], task["checks_run"]), ("untested", []))
        self.assertEqual(task["criteria"][0]["status"], "unverified")
        self.assertEqual(task["criteria"][0]["evidence"], "untested")
        self.orch().record_task("task-1", TaskStatus.PARTIAL, "half way")
        self.assertEqual(self.task()["evidence"], "untested")

    def test_failed_and_skipped_checks_are_reported_as_such(self) -> None:
        self.start()
        self.set_plan(
            {"id": "a", "acceptance_criteria": ["works"], "checks": ["ruff check .", "make test"]}
        )
        self.run_task("a")
        self.runner.on(("ruff", "check", "."), exit_code=1)
        self.orch().check_task("a")
        task = self.task()
        self.assertEqual(
            task["criteria"][0],
            {
                "criterion": "works",
                "status": "unmet",
                "evidence": "tested",
                "support": "none",
                "support_note": "A check that supports this criterion failed.",
                "evidence_refs": task["criteria"][0]["evidence_refs"],
            },
        )
        self.assertEqual(task["checks_run"][0]["exit_code"], 1)
        self.assertEqual(
            task["checks_not_run"],
            [{"command": "make test", "state": "not_run", "reason": "", "evidence": "untested"}],
        )

    def test_a_stale_verification_does_not_speak_for_a_restarted_task(self) -> None:
        self.running()
        self.orch().check_task("task-1")
        self.orch().resume()
        task = self.task()
        self.assertEqual((task["checks_run"], task["criteria"][0]["status"]), ([], "unverified"))

    def test_manual_evidence_labels_are_kept(self) -> None:
        self.start()
        self.run_task()
        name = self.orch().contract(self.state(), "task-1").acceptance_criteria[0]
        ref = self.evidence_file("x.md", "notes\n")
        weak = Evidence(name, "described in the docs", ref, None, EvidenceLabel.DOCUMENTED_ONLY)
        self.orch().record_task("task-1", TaskStatus.PARTIAL, "documented", evidence=(weak,))
        self.assertEqual(self.task()["criteria"][0]["evidence"], "documented_only")

    def test_every_label_in_the_report_is_a_known_evidence_label(self) -> None:
        self.running()
        self.verify()
        task = self.task()
        found = {
            task["evidence"],
            *(c["evidence"] for c in task["criteria"]),
            *(c["evidence"] for c in task["checks_run"]),
        }
        self.assertLessEqual(found, LABELS)


class ReviewAndMarkdownTests(ReportCase):
    def reviewed(self) -> None:
        self.start(files_touched_estimate=8)
        self.set_plan({"id": "a", "acceptance_criteria": ["works | well"], "checks": ["make test"]})
        self.run_task("a")
        self.verify("a")

    def test_required_review_keeps_the_run_incomplete_until_accepted(self) -> None:
        self.reviewed()
        report = self.orch().report()
        self.assertEqual(report["status"], "incomplete")
        self.assertIn(
            "Task a is verified but has no accepting independent review.", report["reasons"]
        )
        self.orch().review_task("a", "reviewer", True, "read the diff")
        task = self.task()
        self.assertEqual((task["review"]["required"], task["review"]["accepted"]), (True, True))
        self.assertEqual(task["review"]["reviews"][0]["reviewer"], "reviewer")
        self.assertEqual(self.orch().report()["status"], "complete")

    def test_markdown_in_both_languages_restates_the_report(self) -> None:
        self.reviewed()
        report = self.orch().report("en")
        english = render_markdown(report, "en")
        self.assertIn(f"# Delivery report: run {RUN_ID}", english)
        self.assertIn("**Overall status:** incomplete", english)
        self.assertIn("| works \\| well | met | tested |", english)
        self.assertIn("An independent review is required", english)
        self.assertIn("| make test | 0 |", english)
        portuguese = render_markdown(self.orch().report("pt-BR"), "pt-BR")
        self.assertIn(f"# Relatório de entrega: execução {RUN_ID}", portuguese)
        self.assertIn("**Status geral:** incompleta", portuguese)
        self.assertIn("| atendido | testado |", portuguese)
        self.assertIn("A tarefa a está verificada, mas não tem revisão independente", portuguese)

    def test_markdown_shows_unrun_checks_and_never_claims_completion(self) -> None:
        self.running()
        text = render_markdown(self.orch().report("en"), "en")
        self.assertIn("No check ran for this task.", text)
        self.assertIn("| unverified | untested |", text)
        self.assertNotIn("**Overall status:** complete", text)

    def test_report_is_json_serializable_and_read_only(self) -> None:
        self.running()
        before = self.state().revision
        json.dumps(self.orch().report())
        self.assertEqual(self.state().revision, before)
