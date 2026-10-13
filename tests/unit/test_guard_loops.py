"""Guard rules added for real loops: alternating commands, polling caps and budgets."""

from __future__ import annotations

import unittest

from wev_skills.config import LimitsConfig
from wev_skills.core.contracts import GuardAction
from wev_skills.guards import (
    GuardEvent,
    GuardLimits,
    budget_event,
    command_event,
    evaluate,
    progress_event,
)

T = "t1"
A, B, C = ("make", "test"), ("make", "lint"), ("git", "status")


def cmd(at: float, argv: tuple[str, ...], code: int | None = 0, **kw: bool) -> GuardEvent:
    return command_event(T, at, argv, "/w", code, **kw)


def limits(**kw: object) -> GuardLimits:
    base: dict[str, object] = {
        "max_identical_commands": 3,
        "max_consecutive_failures": 0,
        "no_progress_window": 0,
        "task_timeout_seconds": None,
        "budget_units": None,
    }
    base.update(kw)
    return GuardLimits(**base)  # type: ignore[arg-type]


def series(*argvs: tuple[str, ...], start: float = 1.0) -> list[GuardEvent]:
    return [cmd(start + index, argv) for index, argv in enumerate(argvs)]


class AlternatingLoopTests(unittest.TestCase):
    def test_a_two_command_cycle_trips_the_identical_command_rule(self) -> None:
        events = series(*([A, B] * 4))
        result = evaluate(events, limits())
        self.assertEqual(
            (result.action, result.rule), (GuardAction.CHANGE_STRATEGY, "identical_commands")
        )
        self.assertEqual(len(result.details["cycle"]), 2)

    def test_a_three_command_cycle_trips_too(self) -> None:
        result = evaluate(series(*([A, B, C] * 4)), limits())
        self.assertEqual(result.rule, "identical_commands")
        self.assertEqual(len(result.details["cycle"]), 3)

    def test_a_cycle_within_the_allowed_repeats_does_not_trip(self) -> None:
        self.assertIs(evaluate(series(*([A, B] * 3)), limits()).action, GuardAction.CONTINUE)

    def test_progress_between_rounds_is_not_a_loop(self) -> None:
        events: list[GuardEvent] = []
        for round_number in range(6):
            base = 10.0 * round_number
            events.append(progress_event(T, base, f"tree-{round_number}"))
            events.extend(series(A, B, start=base + 1))
        self.assertIs(evaluate(events, limits()).action, GuardAction.CONTINUE)

    def test_distinct_commands_are_not_a_cycle(self) -> None:
        varied = [("step", str(index)) for index in range(12)]
        self.assertIs(evaluate(series(*varied), limits()).action, GuardAction.CONTINUE)


class ProgressTests(unittest.TestCase):
    def test_same_command_with_edits_between_runs_never_trips(self) -> None:
        events: list[GuardEvent] = []
        for index in range(10):
            events.append(progress_event(T, 2.0 * index, f"tree-{index}"))
            events.append(cmd(2.0 * index + 1, A, 1))
        result = evaluate(events, limits(no_progress_window=8))
        self.assertIs(result.action, GuardAction.CONTINUE)

    def test_same_command_without_any_change_still_trips(self) -> None:
        events = [progress_event(T, 0.0, "tree"), *series(A, A, A, A)]
        self.assertEqual(evaluate(events, limits()).rule, "identical_commands")


class PollingCapTests(unittest.TestCase):
    def polls(self, count: int) -> list[GuardEvent]:
        return [cmd(float(index), ("tmux", "capture-pane"), polling=True) for index in range(count)]

    def test_polling_is_exempt_up_to_the_cap(self) -> None:
        result = evaluate(self.polls(5), limits(max_polling_commands=5))
        self.assertIs(result.action, GuardAction.CONTINUE)

    def test_beyond_the_cap_a_human_is_asked(self) -> None:
        result = evaluate(self.polls(6), limits(max_polling_commands=5))
        self.assertEqual((result.action, result.rule), (GuardAction.ASK_HUMAN, "polling_cap"))

    def test_a_real_command_between_polls_restarts_the_count(self) -> None:
        events = [*self.polls(4), cmd(50.0, A), *self.polls(4)]
        result = evaluate(events, limits(max_polling_commands=5))
        self.assertIs(result.action, GuardAction.CONTINUE)

    def test_the_cap_comes_from_configuration_with_a_default_of_sixty(self) -> None:
        self.assertEqual(GuardLimits.from_config(LimitsConfig()).max_polling_commands, 60)
        custom = GuardLimits.from_config(LimitsConfig(max_polling_commands=7))
        self.assertEqual(custom.max_polling_commands, 7)


class BudgetTests(unittest.TestCase):
    def test_one_unit_per_command_trips_when_the_budget_is_exceeded(self) -> None:
        events = [budget_event(T, float(index), 1.0) for index in range(4)]
        self.assertIs(evaluate(events, limits(budget_units=4.0)).action, GuardAction.CONTINUE)
        events.append(budget_event(T, 9.0, 1.0))
        result = evaluate(events, limits(budget_units=4.0))
        self.assertEqual((result.action, result.rule), (GuardAction.ASK_HUMAN, "budget"))


if __name__ == "__main__":
    unittest.main()
