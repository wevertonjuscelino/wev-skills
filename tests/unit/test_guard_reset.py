"""Guard reset markers: earlier events of the scope stop counting, later ones do."""

from __future__ import annotations

import unittest

from wev_skills.config import LimitsConfig
from wev_skills.core.contracts import GuardAction
from wev_skills.guards import (
    GuardEvent,
    GuardEventKind,
    GuardLimits,
    budget_event,
    command_event,
    effective_events,
    evaluate,
    reset_event,
)

LIMITS = GuardLimits.from_config(LimitsConfig())


def cmd(task: str, at: float) -> GuardEvent:
    return command_event(task, at, ("pytest",), "/w", 1)


class EffectiveEventsTests(unittest.TestCase):
    def test_without_markers_the_history_is_unchanged(self) -> None:
        events = (cmd("a", 1.0), cmd("b", 2.0))
        self.assertEqual(effective_events(events), events)

    def test_a_task_reset_drops_only_that_tasks_earlier_events(self) -> None:
        later = cmd("a", 5.0)
        events = (cmd("a", 1.0), cmd("b", 2.0), reset_event("a", 3.0), later)
        self.assertEqual(effective_events(events), (events[1], later))

    def test_a_run_wide_reset_drops_every_earlier_event(self) -> None:
        later = cmd("b", 5.0)
        events = (cmd("a", 1.0), budget_event("", 2.0, 9.0), reset_event("", 3.0), later)
        self.assertEqual(effective_events(events), (later,))

    def test_markers_never_appear_in_the_result(self) -> None:
        events = (reset_event("a", 1.0), cmd("a", 2.0), reset_event("", 3.0))
        self.assertTrue(all(e.kind is not GuardEventKind.RESET for e in effective_events(events)))

    def test_position_decides_not_the_timestamp(self) -> None:
        marker = reset_event("a", 1.0)
        events = (cmd("a", 9.0), marker, cmd("a", 0.5))
        self.assertEqual(effective_events(events), (events[2],))

    def test_marker_round_trips_through_json(self) -> None:
        marker = reset_event("a", 1.0)
        self.assertEqual(GuardEvent.from_dict(marker.to_dict()), marker)


class EvaluateAfterResetTests(unittest.TestCase):
    def failing(self, task: str, count: int, start: float = 0.0) -> list[GuardEvent]:
        return [cmd(task, start + i) for i in range(count)]

    def test_a_tripped_scope_continues_after_the_reset(self) -> None:
        events = self.failing("a", 6)
        self.assertNotEqual(evaluate(events, LIMITS, now=10.0).action, GuardAction.CONTINUE)
        events.append(reset_event("a", 7.0))
        self.assertEqual(evaluate(events, LIMITS, now=10.0).action, GuardAction.CONTINUE)

    def test_counting_starts_again_after_the_reset(self) -> None:
        events = [*self.failing("a", 6), reset_event("a", 7.0), *self.failing("a", 6, 8.0)]
        self.assertNotEqual(evaluate(events, LIMITS, now=20.0).action, GuardAction.CONTINUE)

    def test_a_reset_of_another_task_does_not_clear_the_trip(self) -> None:
        events = [*self.failing("a", 6), reset_event("b", 7.0)]
        self.assertNotEqual(evaluate(events, LIMITS, now=10.0).action, GuardAction.CONTINUE)

    def test_a_run_wide_reset_clears_the_budget(self) -> None:
        events = [budget_event("a", 1.0, 1e9), reset_event("", 2.0)]
        self.assertEqual(evaluate(events, LIMITS, now=3.0).action, GuardAction.CONTINUE)


if __name__ == "__main__":
    unittest.main()
