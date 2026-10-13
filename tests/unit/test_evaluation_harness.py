from __future__ import annotations

import itertools
import os
import unittest
from dataclasses import replace
from unittest import mock

from wev_skills.core.contracts import TaskStatus
from wev_skills.core.errors import ValidationError
from wev_skills.evaluation import harness
from wev_skills.evaluation.configs import HarnessConfig, load_configs
from wev_skills.evaluation.metrics import Counts, EvalReport, RunResult, SubtaskOutcome, add_counts
from wev_skills.evaluation.report import render_json
from wev_skills.evaluation.tasks import CONFIGS_FILE, EVALS_DIR, TASKS_SUBDIR, Subtask, load_tasks

GRAPH = (
    Subtask("tests", ("api", "cli"), ("tests/test_x.py",)),
    Subtask("model", (), ("src/model.py",)),
    Subtask("api", ("model",), ("src/api.py", "src/registry.py")),
    Subtask("cli", ("model",), ("src/cli.py", "src/registry.py")),
    Subtask("docs", (), ("docs/x.md",)),
    Subtask("lint", (), ("src/model.py",)),
)
DURATIONS = {"tests": 3, "model": 4, "api": 5, "cli": 2, "docs": 7, "lint": 1}


def fake_execute(
    failing: frozenset[str] = frozenset(), log: list[str] | None = None
) -> harness.Execute:
    def execute(sub: Subtask) -> SubtaskOutcome:
        if log is not None:
            log.append(sub.id)
        status = TaskStatus.FAILED if sub.id in failing else TaskStatus.VERIFIED
        return SubtaskOutcome(sub.id, status, attempts=1, duration_units=DURATIONS[sub.id])

    return execute


def overlaps(first: SubtaskOutcome, second: SubtaskOutcome) -> bool:
    return first.start < second.end and second.start < first.end


class ScheduleTests(unittest.TestCase):
    def assert_safe(self, outcomes: tuple[SubtaskOutcome, ...], max_parallel: int) -> None:
        by_id = {outcome.subtask_id: outcome for outcome in outcomes}
        subs = {sub.id: sub for sub in GRAPH}
        for first, second in itertools.combinations(outcomes, 2):
            shared = set(subs[first.subtask_id].files) & set(subs[second.subtask_id].files)
            if shared:
                self.assertFalse(overlaps(first, second), (first, second, shared))
        for outcome in outcomes:
            for dep in subs[outcome.subtask_id].depends_on:
                self.assertGreaterEqual(outcome.start, by_id[dep].end, (outcome, dep))
        for moment in range(max(o.end for o in outcomes)):
            active = [o for o in outcomes if o.start <= moment < o.end]
            self.assertLessEqual(len(active), max_parallel, moment)

    def test_no_shared_file_or_unmet_dependency_runs_concurrently(self) -> None:
        for max_parallel in (1, 2, 3, 6):
            with self.subTest(max_parallel=max_parallel):
                outcomes = harness.schedule(GRAPH, max_parallel, fake_execute())
                self.assertEqual([o.subtask_id for o in outcomes], [s.id for s in GRAPH])
                self.assertTrue(all(o.end - o.start == DURATIONS[o.subtask_id] for o in outcomes))
                self.assert_safe(outcomes, max_parallel)

    def test_sequential_makespan_is_the_sum_and_parallel_is_shorter(self) -> None:
        sequential = harness.schedule(GRAPH, 1, fake_execute(), start=1)
        self.assertEqual(max(o.end for o in sequential), 1 + sum(DURATIONS.values()))
        parallel = harness.schedule(GRAPH, 3, fake_execute(), start=1)
        self.assertEqual(max(o.end for o in parallel), 1 + 4 + 5 + 2 + 3)
        self.assertEqual(min(o.start for o in parallel), 1)

    def test_api_and_cli_share_a_file_and_never_overlap_even_with_free_slots(self) -> None:
        by_id = {o.subtask_id: o for o in harness.schedule(GRAPH, 6, fake_execute())}
        self.assertFalse(overlaps(by_id["api"], by_id["cli"]))
        self.assertFalse(overlaps(by_id["model"], by_id["lint"]))
        self.assertTrue(overlaps(by_id["model"], by_id["docs"]))

    def test_failed_dependency_means_dependents_are_not_executed(self) -> None:
        log: list[str] = []
        outcomes = harness.schedule(GRAPH, 2, fake_execute(frozenset({"model"}), log))
        status = {o.subtask_id: (o.status, o.failure) for o in outcomes}
        skipped = (TaskStatus.NOT_EXECUTED, harness.FAILURE_DEPENDENCY_FAILED)
        self.assertEqual((status["api"], status["cli"], status["tests"]), (skipped,) * 3)
        self.assertEqual(sorted(log), ["docs", "lint", "model"])

    def test_failure_propagates_down_a_chain_with_nothing_else_running(self) -> None:
        chain = (Subtask("model"), Subtask("api", ("model",)), Subtask("tests", ("api",)))
        outcomes = harness.schedule(chain, 1, fake_execute(frozenset({"model"})))
        self.assertEqual(
            [o.status for o in outcomes],
            [TaskStatus.FAILED, TaskStatus.NOT_EXECUTED, TaskStatus.NOT_EXECUTED],
        )
        self.assertEqual([o.end for o in outcomes], [4, 4, 4])

    def test_invalid_schedules_raise(self) -> None:
        with self.assertRaises(ValidationError):
            harness.schedule(GRAPH, 0, fake_execute())
        with self.assertRaises(ValidationError) as caught:
            harness.schedule((Subtask("tests", ("ghost",)),), 1, fake_execute())
        self.assertEqual(caught.exception.code, "unschedulable")

    def test_without_a_plan_declaration_order_blocks_out_of_order_subtasks(self) -> None:
        log: list[str] = []
        outcomes = harness.run_in_order(GRAPH, fake_execute(log=log))
        self.assertEqual(outcomes[0].status, TaskStatus.BLOCKED)
        self.assertEqual(outcomes[0].failure, harness.FAILURE_DEPENDENCY_UNMET)
        self.assertEqual(log, ["model", "api", "cli", "docs", "lint"])
        self.assertEqual(max(o.end for o in outcomes), sum(DURATIONS.values()) - DURATIONS["tests"])


class ShippedRunTests(unittest.TestCase):
    report: EvalReport
    configs: tuple[HarnessConfig, ...]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = load_tasks(EVALS_DIR / TASKS_SUBDIR)
        cls.configs = load_configs(EVALS_DIR / CONFIGS_FILE)
        cls.report = harness.run(cls.tasks, cls.configs)

    def result(self, task_id: str, config_id: str) -> RunResult:
        return next(r for r in self.report.runs if (r.task_id, r.config_id) == (task_id, config_id))

    def subtask(self, task_id: str, config_id: str, subtask_id: str) -> tuple[str, str]:
        subs = self.result(task_id, config_id).subtasks
        found = next(s for s in subs if s.subtask_id == subtask_id)
        return found.status.value, found.failure

    def test_every_task_runs_under_every_config(self) -> None:
        self.assertEqual(len(self.report.runs), len(self.tasks) * len(self.configs))
        self.assertEqual(len(self.report.aggregates), len(self.configs))

    def test_two_runs_are_identical(self) -> None:
        again = harness.run(self.tasks, self.configs)
        self.assertEqual(again, self.report)
        self.assertEqual(render_json(again, "en"), render_json(self.report, "en"))

    def test_results_do_not_depend_on_the_ambient_language(self) -> None:
        with mock.patch.dict(os.environ, {"WEV_LANG": "pt-BR"}):
            self.assertEqual(harness.run(self.tasks, self.configs), self.report)

    def test_simple_fix_passes_everywhere(self) -> None:
        for config in self.configs:
            self.assertTrue(self.result("simple-fix", config.id).success, config.id)

    def test_loop_task_ends_with_a_guard_trip_and_is_a_failure(self) -> None:
        for config in self.configs:
            run = self.result("agent-loop", config.id)
            with self.subTest(config.id):
                self.assertFalse(run.success)
                self.assertEqual(run.counts.criteria_met, 0)
                if not config.guard_enabled:
                    self.assertEqual(run.counts.guard_trips, 0)
                    continue
                rules = {rc.rule for rc in run.counts.guard_trips_by_rule}
                self.assertTrue({"identical_commands", "handoff_cycle"} <= rules, rules)
                self.assertTrue(all(s.failure.startswith("guard:") for s in run.subtasks))
                self.assertEqual(run.counts.unexecuted_verifications, 3)

    def test_guard_bounds_the_loop_that_otherwise_runs_to_the_attempt_limit(self) -> None:
        guarded = self.result("agent-loop", "baseline").counts
        unguarded = self.result("agent-loop", "guard-off").counts
        self.assertLess(guarded.duration_units, unguarded.duration_units)
        self.assertLess(guarded.cost_units, unguarded.cost_units)

    def test_overflow_with_unmanaged_context_and_none_with_elision(self) -> None:
        unmanaged = self.result("context-overload", "context-none")
        self.assertEqual(unmanaged.counts.context_overflows, 1)
        self.assertFalse(unmanaged.success)
        self.assertEqual(
            self.subtask("context-overload", "context-none", "investigate"),
            ("failed", "context_overflow"),
        )
        elided = self.result("context-overload", "baseline")
        self.assertEqual(elided.counts.context_overflows, 0)
        self.assertGreater(elided.counts.items_elided, 0)
        self.assertTrue(elided.success)

    def test_aggressive_elision_and_summarization_lose_needed_items(self) -> None:
        aggressive = self.result("context-overload", "context-elide-aggressive")
        self.assertEqual(aggressive.counts.info_loss_failures, 1)
        self.assertEqual(
            self.subtask("context-overload", "context-elide-summarize", "handover"),
            ("failed", "info_loss"),
        )

    def test_only_summarization_fits_the_note_heavy_diagnosis(self) -> None:
        for config in self.configs:
            run = self.result("remote-diagnosis", config.id)
            expected = config.context_policy == "elide_and_summarize"
            self.assertEqual(run.success, expected, config.id)
            self.assertEqual(run.counts.context_overflows, 0 if expected else 1, config.id)
            polling_rules = {rc.rule for rc in run.counts.guard_trips_by_rule}
            self.assertNotIn("identical_commands", polling_rules)

    def test_planning_off_blocks_the_out_of_order_subtask(self) -> None:
        self.assertEqual(
            self.subtask("multi-file-feature", "planning-off", "tests"),
            ("blocked", "dependency_unmet"),
        )
        self.assertFalse(self.result("multi-file-feature", "planning-off").success)
        self.assertTrue(self.result("multi-file-feature", "baseline").success)
        self.assertFalse(self.result("simple-fix", "planning-auto").planned)
        self.assertTrue(self.result("multi-file-feature", "planning-auto").planned)

    def test_capability_profiles_change_the_plan_step_of_a_simple_task(self) -> None:
        economy = self.result("two-file-change", "profile-economy")
        premium = self.result("two-file-change", "profile-premium")
        self.assertEqual((economy.executor_tier, economy.planned), ("economy", True))
        self.assertEqual((premium.executor_tier, premium.planned), ("premium", False))
        self.assertTrue(economy.success and premium.success)
        self.assertFalse(self.result("simple-fix", "profile-economy").planned)
        self.assertTrue(self.result("multi-file-feature", "profile-premium").planned)

    def test_tool_profiles_are_recorded_per_run(self) -> None:
        lean = ("Read", "Edit", "Bash")
        baseline = self.result("two-file-change", "baseline")
        self.assertEqual(baseline.tool_profile, "structured")
        self.assertEqual(len(baseline.tools), 6)
        self.assertEqual(self.result("two-file-change", "tools-lean").tools, lean)
        self.assertEqual(self.result("two-file-change", "profile-premium").tools, lean)
        self.assertEqual(self.result("two-file-change", "profile-economy").tools, baseline.tools)
        lean_counts = self.result("two-file-change", "tools-lean").counts
        estimate = baseline.counts.estimated_tool_tokens_selected
        self.assertLess(lean_counts.estimated_tool_tokens_selected, estimate)
        same = replace(lean_counts, estimated_tool_tokens_selected=estimate)
        self.assertEqual(same, baseline.counts, "a profile lists tools; the script is unchanged")

    def test_parallel_changes_duration_only(self) -> None:
        for task_id in ("multi-file-feature", "agent-loop"):
            sequential = self.result(task_id, "baseline").counts
            parallel = self.result(task_id, "parallel-3").counts
            self.assertLess(parallel.duration_units, sequential.duration_units, task_id)
            self.assertEqual(parallel.cost_units, sequential.cost_units, task_id)
            self.assertEqual(parallel.attempts, sequential.attempts, task_id)

    def test_attempt_limits(self) -> None:
        expected = {"attempts-1": False, "attempts-2": True, "baseline": True, "attempts-4": True}
        for config_id, success in expected.items():
            self.assertEqual(self.result("failing-test", config_id).success, success, config_id)
        gated = {"attempts-1": False, "attempts-2": False, "baseline": True, "attempts-4": True}
        for config_id, success in gated.items():
            run = self.result("multi-file-feature", config_id)
            self.assertEqual(run.success, success, config_id)

    def test_routing(self) -> None:
        policy = self.result("multi-file-feature", "baseline")
        standard = self.result("multi-file-feature", "routing-fixed-standard")
        premium = self.result("multi-file-feature", "routing-fixed-premium")
        self.assertEqual((policy.success, policy.counts.tier_escalations), (True, 1))
        self.assertEqual((standard.success, standard.counts.tier_escalations), (False, 0))
        self.assertEqual(
            self.subtask("multi-file-feature", "routing-fixed-standard", "tests"),
            ("not_executed", "dependency_failed"),
        )
        self.assertTrue(premium.success)
        self.assertGreater(premium.counts.cost_units, policy.counts.cost_units)

    def test_aggregates_are_plain_sums_of_their_runs(self) -> None:
        for agg in self.report.aggregates:
            runs = [r for r in self.report.runs if r.config_id == agg.config_id]
            total = Counts()
            for run in runs:
                total = add_counts(total, run.counts)
            self.assertEqual(agg.counts, total)
            self.assertEqual(agg.successes, sum(1 for r in runs if r.success))
            self.assertEqual(agg.success_rate, round(agg.successes / len(runs), 4))
            by_rule = sum(rc.count for rc in agg.counts.guard_trips_by_rule)
            self.assertEqual(agg.counts.guard_trips, by_rule)


class InputTests(unittest.TestCase):
    def test_empty_or_duplicate_inputs_are_rejected(self) -> None:
        tasks = load_tasks(EVALS_DIR / TASKS_SUBDIR)
        configs = load_configs(EVALS_DIR / CONFIGS_FILE)
        for bad_tasks, bad_configs in (((), configs), (tasks, ()), (tasks, (configs[0],) * 2)):
            with self.assertRaises(ValidationError) as caught:
                harness.run(bad_tasks, bad_configs)
            self.assertEqual(caught.exception.code, "invalid_eval_input")


if __name__ == "__main__":
    unittest.main()
