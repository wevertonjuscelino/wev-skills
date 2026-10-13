from __future__ import annotations

import json

from tests.unit._orchestrator_helpers import RUN_ID, OrchestratorCase
from wev_skills.core.contracts import Mode, TaskSignals, TaskStatus
from wev_skills.core.errors import NotFound, StateConflict, ValidationError
from wev_skills.state.model import Phase

SECRET = "example_" + "Hunter2" * 3


class StartTests(OrchestratorCase):
    def test_direct_run_records_snapshot_discovery_classification_and_strategy(self) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        out = self.start()
        state = self.state()
        self.assertEqual(out["run_id"], RUN_ID)
        self.assertEqual(out["classification"]["risk"], "low")
        self.assertEqual(out["strategy"]["flow"], "direct")
        self.assertEqual(
            out["discovery"]["checks"][0],
            {"command": "make test", "source": "Makefile", "kind": "test"},
        )
        self.assertEqual(out["next_step"], f"wev task next --run {RUN_ID}")
        self.assertEqual((state.repo.head, state.repo.branch), ("abc123", "main"))
        self.assertEqual(
            [d.phase for d in state.decisions],
            [Phase.REQUEST, Phase.DISCOVER, Phase.CLASSIFY, Phase.DECIDE],
        )
        self.assertTrue(all(d.reasons for d in state.decisions))
        self.assertEqual((state.phase, state.next_step), (Phase.EXECUTE, out["next_step"]))
        self.assertIn("run.started", self.audit_types())

    def test_strategy_follows_the_configured_executor_tier(self) -> None:
        self.overrides = {"harness": {"executor_tier": "economy"}}
        out = self.start(files_touched_estimate=2)
        self.assertEqual(
            (out["strategy"]["flow"], out["strategy"]["needs_plan"]), ("planned", True)
        )
        self.assertIn("Executor tier economy", " ".join(out["strategy"]["reasons"]))
        self.assertEqual(out["next_step"], f"wev plan set --file plan.json --run {RUN_ID}")
        recorded = self.state().decisions[-1]
        self.assertIn("Executor tier economy, planning auto", " ".join(recorded.reasons))

    def test_auto_executor_tier_is_the_tier_the_router_picks(self) -> None:
        trivial = self.start()
        self.assertIn("Executor tier economy", " ".join(trivial["strategy"]["reasons"]))
        self.assertEqual(trivial["strategy"]["flow"], "direct")
        self.orch().finish()
        simple = self.orch("run-2").start("x", Mode.AUTO, TaskSignals("x", 2), "run-2")
        self.assertIn("Executor tier standard", " ".join(simple["strategy"]["reasons"]))
        self.assertEqual(simple["strategy"]["flow"], "direct")
        self.orch("run-2").finish()
        big = self.orch("run-3").start("x", Mode.AUTO, TaskSignals("x", 20), "run-3")
        self.assertIn("Executor tier premium", " ".join(big["strategy"]["reasons"]))
        self.assertEqual(big["strategy"]["flow"], "planned")

    def test_planning_policy_comes_from_the_configuration(self) -> None:
        self.overrides = {"harness": {"planning": "always"}}
        self.assertTrue(self.start()["strategy"]["needs_plan"])
        self.orch().finish()
        self.overrides = {"harness": {"planning": "never"}}
        out = self.orch("run-2").start("x", Mode.AUTO, TaskSignals("x", 8), "run-2")
        self.assertFalse(out["strategy"]["needs_plan"])
        self.assertEqual(out["next_step"], "wev task next --run run-2")

    def test_run_that_needs_a_plan_points_at_plan_set(self) -> None:
        out = self.start(touches_production=True)
        self.assertEqual(
            (out["strategy"]["flow"], out["strategy"]["needs_approval"]), ("gated", True)
        )
        self.assertEqual(out["next_step"], f"wev plan set --file plan.json --run {RUN_ID}")
        self.assertEqual(self.state().phase, Phase.PLAN)

    def test_plan_mode_never_points_at_execution(self) -> None:
        out = self.start(mode=Mode.PLAN)
        self.assertEqual(out["next_step"], f"wev plan set --file plan.json --run {RUN_ID}")

    def test_resume_is_not_a_start_mode_and_creates_nothing(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            self.orch().start("x", Mode.RESUME, TaskSignals("x"), RUN_ID)
        self.assertEqual(caught.exception.code, "invalid_mode")
        self.assertFalse(self.orch().store.exists())

    def test_invalid_signals_create_no_run(self) -> None:
        with self.assertRaises(ValidationError):
            self.start(files_touched_estimate=-1)
        self.assertFalse(self.orch().store.exists())

    def test_starting_the_same_run_twice_is_a_conflict(self) -> None:
        self.start()
        with self.assertRaises(StateConflict):
            self.start()

    def test_objective_is_redacted_in_state_and_audit(self) -> None:
        self.start(objective=f"Rotate the key, password={SECRET}")
        services = self.services()
        stored = json.dumps(self.state().to_dict()) + json.dumps(services.audit.read())
        self.assertNotIn(SECRET, stored)
        self.assertIn("[REDACTED]", self.state().objective)

    def test_outside_a_repository_the_run_still_starts(self) -> None:
        self.runner.is_repo = False
        self.start()
        self.assertIsNone(self.state().repo)


class StatusTests(OrchestratorCase):
    def test_status_lists_tasks_approvals_blockers_guard_and_next_step(self) -> None:
        self.start()
        self.set_plan({"id": "a", "files": ["a.py"]}, {"id": "b", "depends_on": ["a"]})
        status = self.orch().status()
        self.assertEqual(
            [(t["id"], t["status"]) for t in status["tasks"]], [("a", "pending"), ("b", "pending")]
        )
        self.assertEqual(status["tasks"][0]["agent_id"], "builder")
        self.assertEqual((status["pending_approvals"], status["blockers"]), ([], []))
        self.assertEqual(status["guard"]["action"], "continue")
        self.assertEqual(status["next_step"], f"wev task next --run {RUN_ID}")

    def test_status_does_not_change_the_state(self) -> None:
        self.start()
        before = self.state().revision
        self.orch().status()
        self.assertEqual(self.state().revision, before)

    def test_unknown_run_is_not_found(self) -> None:
        with self.assertRaises(NotFound):
            self.orch("missing").status()


class PlanTests(OrchestratorCase):
    def test_each_task_gets_an_agent_and_a_model_recorded_as_decisions(self) -> None:
        self.start(files_touched_estimate=4)
        out = self.set_plan({"id": "a"}, {"id": "b", "agent_hint": "reviewer"})
        rows = {row["id"]: row for row in out["tasks"]}
        self.assertEqual((rows["a"]["agent_id"], rows["b"]["agent_id"]), ("builder", "reviewer"))
        self.assertEqual(rows["a"]["model"], "claude-sonnet-5-5")
        decisions = [(d.decision, d.source) for d in self.state().decisions]
        self.assertIn(("Task a: agent builder.", "local-policy"), decisions)
        self.assertIn(("Task b: agent reviewer.", "agent_hint"), decisions)
        self.assertIn(
            ("Task a: model claude-sonnet-5-5 (tier standard).", "model-router"), decisions
        )
        self.assertEqual(self.orch().show_plan()["plan"]["tasks"][0]["id"], "a")

    def test_read_only_agents_are_not_routed_to_in_an_executing_run(self) -> None:
        self.start()
        out = self.set_plan({"id": "a", "title": "review the review of reviews"})
        self.assertEqual(out["tasks"][0]["agent_id"], "builder")

    def test_task_risk_above_the_run_raises_the_effective_risk_and_the_model(self) -> None:
        self.start()
        out = self.set_plan({"id": "safe"}, {"id": "danger", "risk": "high"})
        rows = {row["id"]: row for row in out["tasks"]}
        self.assertEqual((rows["safe"]["risk"], rows["danger"]["risk"]), ("low", "high"))
        self.assertEqual(rows["danger"]["model"], "claude-opus-5-5")
        texts = [d.decision for d in self.state().decisions]
        self.assertIn("Task danger: its own risk raises the effective risk to high.", texts)

    def test_invalid_plans_are_rejected_and_nothing_is_stored(self) -> None:
        self.start()
        cases = (
            [{"id": "a", "depends_on": ["ghost"]}],
            [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}],
            [{"id": "a"}, {"id": "a"}],
            [{"id": "a", "bogus": 1}],
            [],
        )
        for tasks in cases:
            with self.subTest(tasks=tasks), self.assertRaises(ValidationError) as caught:
                self.set_plan(*tasks)
            self.assertEqual(caught.exception.code, "invalid_plan")
        self.assertIsNone(self.state().plan)

    def test_plan_is_allowed_in_a_direct_run_and_may_be_replaced_before_work_starts(self) -> None:
        self.start()
        self.set_plan({"id": "a"}, {"id": "b"})
        self.set_plan({"id": "c"})
        self.assertEqual(list(self.state().tasks), ["c"])

    def test_replacing_a_plan_may_not_drop_a_task_that_already_ran(self) -> None:
        self.start()
        self.set_plan({"id": "a"})
        self.run_task("a")
        with self.assertRaises(ValidationError) as caught:
            self.set_plan({"id": "c"})
        self.assertEqual(caught.exception.code, "plan_drops_tasks")

    def test_secret_in_a_plan_is_redacted(self) -> None:
        self.start()
        self.set_plan({"id": "a", "objective": f"use token={SECRET}"})
        self.assertNotIn(SECRET, json.dumps(self.state().to_dict()))


class ResumeTests(OrchestratorCase):
    def running(self) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start()
        self.run_task()

    def test_running_task_needs_reverification_and_old_checks_no_longer_count(self) -> None:
        self.running()
        self.orch().check_task("task-1")
        out = self.orch().resume()
        self.assertEqual(out["needs_reverification"], ["task-1"])
        self.assertTrue(out["drift"]["drifted"])
        self.assertEqual(out["next_step"], f"wev task check task-1 --run {RUN_ID}")
        self.assertEqual(self.status_of("task-1"), TaskStatus.RUNNING)
        with self.assertRaises(ValidationError) as caught:
            self.orch().record_task("task-1", TaskStatus.VERIFIED, "it was done before")
        self.assertEqual(caught.exception.code, "verification_required")
        self.verify()
        self.assertEqual(self.status_of("task-1"), TaskStatus.VERIFIED)

    def test_drift_is_recorded_as_a_decision_and_the_snapshot_is_refreshed(self) -> None:
        self.running()
        self.runner.head, self.runner.porcelain = "def456", " M src/a.py\n"
        out = self.orch().resume()
        self.assertTrue(out["drift"]["head_changed"])
        self.assertEqual(out["drift"]["new_dirty_files"], ["src/a.py"])
        decision = self.state().decisions[-1]
        self.assertEqual(decision.source, "resume")
        self.assertTrue(any("HEAD changed" in reason for reason in decision.reasons))
        self.assertEqual(self.state().repo.head, "def456")
        self.assertIn("run.resumed", self.audit_types())

    def test_drift_notes_and_the_snapshot_are_redacted_before_they_are_stored(self) -> None:
        self.start()
        self.runner.branch = f"feature/password={SECRET}"
        self.orch().resume()
        state = self.state()
        self.assertNotIn(SECRET, json.dumps(state.to_dict()))
        self.assertTrue(any("[REDACTED]" in reason for reason in state.decisions[-1].reasons))
        self.assertNotIn(SECRET, json.dumps(self.services().audit.read()))

    def test_no_drift_is_said_plainly(self) -> None:
        self.start()
        out = self.orch().resume()
        self.assertFalse(out["drift"]["drifted"])
        self.assertEqual(
            self.state().decisions[-1].reasons, ("The repository matches the recorded run.",)
        )


class GuardCheckTests(OrchestratorCase):
    def test_unresolved_dependencies_of_a_task_stop(self) -> None:
        self.start()
        self.set_plan({"id": "a"}, {"id": "b", "depends_on": ["a"]})
        self.assertEqual(self.orch().guard_check().action.value, "continue")
        verdict = self.orch().guard_check("b")
        self.assertEqual((verdict.action.value, verdict.rule), ("stop", "unresolved_dependencies"))
        with self.assertRaises(NotFound):
            self.orch().guard_check("ghost")
