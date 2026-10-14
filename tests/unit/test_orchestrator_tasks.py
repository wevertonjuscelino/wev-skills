from __future__ import annotations

from tests.unit._orchestrator_helpers import RUN_ID, OrchestratorCase
from wev_skills.core.contracts import Mode, TaskContract, TaskStatus
from wev_skills.core.errors import (
    ApprovalRequired,
    GuardTripped,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from wev_skills.guards.events import budget_event
from wev_skills.state.model import with_guard_event

FAILING = ("false",)


class NextTaskTests(OrchestratorCase):
    def test_direct_run_synthesizes_one_task_with_a_full_contract(self) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start()
        out = self.orch().next_tasks()
        contract = TaskContract.from_dict(out["tasks"][0])
        self.assertEqual((contract.task_id, contract.agent_id), ("task-1", "builder"))
        self.assertEqual(contract.objective, "Add a greeting")
        self.assertIn("Add a greeting", contract.context)
        self.assertEqual(contract.checks, ("make test",))
        self.assertEqual(len(contract.acceptance_criteria), 1)
        self.assertEqual(contract.permissions, ("Read", "Edit", "Bash"))
        self.assertEqual((contract.model, contract.risk.value), ("claude-sonnet-5-5", "low"))
        self.assertIn(".wev", contract.exclusions)
        self.assertEqual(len(contract.constraints), 3)
        self.assertTrue(contract.response_format)
        self.assertEqual(out["next_step"], f"wev task start task-1 --run {RUN_ID}")
        self.assertEqual(self.status_of("task-1"), TaskStatus.READY)
        self.assertIn("plan.synthesized", self.audit_types())

    def test_plan_mode_refuses_and_says_the_plan_is_ready_for_review(self) -> None:
        self.start(mode=Mode.PLAN)
        self.set_plan({"id": "a"})
        for call in (self.orch().next_tasks, lambda: self.orch().start_task("a")):
            with self.assertRaises(PermissionDenied) as caught:
                call()
            self.assertEqual(caught.exception.code, "plan_mode")
            self.assertIn("ready for review", caught.exception.message)
        self.assertEqual(self.status_of("a"), TaskStatus.PENDING)

    def test_a_strategy_that_needs_a_plan_gets_no_synthesized_task(self) -> None:
        self.start(files_touched_estimate=8)
        with self.assertRaises(ValidationError) as caught:
            self.orch().next_tasks()
        self.assertEqual(caught.exception.code, "plan_required")
        self.assertIn("wev plan set", caught.exception.details["next_step"])

    def test_dependencies_must_be_verified_first(self) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start()
        self.set_plan({"id": "a"}, {"id": "b", "depends_on": ["a"]})
        out = self.orch().next_tasks()
        self.assertEqual([t["task_id"] for t in out["tasks"]], ["a"])
        self.assertIn("a", out["deferred"][0]["reason"])
        with self.assertRaises(ValidationError):
            self.orch().start_task("b")
        self.orch().start_task("a")
        self.verify("a")
        self.assertEqual([t["task_id"] for t in self.orch().next_tasks()["tasks"]], ["b"])

    def test_a_free_slot_does_not_let_a_task_skip_its_dependencies(self) -> None:
        self.start(independent_subtasks=3)
        self.set_plan(
            {"id": "a", "files": ["a.py"]}, {"id": "b", "files": ["b.py"], "depends_on": ["a"]}
        )
        out = self.orch().next_tasks()
        self.assertEqual([t["task_id"] for t in out["tasks"]], ["a"])
        self.assertIn("dependencies that are not verified: a", out["deferred"][0]["reason"])

    def test_overlapping_files_are_never_offered_together(self) -> None:
        self.start(independent_subtasks=3)
        self.set_plan(
            {"id": "a", "files": ["src/app.py"]},
            {"id": "b", "files": ["src/app.py", "docs/x.md"]},
            {"id": "c", "files": ["tests/test_app.py"]},
            {"id": "d", "files": ["src"]},
        )
        out = self.orch().next_tasks()
        self.assertEqual([t["task_id"] for t in out["tasks"]], ["a", "c"])
        self.assertEqual({d["task_id"] for d in out["deferred"]}, {"b", "d"})
        self.orch().start_task("a")
        with self.assertRaises(ValidationError) as caught:
            self.orch().start_task("b")
        self.assertEqual(caught.exception.code, "task_not_startable")

    def test_a_task_without_declared_files_runs_alone(self) -> None:
        self.start(independent_subtasks=2)
        self.set_plan({"id": "a"}, {"id": "b", "files": ["b.py"]})
        self.assertEqual([t["task_id"] for t in self.orch().next_tasks()["tasks"]], ["a"])

    def test_no_more_than_max_parallel_including_running_tasks(self) -> None:
        self.overrides = {"limits": {"max_parallel": 2}}
        self.start(independent_subtasks=3)
        self.set_plan(*({"id": name, "files": [f"{name}.py"]} for name in "abc"))
        self.assertEqual([t["task_id"] for t in self.orch().next_tasks()["tasks"]], ["a", "b"])
        self.orch().start_task("a")
        self.orch().start_task("b")
        self.assertEqual(self.orch().next_tasks()["tasks"], [])
        with self.assertRaises(ValidationError):
            self.orch().start_task("c")

    def test_serial_strategy_offers_one_task_at_a_time(self) -> None:
        self.start()
        self.set_plan({"id": "a", "files": ["a.py"]}, {"id": "b", "files": ["b.py"]})
        self.assertEqual([t["task_id"] for t in self.orch().next_tasks()["tasks"]], ["a"])


class ApprovalTests(OrchestratorCase):
    def gated(self) -> None:
        self.start(touches_production=True)
        self.set_plan({"id": "a"})

    def test_gated_task_blocks_until_a_human_grants_and_the_grant_is_single_use(self) -> None:
        self.gated()
        with self.assertRaises(ApprovalRequired) as caught:
            self.orch().next_tasks()
        approval = caught.exception.details["approval_ids"][0]
        self.assertEqual(self.state().pending_approvals, (approval,))
        step = caught.exception.details["next_step"]
        self.assertIn("ask the human operator", step)
        self.assertIn(f"'wev approval grant {approval}' themselves in their own terminal", step)
        for text in (step, caught.exception.message, self.orch().status()["next_step"]):
            self.assertNotIn("--i-am-human", text)
        self.assertEqual(self.orch().status()["next_step"], step)
        with self.assertRaises(ApprovalRequired):
            self.orch().next_tasks()
        with self.assertRaises(ApprovalRequired):
            self.orch().start_task("a")
        self.assertEqual(len(self.services().approvals.list()), 1)
        self.grant(approval)
        self.assertEqual([t["task_id"] for t in self.orch().next_tasks()["tasks"]], ["a"])
        self.orch().start_task("a")
        self.assertEqual(self.status_of("a"), TaskStatus.RUNNING)
        self.assertEqual(self.state().pending_approvals, ())
        self.assertEqual(self.services().approvals.get(approval).status.value, "consumed")

    def test_high_risk_task_in_a_low_risk_run_needs_approval_too(self) -> None:
        self.start(independent_subtasks=2)
        self.set_plan(
            {"id": "safe", "files": ["a.py"]}, {"id": "danger", "files": ["b.py"], "risk": "high"}
        )
        out = self.orch().next_tasks()
        self.assertEqual([t["task_id"] for t in out["tasks"]], ["safe"])
        self.assertEqual(len(out["awaiting_approval"]), 1)

    def test_denied_approval_defers_the_task_without_asking_again(self) -> None:
        self.gated()
        with self.assertRaises(ApprovalRequired) as caught:
            self.orch().next_tasks()
        self.services().approvals.deny(caught.exception.details["approval_ids"][0], "ana")
        out = self.orch().next_tasks()
        self.assertEqual((out["tasks"], out["awaiting_approval"]), ([], []))
        self.assertIn("denied", out["deferred"][0]["reason"])


class StartTaskTests(OrchestratorCase):
    def test_start_records_attempt_agent_model_and_a_handoff_event(self) -> None:
        self.start()
        self.orch().next_tasks()
        out = self.orch().start_task("task-1")
        self.assertEqual((out["status"], out["attempt"]), ("running", 1))
        self.assertEqual((out["agent_id"], out["model"]), ("builder", "claude-sonnet-5-5"))
        self.assertEqual(out["contract"]["task_id"], "task-1")
        state = self.state()
        self.assertTrue(state.tasks["task-1"].started_at)
        event = next(dict(e) for e in state.guard_events if dict(e)["kind"] == "agent_handoff")
        self.assertEqual(event["to_agent"], "builder")
        self.assertEqual(dict(state.guard_events[-1])["kind"], "progress")
        self.assertIn("attempt 1", state.decisions[-1].decision)
        self.assertIn("task.started", self.audit_types())

    def test_unknown_or_already_running_tasks_are_refused(self) -> None:
        self.start()
        self.run_task()
        with self.assertRaises(NotFound):
            self.orch().start_task("ghost")
        with self.assertRaises(ValidationError):
            self.orch().start_task("task-1")


class GuardRefusalTests(OrchestratorCase):
    def test_repeating_a_failing_command_ends_in_ask_human_and_next_refuses(self) -> None:
        self.start()
        self.run_task()
        self.runner.on(FAILING, exit_code=1)
        actions = [self.orch().exec_command(FAILING)[0]["guard"]["action"] for _ in range(5)]
        self.assertEqual(actions[:2], ["continue", "continue"])
        self.assertEqual(actions[3], "change_strategy")
        self.assertEqual(actions[4], "ask_human")
        with self.assertRaises(GuardTripped) as caught:
            self.orch().next_tasks()
        self.assertEqual(caught.exception.details["verdict"]["rule"], "ignored_loop")
        self.assertEqual(self.orch().status()["next_step"], f"wev guard check --run {RUN_ID}")

    def test_an_advisory_verdict_does_not_refuse(self) -> None:
        self.start()
        self.run_task()
        self.runner.on(FAILING, exit_code=1)
        for _ in range(3):
            self.orch().exec_command(FAILING)
        self.assertEqual(self.orch().guard_check().action.value, "change_strategy")
        self.assertEqual(self.orch().next_tasks()["tasks"], [])

    def test_budget_overrun_refuses_next_and_start(self) -> None:
        self.start()
        self.orch().next_tasks()
        event = budget_event("task-1", 1.0, 500.0).to_dict()
        self.orch().store.update(lambda state: with_guard_event(state, event))
        for call in (self.orch().next_tasks, lambda: self.orch().start_task("task-1")):
            with self.assertRaises(GuardTripped) as caught:
                call()
            self.assertEqual(caught.exception.details["verdict"]["action"], "stop")
