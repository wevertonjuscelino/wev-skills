"""Scripted evaluation of per-task tool selection: estimates and the miss-and-recover path."""

from __future__ import annotations

import unittest
from typing import Any

from wev_skills.core.contracts import TaskStatus
from wev_skills.core.errors import ValidationError
from wev_skills.evaluation import harness, report
from wev_skills.evaluation.configs import HarnessConfig, load_configs
from wev_skills.evaluation.metrics import EvalReport, RunResult
from wev_skills.evaluation.tasks import (
    CONFIGS_FILE,
    EVALS_DIR,
    TASKS_SUBDIR,
    load_tasks,
    parse_task,
)
from wev_skills.tools.registry import ToolRegistry

TASK = "tool-selection-miss"
OFF, LOCAL = "tools-selection-off", "tools-selection-local"
ALL = ("Read", "Grep", "Glob", "Edit", "Write", "Bash")


def tokens(*names: str) -> int:
    return sum(ToolRegistry.default().get(name).approx_definition_tokens for name in names)


def task_data(**step: Any) -> dict[str, Any]:
    return {
        "id": "t",
        "title": "T",
        "category": "tool-selection",
        "signals": {"objective": "Tidy the parser"},
        "window_tokens": 4000,
        "acceptance_criteria": [{"id": "ok", "text": "It works."}],
        "subtasks": [{"id": "s", "objective": "Tidy the parser"}],
        "script": [
            {"id": "use", "subtask": "s", "kind": "tool_output", "tokens": 10, **step},
            {
                "id": "v",
                "subtask": "s",
                "kind": "verify",
                "signature": "make t",
                "criteria": ["ok"],
            },
        ],
    }


class ShippedTests(unittest.TestCase):
    report: EvalReport

    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = load_tasks(EVALS_DIR / TASKS_SUBDIR)
        cls.configs = load_configs(EVALS_DIR / CONFIGS_FILE)
        cls.report = harness.run(cls.tasks, cls.configs)

    def result(self, config_id: str, task_id: str = TASK) -> RunResult:
        return next(r for r in self.report.runs if (r.task_id, r.config_id) == (task_id, config_id))

    def test_off_hands_every_subtask_the_whole_reference_list(self) -> None:
        off = self.result(OFF)
        self.assertEqual(off.tool_selection, "off")
        for tools in off.subtask_tools:
            self.assertEqual((tools.selected, tools.dropped, tools.restored), (ALL, (), ()))
        self.assertEqual(off.counts.tool_selection_misses, 0)
        self.assertEqual(off.counts.estimated_tool_tokens_offered, 2 * tokens(*ALL))
        self.assertEqual(
            off.counts.estimated_tool_tokens_selected, off.counts.estimated_tool_tokens_offered
        )

    def test_local_narrows_the_read_only_subtask(self) -> None:
        review = self.result(LOCAL).subtask_tools[0]
        self.assertEqual(review.subtask_id, "review")
        self.assertEqual(review.selected, ("Read", "Grep", "Glob", "Bash"))
        self.assertEqual(review.dropped, ("Edit", "Write"))
        self.assertEqual(review.estimated_tokens_selected, tokens("Read", "Grep", "Glob", "Bash"))
        self.assertEqual(review.misses, 0)

    def test_local_drops_a_needed_tool_which_is_then_restored(self) -> None:
        local = self.result(LOCAL)
        split = local.subtask_tools[1]
        self.assertEqual((split.subtask_id, split.restored, split.misses), ("split", ("Write",), 1))
        self.assertIn("Write", split.selected)
        self.assertEqual(local.counts.tool_selection_misses, 1)
        self.assertTrue(local.success)
        self.assertEqual([s.status for s in local.subtasks], [TaskStatus.VERIFIED] * 2)

    def test_the_estimate_is_lower_under_local_and_nothing_else_moves(self) -> None:
        off, local = self.result(OFF).counts, self.result(LOCAL).counts
        self.assertLess(local.estimated_tool_tokens_selected, off.estimated_tool_tokens_selected)
        self.assertEqual(local.estimated_tool_tokens_offered, off.estimated_tool_tokens_offered)
        same = ("criteria_met", "attempts", "cost_units", "duration_units", "guard_trips")
        for name in same:
            with self.subTest(field=name):
                self.assertEqual(getattr(local, name), getattr(off, name))

    def test_selection_off_matches_the_baseline_configuration(self) -> None:
        for task in self.report.task_ids:
            with self.subTest(task=task):
                self.assertEqual(
                    self.result(OFF, task).counts, self.result("baseline", task).counts
                )

    def test_other_tasks_have_no_misses_under_local(self) -> None:
        for task in self.report.task_ids:
            if task != TASK:
                self.assertEqual(self.result(LOCAL, task).counts.tool_selection_misses, 0, task)

    def test_runs_are_deterministic(self) -> None:
        again = harness.run(self.tasks, self.configs)
        self.assertEqual(again, self.report)
        self.assertEqual(report.render_json(again, "en"), report.render_json(self.report, "en"))

    def test_the_report_labels_token_figures_as_estimates_in_both_languages(self) -> None:
        english = report.render_markdown(self.report, "en")
        self.assertIn("Est. tool-definition tokens selected (approximate)", english)
        self.assertIn("Tool-selection misses", english)
        self.assertIn("token figures are estimates", report.notice("en"))
        self.assertIn("say nothing about model quality", report.notice("en"))
        portuguese = report.render_markdown(self.report, "pt-BR")
        self.assertIn("(aproximado)", portuguese)
        self.assertIn("são estimativas", report.notice("pt-BR"))
        self.assertIn("`tool-selection-miss` / `tools-selection-local`", english)


class MechanicsTests(unittest.TestCase):
    def run_one(self, selection: str, **step: Any) -> RunResult:
        config = HarnessConfig(id="c", tool_selection=selection)
        return harness.run_one(parse_task(task_data(**step)), config)

    def test_a_tool_outside_the_reference_list_fails_the_subtask(self) -> None:
        result = self.run_one("local", needs_tool="WebFetch")
        self.assertEqual(result.subtasks[0].failure, "tool_unavailable")
        self.assertEqual(result.subtasks[0].attempts, 1)
        self.assertEqual(result.counts.tool_selection_misses, 0)

    def test_a_selected_tool_is_not_a_miss(self) -> None:
        result = self.run_one("local", needs_tool="Grep")
        self.assertEqual((result.counts.tool_selection_misses, result.success), (0, True))

    def test_off_never_checks_the_tools_a_step_needs(self) -> None:
        result = self.run_one("off", needs_tool="WebFetch")
        self.assertTrue(result.success)

    def test_an_unknown_selection_mode_is_refused(self) -> None:
        for mode in ("provider", "jev"):
            with self.subTest(mode=mode), self.assertRaises(ValidationError):
                HarnessConfig(id="c", tool_selection=mode)


if __name__ == "__main__":
    unittest.main()
