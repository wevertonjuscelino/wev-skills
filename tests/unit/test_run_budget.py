"""Whole-run budgets stop at the boundary and survive per-task guard resets."""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from wev_skills.config import LimitsConfig
from wev_skills.core import run_budget
from wev_skills.core.contracts import GuardAction, Mode
from wev_skills.core.errors import GuardTripped
from wev_skills.guards.events import budget_event, reset_event
from wev_skills.state.model import RunState


class RunBudgetTests(unittest.TestCase):
    def state(self, units: float) -> RunState:
        events = (budget_event("task", 1, units).to_dict(), reset_event("task", 2).to_dict())
        return RunState("run-1", "goal", Mode.EXECUTE, "now", "now", guard_events=events)

    def test_warning_at_eighty_and_stop_at_one_hundred(self) -> None:
        limits = replace(LimitsConfig(), run_budget_units=10)
        self.assertFalse(run_budget.payload(self.state(7), limits)["warning"])
        self.assertTrue(run_budget.payload(self.state(8), limits)["warning"])
        self.assertEqual(run_budget.verdict(self.state(10), limits).action, GuardAction.STOP)

    def test_preflight_refuses_overshoot_without_resetting_spent(self) -> None:
        limits = replace(LimitsConfig(), run_budget_units=10)
        engine = SimpleNamespace(services=SimpleNamespace(config=SimpleNamespace(limits=limits)))
        run_budget.require(engine, self.state(9), units=1)
        with self.assertRaises(GuardTripped):
            run_budget.require(engine, self.state(9), units=2)
        with self.assertRaises(GuardTripped):
            run_budget.require(engine, self.state(10), units=1)


if __name__ == "__main__":
    unittest.main()
