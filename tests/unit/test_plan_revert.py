"""A medium or high risk plan must say what could go wrong and how to undo it."""

from __future__ import annotations

from pathlib import Path

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.core.errors import ValidationError

TASK = {"id": "a", "acceptance_criteria": ["done"]}
RISKY = {**TASK, "risk": "medium"}


class PlanRevertTests(OrchestratorCase):
    def refused(self, *tasks: dict[str, object], **notes: str) -> ValidationError:
        with self.assertRaises(ValidationError) as caught:
            self.set_plan(*tasks, **notes)
        return caught.exception

    def test_low_risk_plan_without_revert_ok(self) -> None:
        self.start()
        self.set_plan(TASK, risk_notes="", revert="")
        self.assertEqual(self.state().plan.revert, "")

    def test_medium_task_risk_needs_revert(self) -> None:
        self.start()
        error = self.refused(RISKY, revert="")
        self.assertEqual(error.code, "plan_needs_revert")
        self.assertEqual(self.refused(RISKY, risk_notes="   ").code, "plan_needs_revert")
        self.set_plan(RISKY)
        self.assertEqual(self.state().plan.revert, "git revert the commit.")

    def test_high_run_risk_needs_revert(self) -> None:
        self.start(touches_production=True, destructive=True)
        self.assertEqual(self.state().classification.risk.value, "high")
        self.assertEqual(self.refused(TASK, revert="").code, "plan_needs_revert")
        self.set_plan(TASK)

    def test_an_amendment_cannot_drop_the_notes(self) -> None:
        self.start()
        self.set_plan(RISKY)
        self.assertEqual(self.refused(RISKY, risk_notes="", revert="").code, "plan_needs_revert")
        self.assertEqual(self.state().plan.risk_notes, "Test plan.")

    def test_oversized_notes_are_refused_by_the_schema(self) -> None:
        self.start()
        self.assertEqual(self.refused(TASK, revert="x" * 4001).code, "invalid_plan")

    def test_template_has_risk_revert_review(self) -> None:
        text = (Path(__file__).parents[2] / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text()
        for heading in ("## Risk", "## How to revert", "## Review", "## Summary"):
            self.assertIn(heading, text)
