from __future__ import annotations

from tests.unit._orchestrator_helpers import RUN_ID, OrchestratorCase
from wev_skills.core.contracts import Evidence, EvidenceLabel, TaskStatus
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError

TESTS = ("make", "test")


class RecordTests(OrchestratorCase):
    def running(self, **signals: object) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start(**signals)
        self.run_task()

    def criterion(self) -> str:
        return self.orch().contract(self.state(), "task-1").acceptance_criteria[0]

    def refuse_verified(self, *evidence: Evidence) -> ValidationError:
        with self.assertRaises(ValidationError) as caught:
            self.orch().record_task("task-1", TaskStatus.VERIFIED, "trust me", evidence=evidence)
        self.assertEqual(caught.exception.code, "verification_required")
        self.assertEqual(self.status_of("task-1"), TaskStatus.RUNNING)
        return caught.exception

    def test_verified_is_refused_without_any_check(self) -> None:
        self.running()
        error = self.refuse_verified()
        self.assertEqual(error.details["next_step"], f"wev task check task-1 --run {RUN_ID}")
        self.assertEqual(error.details["missing"], [self.criterion()])

    def test_verified_is_refused_after_a_failing_check(self) -> None:
        self.running()
        self.runner.on(TESTS, exit_code=1)
        self.orch().check_task("task-1")
        self.refuse_verified()

    def test_verified_is_refused_when_the_check_predates_the_last_start(self) -> None:
        self.running()
        self.orch().check_task("task-1")
        self.orch().record_task("task-1", TaskStatus.FAILED, "broke something else")
        self.run_task()
        self.refuse_verified()

    def test_verified_is_accepted_after_a_fresh_passing_check(self) -> None:
        self.running()
        self.orch().check_task("task-1")
        out = self.orch().record_task(
            "task-1", TaskStatus.VERIFIED, "done", changed_files=["greet.py"]
        )
        self.assertEqual((out["status"], out["attempt"]), ("verified", 1))
        self.assertEqual(out["next_step"], f"wev run finish --run {RUN_ID}")
        state = self.state()
        self.assertEqual(state.tasks["task-1"].result.changed_files, ("greet.py",))
        self.assertEqual(state.tasks["task-1"].attempts[0].status, TaskStatus.VERIFIED)
        self.assertEqual(state.phase.value, "deliver")
        self.assertIn("task.recorded", self.audit_types())

    def test_manual_evidence_must_be_tested_with_a_ref_for_every_open_criterion(self) -> None:
        self.running()
        notes, log, manual = (self.evidence_file(n) for n in ("notes.md", "log.txt", "manual.txt"))
        name = self.criterion()
        self.refuse_verified(Evidence(name, "looked at it", "", None, EvidenceLabel.TESTED))
        documented = EvidenceLabel.DOCUMENTED_ONLY
        self.refuse_verified(Evidence(name, "docs", notes, None, documented))
        self.refuse_verified(Evidence("another", "x", log, None, EvidenceLabel.TESTED))
        proof = Evidence(f"criterion:{name}", "ran it by hand", manual, 0, EvidenceLabel.TESTED)
        self.orch().record_task("task-1", TaskStatus.VERIFIED, "done", evidence=(proof,))
        self.assertEqual(self.status_of("task-1"), TaskStatus.VERIFIED)

    def test_manual_evidence_ref_must_be_an_existing_file_inside_the_repository(self) -> None:
        self.running()
        name = self.criterion()
        outside = self.root.parent / "outside-proof.txt"
        outside.write_text("x", encoding="utf-8")
        self.addCleanup(outside.unlink)
        (self.root / "docs").mkdir()
        audit = ".wev/audit.jsonl"
        self.assertTrue((self.root / audit).is_file())
        (self.root / "unrelated.txt").write_text("x", encoding="utf-8")
        refs = ("missing.txt", str(outside), "../outside-proof.txt", "docs", audit, "unrelated.txt")
        for ref in refs:
            proof = Evidence(name, "claimed", ref, 0, EvidenceLabel.TESTED)
            with self.subTest(ref=ref), self.assertRaises(ValidationError) as caught:
                self.orch().record_task("task-1", TaskStatus.VERIFIED, "done", evidence=(proof,))
            self.assertEqual(caught.exception.code, "invalid_evidence_ref")
        self.assertEqual(self.status_of("task-1"), TaskStatus.RUNNING)

    def test_a_command_log_of_the_run_is_an_acceptable_manual_reference(self) -> None:
        self.running()
        payload, _ = self.orch().exec_command(("echo", "proof"))
        proof = Evidence(
            self.criterion(), "ran it", payload["record"]["stdout_ref"], 0, EvidenceLabel.TESTED
        )
        self.orch().record_task("task-1", TaskStatus.VERIFIED, "done", evidence=(proof,))
        self.assertEqual(self.status_of("task-1"), TaskStatus.VERIFIED)

    def test_failed_outcome_records_an_attempt_with_a_stable_error_signature(self) -> None:
        self.running()
        first = self.orch().record_task("task-1", TaskStatus.FAILED, "TypeError at line 12")
        self.assertEqual(first["recommended_action"], "continue")
        self.assertIsNone(first["next_model"])
        self.run_task()
        second = self.orch().record_task("task-1", TaskStatus.FAILED, "TypeError at line 40")
        self.assertEqual(first["error_signature"], second["error_signature"])
        self.assertEqual(second["recommended_action"], "escalate")
        self.assertEqual(second["next_model"], "claude-opus-5-5")
        attempts = self.state().tasks["task-1"].attempts
        self.assertEqual([a.attempt for a in attempts], [1, 2])
        self.assertEqual(attempts[1].error_signature, second["error_signature"])
        kinds = [dict(e)["kind"] for e in self.state().guard_events]
        self.assertEqual(kinds.count("task_attempt"), 2)

    def test_escalation_takes_effect_while_an_attempt_remains(self) -> None:
        self.overrides = {"limits": {"max_attempts": 2}}
        self.running()
        out = self.orch().record_task("task-1", TaskStatus.FAILED, "first")
        self.assertTrue(out["escalation"]["escalate"])
        self.assertEqual(
            (out["recommended_action"], out["next_model"]), ("escalate", "claude-opus-5-5")
        )
        self.assertEqual(self.state().tasks["task-1"].model, "claude-opus-5-5")
        self.assertIn("recommended action: escalate", self.state().decisions[-1].decision)
        self.orch().next_tasks()
        started = self.orch().start_task("task-1")
        self.assertEqual((started["attempt"], started["model"]), (2, "claude-opus-5-5"))

    def test_exhausted_attempts_block_the_task_until_a_person_reopens_it(self) -> None:
        self.overrides = {"limits": {"max_attempts": 2}}
        self.running()
        self.orch().record_task("task-1", TaskStatus.FAILED, "first")
        self.run_task()
        out = self.orch().record_task("task-1", TaskStatus.FAILED, "second, different")
        self.assertEqual((out["status"], out["reported_status"]), ("blocked", "failed"))
        self.assertTrue(out["attempts_exhausted"])
        self.assertEqual((out["recommended_action"], out["next_model"]), ("ask_human", None))
        self.assertIn("wev task reopen task-1", out["next_step"])
        self.assertIn("Stop and ask the human", out["next_step"])
        deferred = self.orch().next_tasks()["deferred"]
        self.assertIn("all its 2 attempt", deferred[0]["reason"])
        with self.assertRaises(ValidationError) as caught:
            self.orch().start_task("task-1")
        self.assertEqual(caught.exception.code, "attempts_exhausted")
        self.assertEqual(self.state().tasks["task-1"].starts, 2)
        reopened = self.orch().reopen_task("task-1", "new information", "ana", "tty")
        self.assertEqual((reopened["status"], reopened["previous_attempts"]), ("pending", 2))
        self.assertEqual(self.state().tasks["task-1"].starts, 0)
        self.assertEqual(self.state().decisions[-1].source, "reopen")
        self.assertIn("ana", " ".join(self.state().decisions[-1].reasons))
        self.assertIn("task.reopened", self.audit_types())
        self.run_task()
        self.assertEqual(self.status_of("task-1"), TaskStatus.RUNNING)

    def test_every_start_counts_whatever_the_previous_outcome_was(self) -> None:
        self.overrides = {"limits": {"max_attempts": 3}}
        self.running()
        self.orch().record_task("task-1", TaskStatus.PARTIAL, "half")
        self.run_task()
        self.orch().record_task("task-1", TaskStatus.BLOCKED, "waiting")
        self.orch().start_task("task-1")
        out = self.orch().record_task("task-1", TaskStatus.PARTIAL, "still half")
        self.assertEqual((out["attempt"], out["status"]), (3, "blocked"))
        for call in (self.orch().next_tasks, lambda: self.orch().start_task("task-1")):
            try:
                result = call()
            except ValidationError as exc:
                self.assertEqual(exc.code, "attempts_exhausted")
            else:
                self.assertEqual(result["tasks"], [])
        self.assertEqual(self.state().tasks["task-1"].starts, 3)

    def test_failed_is_refused_for_a_task_that_is_not_running(self) -> None:
        self.running()
        self.orch().record_task("task-1", TaskStatus.FAILED, "first")
        with self.assertRaises(ValidationError) as caught:
            self.orch().record_task("task-1", TaskStatus.FAILED, "again, without a start")
        self.assertEqual(caught.exception.code, "task_not_running")
        self.assertEqual(len(self.state().tasks["task-1"].attempts), 1)

    def test_reopen_needs_a_reason_and_a_task_that_ran(self) -> None:
        self.running()
        for reason, code in (("  ", "reason_required"), ("why", "task_not_reopenable")):
            with self.assertRaises(ValidationError) as caught:
                self.orch().reopen_task("task-1", reason, "ana", "tty")
            self.assertEqual(caught.exception.code, code)

    def test_blocked_outcome_is_listed_and_cleared_when_the_task_is_later_verified(self) -> None:
        self.running()
        self.orch().record_task("task-1", TaskStatus.BLOCKED, "waiting", blockers=["no API key"])
        self.assertEqual(self.state().blockers, ("no API key",))
        self.assertEqual(self.orch().next_tasks()["tasks"], [])
        self.orch().start_task("task-1")
        self.verify()
        self.assertEqual(self.state().blockers, ())

    def test_illegal_or_unknown_records_are_refused(self) -> None:
        self.start()
        self.orch().next_tasks()
        with self.assertRaises(ValidationError):
            self.orch().record_task("task-1", TaskStatus.PARTIAL, "never started")
        with self.assertRaises(NotFound):
            self.orch().record_task("ghost", TaskStatus.FAILED, "x")


class ReviewTests(OrchestratorCase):
    def verified(self) -> None:
        self.start(files_touched_estimate=8)
        self.assertTrue(self.state().strategy.needs_independent_review)
        self.set_plan({"id": "a", "acceptance_criteria": ["works"], "checks": ["make test"]})
        self.run_task("a")
        self.verify("a")

    def test_verified_task_waits_for_review_and_the_step_names_a_reviewer(self) -> None:
        self.verified()
        self.assertEqual(self.state().phase.value, "review")
        expected = "wev task review a --reviewer reviewer --verdict accept --summary <text>"
        self.assertEqual(self.state().next_step, f"{expected} --run {RUN_ID}")
        self.assertEqual(self.orch().report()["status"], "incomplete")

    def test_self_review_and_unknown_reviewers_are_refused(self) -> None:
        self.verified()
        with self.assertRaises(PermissionDenied) as denied:
            self.orch().review_task("a", "builder", True, "looks fine to me")
        self.assertEqual(denied.exception.code, "self_review")
        with self.assertRaises(ValidationError) as unknown:
            self.orch().review_task("a", "nobody", True, "ok")
        self.assertEqual(unknown.exception.code, "unknown_reviewer")
        self.assertEqual(self.state().reviews, ())

    def test_accepting_review_completes_the_run(self) -> None:
        self.verified()
        out = self.orch().review_task("a", "reviewer", True, "checked the diff")
        self.assertTrue(out["complete"])
        self.assertEqual(out["next_step"], f"wev run finish --run {RUN_ID}")
        self.assertEqual(self.orch().report()["status"], "complete")
        self.assertIn("task.reviewed", self.audit_types())

    def test_rejecting_review_reopens_the_task_with_the_summary_as_context(self) -> None:
        self.verified()
        out = self.orch().review_task("a", "reviewer", False, "edge case is not covered")
        self.assertEqual((out["task_status"], out["complete"]), ("pending", False))
        contract = self.orch().next_tasks()["tasks"][0]
        self.assertIn("edge case is not covered", contract["context"])
        self.orch().start_task("a")
        with self.assertRaises(ValidationError):
            self.orch().record_task("a", TaskStatus.VERIFIED, "same as before")
        self.verify("a")
        self.assertEqual(self.orch().report()["status"], "incomplete")
        self.orch().review_task("a", "reviewer", True, "covered now")
        self.assertEqual(self.orch().report()["status"], "complete")

    def test_only_a_verified_task_can_be_reviewed(self) -> None:
        self.start(files_touched_estimate=8)
        self.set_plan({"id": "a"})
        with self.assertRaises(ValidationError) as caught:
            self.orch().review_task("a", "reviewer", True, "ok")
        self.assertEqual(caught.exception.code, "task_not_verified")

    def test_without_the_review_requirement_verified_is_enough(self) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start()
        self.run_task()
        self.verify()
        self.assertEqual(self.orch().report()["status"], "complete")
