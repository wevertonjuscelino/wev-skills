from __future__ import annotations

import json
from pathlib import Path

from tests.unit._orchestrator_helpers import RUN_ID, OrchestratorCase
from wev_skills.core.contracts import Mode, TaskStatus
from wev_skills.core.errors import (
    ApprovalRequired,
    GuardTripped,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from wev_skills.core.fingerprint import FS_PREFIX, tree_fingerprint

SECRET = "example_" + "Hunter2" * 3
TESTS = ("make", "test")


class ExecTests(OrchestratorCase):
    def running(self, **signals: object) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start(**signals)
        self.run_task()

    def test_passing_command_is_logged_with_a_guard_event_and_exit_zero(self) -> None:
        self.running()
        payload, code = self.orch().exec_command(("echo", "hi"))
        self.assertEqual((code, payload["record"]["status"]), (0, "passed"))
        self.assertEqual(payload["guard"]["action"], "continue")
        state = self.state()
        entry = state.commands[-1]
        self.assertEqual((entry.task_id, entry.argv), ("task-1", ("echo", "hi")))
        self.assertEqual(entry.exit_code, 0)
        self.assertTrue(Path(entry.stdout_ref).is_file())
        kinds = [dict(event)["kind"] for event in state.guard_events]
        self.assertEqual(kinds[-2:], ["command", "budget"])
        self.assertEqual(dict(state.guard_events[-1])["units"], 1.0)
        self.assertEqual(state.evidence[-1].evidence.label.value, "tested")
        self.assertIn("exec.ran", self.audit_types())

    def test_failed_and_unknown_outcomes_exit_one(self) -> None:
        self.running()
        self.runner.on(("false",), exit_code=1)
        self.runner.on(("sleep", "99"), exit_code=None)
        self.assertEqual(self.orch().exec_command(("false",))[1], 1)
        payload, code = self.orch().exec_command(("sleep", "99"), timeout=0.1)
        self.assertEqual((code, payload["record"]["status"]), (1, "unknown"))

    def test_command_runs_under_the_task_risk_and_the_run_mode(self) -> None:
        self.start()
        self.set_plan({"id": "a", "risk": "high"})
        with self.assertRaises(PermissionDenied) as pending:
            self.orch().exec_command(("touch", "x"), task_id="a")
        self.assertEqual(pending.exception.code, "exec_task_not_running")
        with self.assertRaises(PermissionDenied) as nothing_running:
            self.orch().exec_command(("touch", "x"))
        self.assertEqual(nothing_running.exception.code, "exec_no_running_task")
        with self.assertRaises(ApprovalRequired) as gate:
            self.orch().start_task("a")
        self.grant(gate.exception.details["approval_ids"][0])
        self.orch().start_task("a")
        with self.assertRaises(ApprovalRequired):
            self.orch().exec_command(("touch", "x"), task_id="a")
        with self.assertRaises(ApprovalRequired):
            self.orch().exec_command(("touch", "x"))
        with self.assertRaises(PermissionDenied) as ghost:
            self.orch().exec_command(("ls",), task_id="ghost")
        self.assertEqual(ghost.exception.code, "exec_task_not_running")

    def test_plan_mode_denies_a_mutating_command_and_allows_a_read(self) -> None:
        self.start(mode=Mode.PLAN)
        with self.assertRaises(PermissionDenied):
            self.orch().exec_command(("touch", "x"))
        self.assertEqual(self.runner.commands(), [])
        self.assertIn("exec.denied", self.audit_types())
        self.assertEqual(self.orch().exec_command(("ls",))[1], 0)

    def test_command_touching_the_state_directory_is_denied(self) -> None:
        self.running()
        for target in (".wev/approvals.json", str(self.root / ".wev" / "runs")):
            with self.subTest(target=target), self.assertRaises(PermissionDenied):
                self.orch().exec_command(("cp", "x", target))
        self.assertEqual([call for call in self.runner.commands() if call[0] == "cp"], [])

    def test_approval_is_requested_recorded_and_spent_by_one_execution(self) -> None:
        self.running()
        push = ("git", "push", "origin", "main")
        with self.assertRaises(ApprovalRequired) as caught:
            self.orch().exec_command(push)
        approval = caught.exception.details["approval_id"]
        self.assertEqual(self.state().pending_approvals, (approval,))
        self.assertEqual(self.state().decisions[-1].source, "approval")
        self.assertNotIn(push, self.runner.calls)
        self.grant(approval)
        self.assertEqual(self.orch().exec_command(push)[1], 0)
        self.assertEqual(self.state().pending_approvals, ())
        with self.assertRaises(ApprovalRequired):
            self.orch().exec_command(push)
        self.assertEqual(self.runner.calls.count(push), 1)

    def test_secret_printed_by_a_command_reaches_no_state_audit_or_log(self) -> None:
        self.running()
        self.runner.on(("cat", "leak.txt"), stdout=f"api_key={SECRET}\n", stderr=f"token: {SECRET}")
        payload, _ = self.orch().exec_command(("cat", "leak.txt"))
        self.orch().exec_command(("curl", f"--token={SECRET}", "https://example.invalid"))
        written = "".join(
            path.read_text(encoding="utf-8")
            for path in (self.root / ".wev").rglob("*")
            if path.is_file()
        )
        self.assertNotIn(SECRET, written + json.dumps(payload))
        self.assertIn("[REDACTED]", written)

    def test_polling_a_named_running_task_does_not_trip_the_repetition_rule(self) -> None:
        self.running()
        self.orch().exec_command(("tmux", "new-session", "-d"), task_id="task-1")
        for _ in range(6):
            payload, code = self.orch().exec_command(("ls",), task_id="task-1", polling=True)
        self.assertEqual((code, payload["guard"]["action"]), (0, "continue"))
        self.assertEqual(payload["polling"], {"requested": True, "accepted": True})

    def test_polling_without_a_task_is_counted_like_any_command(self) -> None:
        self.running()
        self.orch().exec_command(("tmux", "new-session", "-d"), task_id="task-1")
        for _ in range(4):
            payload, code = self.orch().exec_command(("ls",), polling=True)
        self.assertEqual(payload["polling"], {"requested": True, "accepted": False})
        self.assertEqual((code, payload["guard"]["rule"]), (6, "identical_commands"))

    def test_polling_before_the_task_ran_anything_is_not_accepted(self) -> None:
        self.running()
        payload, _ = self.orch().exec_command(("ls",), task_id="task-1", polling=True)
        self.assertFalse(payload["polling"]["accepted"])

    def test_polling_is_capped_and_then_a_human_is_asked(self) -> None:
        self.overrides = {"limits": {"max_polling_commands": 3}}
        self.running()
        self.orch().exec_command(("tmux", "new-session", "-d"), task_id="task-1")
        actions = []
        for _ in range(4):
            payload, _ = self.orch().exec_command(("ls",), task_id="task-1", polling=True)
            actions.append((payload["guard"]["action"], payload["guard"]["rule"]))
        self.assertEqual(actions[2], ("continue", "none"))
        self.assertEqual(actions[3], ("ask_human", "polling_cap"))
        with self.assertRaises(GuardTripped):
            self.orch().exec_command(("ls",), task_id="task-1", polling=True)

    def test_guard_trip_sets_exit_six_even_when_the_command_passed(self) -> None:
        self.running()
        codes = [self.orch().exec_command(("ls",))[1] for _ in range(4)]
        self.assertEqual(codes, [0, 0, 0, 6])


class CheckTests(OrchestratorCase):
    def running(self) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start()
        self.run_task()

    def test_passing_checks_store_report_evidence_and_a_fingerprinted_guard_event(self) -> None:
        self.running()
        self.runner.porcelain = " M a.py\n"
        out = self.orch().check_task("task-1")
        self.assertTrue(out["all_met"])
        self.assertEqual(out["report"]["checks"][0]["state"], "passed")
        expected = f"wev task record task-1 --status verified --summary <text> --run {RUN_ID}"
        self.assertEqual(out["next_step"], expected)
        state = self.state()
        record = state.verifications[-1]
        self.assertEqual((record.task_id, record.all_met), ("task-1", True))
        self.assertEqual(record.checks[0].argv, TESTS)
        self.assertGreater(record.at, state.tasks["task-1"].started_at)
        event = next(
            dict(e) for e in reversed(state.guard_events) if dict(e)["kind"] == "verification"
        )
        self.assertEqual((event["kind"], event["passed"]), ("verification", True))
        self.assertEqual(event["state_fingerprint"], record.fingerprint)
        self.assertEqual(len(record.fingerprint), 64)
        self.assertEqual(state.commands[-1].argv, TESTS)
        self.assertEqual(state.evidence[-1].evidence.label.value, "tested")
        self.assertEqual(state.phase.value, "verify")

    def test_fingerprint_follows_the_working_tree(self) -> None:
        first = tree_fingerprint(self.runner, str(self.root))
        self.runner.diff = "+ change"
        self.assertNotEqual(tree_fingerprint(self.runner, str(self.root)), first)
        self.runner.is_repo = False
        self.assertTrue(tree_fingerprint(self.runner, str(self.root)).startswith(FS_PREFIX))

    def test_failing_check_is_reported_and_later_checks_are_listed_as_not_run(self) -> None:
        self.start()
        self.set_plan(
            {"id": "a", "acceptance_criteria": ["works"], "checks": ["ruff check .", "make test"]}
        )
        self.run_task("a")
        self.runner.on(("ruff", "check", "."), exit_code=1)
        out = self.orch().check_task("a")
        self.assertFalse(out["all_met"])
        self.assertEqual(out["report"]["criteria"][0]["status"], "unmet")
        self.assertEqual(self.state().verifications[-1].unexecuted_checks, ("make test",))
        self.assertEqual(self.runner.calls.count(TESTS), 1, "only the baseline ran it")
        self.assertEqual(out["next_step"], f"wev task check a --run {RUN_ID}")
        self.orch().check_task("a", stop_on_failure=False)
        self.assertEqual(self.runner.calls.count(TESTS), 2)

    def test_task_without_checks_stays_unverified_and_cannot_be_recorded(self) -> None:
        (self.root / "Makefile").unlink()
        self.start()
        self.set_plan({"id": "a"})
        self.run_task("a")
        out = self.orch().check_task("a")
        self.assertFalse(out["all_met"])
        self.assertEqual(out["report"]["criteria"][0]["status"], "unverified")
        with self.assertRaises(ValidationError) as caught:
            self.orch().record_task("a", TaskStatus.VERIFIED, "trust me")
        self.assertEqual(caught.exception.code, "verification_required")

    def test_a_task_that_never_started_cannot_be_checked(self) -> None:
        self.start()
        self.orch().next_tasks()
        with self.assertRaises(ValidationError) as caught:
            self.orch().check_task("task-1")
        self.assertEqual(caught.exception.code, "task_not_started")
        with self.assertRaises(NotFound):
            self.orch().check_task("ghost")

    def test_check_that_needs_approval_is_refused_and_an_approval_is_requested(self) -> None:
        self.start()
        self.set_plan(
            {"id": "a", "acceptance_criteria": ["published"], "checks": ["git push origin main"]}
        )
        self.run_task("a")
        out = self.orch().check_task("a")
        self.assertEqual(out["report"]["checks"][0]["state"], "refused")
        self.assertEqual(self.state().pending_approvals, tuple(out["pending_approvals"]))
        self.assertEqual(len(out["pending_approvals"]), 1)
        self.assertEqual(self.status_of("a"), TaskStatus.RUNNING)
