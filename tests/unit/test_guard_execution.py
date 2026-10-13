from __future__ import annotations

import json
import unittest

from wev_skills import i18n
from wev_skills.config import DEFAULT_TASK_TIMEOUT_SECONDS, LimitsConfig
from wev_skills.core.contracts import GuardAction
from wev_skills.guards import (
    ExecutionGuard,
    GuardEvent,
    GuardLimits,
    attempt_event,
    budget_event,
    command_event,
    command_signature,
    evaluate,
    handoff_event,
    progress_event,
    verification_event,
)

T = "t1"


def cmd(
    at: float, argv: tuple[str, ...] = ("pytest",), code: int | None = 0, **kw: bool
) -> GuardEvent:
    return command_event(T, at, argv, "/w", code, **kw)


def limits(**kw: object) -> GuardLimits:
    base = {
        "max_identical_commands": 3,
        "max_consecutive_failures": 3,
        "max_attempts": 3,
        "max_handoff_cycle_repeats": 2,
        "no_progress_window": 0,
        "max_repeated_verifications": 2,
        "budget_units": 100.0,
        "task_timeout_seconds": 600.0,
        "flaky_retries": 2,
    }
    base.update(kw)
    return GuardLimits(**base)  # type: ignore[arg-type]


def verdict(events: list[GuardEvent], **kw: object) -> tuple[GuardAction, str]:
    result = evaluate(events, limits(**kw))
    return result.action, result.rule


class EventTests(unittest.TestCase):
    def test_round_trip_through_json(self) -> None:
        events = [
            cmd(1.0, polling=True),
            handoff_event(T, 2.0, "a", "b"),
            attempt_event(T, 3.0, "failed", "sig"),
            verification_event(T, 4.0, "v", False, "fp"),
            progress_event(T, 5.0, "p"),
            budget_event(T, 6.0, 2.5),
        ]
        restored = [GuardEvent.from_dict(json.loads(json.dumps(e.to_dict()))) for e in events]
        self.assertEqual(restored, events)

    def test_signature_is_stable_and_sensitive_to_argv_and_cwd(self) -> None:
        base = command_signature(["a", "b"], "/w")
        self.assertEqual(base, command_signature(("a", "b"), "/w/"))
        self.assertNotEqual(base, command_signature(["a", "c"], "/w"))
        self.assertNotEqual(base, command_signature(["a", "b"], "/x"))
        self.assertNotEqual(command_signature(["a b"], "/w"), command_signature(["a", "b"], "/w"))


class IdenticalCommandTests(unittest.TestCase):
    def test_trips_after_more_than_limit(self) -> None:
        events = [cmd(i) for i in range(4)]
        self.assertEqual(verdict(events), (GuardAction.CHANGE_STRATEGY, "identical_commands"))

    def test_does_not_trip_at_limit(self) -> None:
        self.assertEqual(verdict([cmd(i) for i in range(3)])[0], GuardAction.CONTINUE)

    def test_progress_event_resets(self) -> None:
        events = [cmd(0), cmd(1), cmd(2), progress_event(T, 3, "x"), cmd(4)]
        self.assertEqual(verdict(events)[0], GuardAction.CONTINUE)

    def test_successful_different_command_resets_but_failed_one_does_not(self) -> None:
        other_ok = cmd(3, ("ls",), 0)
        other_bad = cmd(3, ("ls",), 1)
        base = [cmd(0), cmd(1), cmd(2)]
        self.assertEqual(verdict([*base, other_ok, cmd(4)])[0], GuardAction.CONTINUE)
        action, rule = verdict([*base, other_bad, cmd(4)], max_consecutive_failures=0)
        self.assertEqual((action, rule), (GuardAction.CHANGE_STRATEGY, "identical_commands"))

    def test_polling_is_exempt(self) -> None:
        events = [cmd(i, polling=True) for i in range(10)]
        self.assertEqual(verdict(events)[0], GuardAction.CONTINUE)

    def test_flaky_gets_extra_retries(self) -> None:
        self.assertEqual(verdict([cmd(i, flaky=True) for i in range(5)])[0], GuardAction.CONTINUE)
        self.assertEqual(
            verdict([cmd(i, flaky=True) for i in range(6)])[0], GuardAction.CHANGE_STRATEGY
        )

    def test_disabled_with_zero_or_none(self) -> None:
        events = [cmd(i) for i in range(9)]
        self.assertEqual(verdict(events, max_identical_commands=0)[0], GuardAction.CONTINUE)
        self.assertEqual(verdict(events, max_identical_commands=None)[0], GuardAction.CONTINUE)


class FailureTests(unittest.TestCase):
    def fails(self, n: int) -> list[GuardEvent]:
        return [cmd(i, (f"c{i}",), 1) for i in range(n)]

    def test_change_strategy_then_escalate(self) -> None:
        self.assertEqual(verdict(self.fails(2))[0], GuardAction.CONTINUE)
        self.assertEqual(
            verdict(self.fails(3)), (GuardAction.CHANGE_STRATEGY, "consecutive_failures")
        )
        self.assertEqual(verdict(self.fails(5))[0], GuardAction.CHANGE_STRATEGY)
        self.assertEqual(verdict(self.fails(6)), (GuardAction.ESCALATE, "consecutive_failures"))

    def test_success_resets_the_run(self) -> None:
        events = [*self.fails(2), cmd(5, ("ok",), 0), *self.fails(2)]
        self.assertEqual(verdict(events)[0], GuardAction.CONTINUE)

    def test_failed_attempts_count_with_commands(self) -> None:
        events = [cmd(0, ("a",), 1), attempt_event(T, 1, "failed", "x"), cmd(2, ("b",), 1)]
        self.assertEqual(verdict(events, max_attempts=0)[0], GuardAction.CHANGE_STRATEGY)

    def test_missing_exit_code_counts_as_failure(self) -> None:
        events = [cmd(i, (f"c{i}",), None) for i in range(3)]
        self.assertEqual(verdict(events)[0], GuardAction.CHANGE_STRATEGY)


class AttemptTests(unittest.TestCase):
    def test_reaching_max_attempts_escalates(self) -> None:
        two = [attempt_event(T, i, "failed", f"e{i}") for i in range(2)]
        self.assertEqual(verdict(two)[0], GuardAction.CONTINUE)
        three = [*two, attempt_event(T, 3, "failed", "e3")]
        self.assertEqual(
            verdict(three, max_consecutive_failures=0), (GuardAction.ESCALATE, "attempts")
        )

    def test_same_error_twice_changes_strategy_first(self) -> None:
        events = [attempt_event(T, 0, "failed", "boom"), attempt_event(T, 1, "failed", "boom")]
        self.assertEqual(
            verdict(events, max_consecutive_failures=0),
            (GuardAction.CHANGE_STRATEGY, "repeated_error"),
        )

    def test_different_or_empty_errors_do_not_trip(self) -> None:
        diff = [attempt_event(T, 0, "failed", "a"), attempt_event(T, 1, "failed", "b")]
        empty = [attempt_event(T, 0, "failed"), attempt_event(T, 1, "failed")]
        for events in (diff, empty):
            self.assertEqual(verdict(events, max_consecutive_failures=0)[0], GuardAction.CONTINUE)


class HandoffTests(unittest.TestCase):
    def chain(self, pairs: list[tuple[str, str]]) -> list[GuardEvent]:
        return [handoff_event(T, i, a, b) for i, (a, b) in enumerate(pairs)]

    def test_ping_pong_beyond_limit_stops(self) -> None:
        pairs = [("a", "b"), ("b", "a")] * 3
        self.assertEqual(verdict(self.chain(pairs)), (GuardAction.STOP, "handoff_cycle"))

    def test_ping_pong_within_limit_continues(self) -> None:
        pairs = [("a", "b"), ("b", "a")] * 2
        self.assertEqual(verdict(self.chain(pairs))[0], GuardAction.CONTINUE)

    def test_three_agent_cycle_detected(self) -> None:
        pairs = [("a", "b"), ("b", "c"), ("c", "a")] * 3
        self.assertEqual(verdict(self.chain(pairs))[0], GuardAction.STOP)

    def test_linear_chain_is_fine(self) -> None:
        pairs = [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")]
        self.assertEqual(
            verdict(self.chain(pairs), max_handoff_cycle_repeats=1)[0], GuardAction.CONTINUE
        )


class NoProgressTests(unittest.TestCase):
    def distinct(self, n: int, start: int = 0) -> list[GuardEvent]:
        return [cmd(start + i, (f"c{start + i}",), 0) for i in range(n)]

    def test_window_without_progress_reduces_scope(self) -> None:
        self.assertEqual(
            verdict(self.distinct(5), no_progress_window=5),
            (GuardAction.REDUCE_SCOPE, "no_progress"),
        )
        self.assertEqual(verdict(self.distinct(4), no_progress_window=5)[0], GuardAction.CONTINUE)

    def test_changed_fingerprint_resets_unchanged_does_not(self) -> None:
        changed = [*self.distinct(4), progress_event(T, 10, "f2"), *self.distinct(3, 20)]
        self.assertEqual(verdict(changed, no_progress_window=5)[0], GuardAction.CONTINUE)
        same = [
            progress_event(T, 0, "f1"),
            *self.distinct(3, 1),
            progress_event(T, 9, "f1"),
            *self.distinct(2, 20),
        ]
        self.assertEqual(verdict(same, no_progress_window=5)[0], GuardAction.REDUCE_SCOPE)

    def test_polling_not_counted(self) -> None:
        events = [cmd(i, polling=True) for i in range(9)]
        self.assertEqual(verdict(events, no_progress_window=5)[0], GuardAction.CONTINUE)


class VerificationTests(unittest.TestCase):
    def ver(self, n: int, fp: str = "s") -> list[GuardEvent]:
        return [verification_event(T, i, "pytest", False, fp) for i in range(n)]

    def test_repeated_failure_with_same_state_trips(self) -> None:
        self.assertEqual(
            verdict(self.ver(3)), (GuardAction.CHANGE_STRATEGY, "repeated_verification")
        )
        self.assertEqual(verdict(self.ver(2))[0], GuardAction.CONTINUE)

    def test_changed_fingerprint_resets_count(self) -> None:
        events = [*self.ver(2, "a"), verification_event(T, 5, "pytest", False, "b")]
        self.assertEqual(verdict(events)[0], GuardAction.CONTINUE)

    def test_pass_resets_and_signatures_are_independent(self) -> None:
        events = [*self.ver(2), verification_event(T, 5, "pytest", True, "s"), *self.ver(1)]
        self.assertEqual(verdict(events)[0], GuardAction.CONTINUE)
        mixed = [verification_event(T, i, f"v{i % 3}", False, "s") for i in range(6)]
        self.assertEqual(verdict(mixed)[0], GuardAction.CONTINUE)


class BudgetTimeoutDependencyTests(unittest.TestCase):
    def test_budget(self) -> None:
        over = [budget_event(T, 0, 60), budget_event(T, 1, 50)]
        self.assertEqual(verdict(over), (GuardAction.ASK_HUMAN, "budget"))
        self.assertEqual(
            verdict([budget_event(T, 0, 60), budget_event(T, 1, 40)])[0], GuardAction.CONTINUE
        )

    def test_timeout_uses_now_and_first_event(self) -> None:
        events = [cmd(0, ("a",)), cmd(10, ("b",))]
        late = evaluate(events, limits(), now=601)
        self.assertEqual((late.action, late.rule), (GuardAction.ASK_HUMAN, "timeout"))
        self.assertEqual(evaluate(events, limits(), now=600).action, GuardAction.CONTINUE)

    def test_timeout_with_recent_polling_continues_with_reason(self) -> None:
        events = [cmd(0, ("a",)), cmd(500, ("wait",), polling=True)]
        with i18n.use_language("en"):
            result = evaluate(events, limits(), now=700)
        self.assertEqual(result.action, GuardAction.CONTINUE)
        self.assertEqual(result.rule, "timeout")
        self.assertIn("long-running", result.reasons[0])

    def test_timeout_disabled(self) -> None:
        result = evaluate([cmd(0)], limits(task_timeout_seconds=None), now=10**6)
        self.assertEqual(result.action, GuardAction.CONTINUE)

    def test_unresolved_dependencies_stop(self) -> None:
        result = evaluate([cmd(0)], limits(), unresolved_dependencies=("b", "a"))
        self.assertEqual(
            (result.action, result.rule), (GuardAction.STOP, "unresolved_dependencies")
        )
        self.assertEqual(result.details["unresolved_dependencies"], ["a", "b"])
        self.assertEqual(evaluate([cmd(0)], limits()).action, GuardAction.CONTINUE)


class VerdictTests(unittest.TestCase):
    def test_most_severe_wins_and_others_are_listed(self) -> None:
        events = [cmd(i) for i in range(4)] + [budget_event(T, 5, 500)]
        result = evaluate(events, limits())
        self.assertEqual(result.action, GuardAction.ASK_HUMAN)
        others = result.details["other_rules"]
        self.assertEqual([o["rule"] for o in others], ["identical_commands"])
        self.assertEqual(len(result.reasons), 2)

    def test_verdict_is_json_serializable_and_empty_history_continues(self) -> None:
        result = evaluate([], limits())
        self.assertEqual(result.action, GuardAction.CONTINUE)
        json.dumps(evaluate([cmd(i) for i in range(4)], limits()).to_dict())

    def test_tasks_are_judged_independently(self) -> None:
        mixed = [command_event("a", i, ("x",), "/w", 0) for i in range(2)]
        mixed += [command_event("b", i, ("x",), "/w", 0) for i in range(2)]
        self.assertEqual(evaluate(mixed, limits()).action, GuardAction.CONTINUE)

    def test_from_config_maps_known_limits(self) -> None:
        built = GuardLimits.from_config(LimitsConfig(max_attempts=9, budget_units=5.0))
        self.assertEqual((built.max_attempts, built.budget_units), (9, 5.0))
        self.assertEqual(built.no_progress_window, GuardLimits().no_progress_window)


class ObserveTests(unittest.TestCase):
    def test_observe_returns_new_history_without_mutating(self) -> None:
        guard = ExecutionGuard(limits())
        history: tuple[GuardEvent, ...] = ()
        for i in range(3):
            history, result = guard.observe(history, cmd(i))
            self.assertEqual(result.action, GuardAction.CONTINUE)
        before = history
        history, result = guard.observe(before, cmd(3))
        self.assertEqual(len(before), 3)
        self.assertEqual(len(history), 4)
        self.assertEqual(result.action, GuardAction.CHANGE_STRATEGY)


class DefaultsAgreeTests(unittest.TestCase):
    def test_guard_timeout_default_matches_the_config_default(self) -> None:
        self.assertEqual(GuardLimits().task_timeout_seconds, LimitsConfig().task_timeout_seconds)
        self.assertEqual(GuardLimits().task_timeout_seconds, DEFAULT_TASK_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
