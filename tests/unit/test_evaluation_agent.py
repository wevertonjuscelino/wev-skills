from __future__ import annotations

import unittest
from typing import Any

from tests.unit.test_evaluation_tasks import task_data
from wev_skills import i18n
from wev_skills.context import estimate_tokens
from wev_skills.core.contracts import TaskStatus
from wev_skills.core.errors import ValidationError
from wev_skills.evaluation.agent import ScriptedAgent, filler_text
from wev_skills.evaluation.configs import PLAN_TOKENS, SIMULATED_PRICE_PER_TOKEN, parse_configs
from wev_skills.evaluation.metrics import SubtaskOutcome
from wev_skills.evaluation.tasks import parse_task

VERIFY = {"id": "check", "kind": "verify", "signature": "run-tests", "criteria": ["c1"]}
FAILING_BUILD = {"id": "build", "kind": "command", "signature": "make", "outcome": "fail"}


def run_script(
    steps: list[dict[str, Any]],
    window: int = 4000,
    signals: dict[str, Any] | None = None,
    **config: Any,
) -> SubtaskOutcome:
    """Replay ``steps`` as the only subtask of a task under one configuration."""
    script = [{"subtask": "s", **step} for step in steps]
    overrides: dict[str, Any] = {"script": script, "window_tokens": window}
    if signals is not None:
        overrides["signals"] = signals
    task = parse_task(task_data(**overrides))
    harness_config = parse_configs({"configs": [{"id": "cfg", **config}]})[0]
    with i18n.use_language("en"):
        return ScriptedAgent(task, harness_config).run_subtask(task.subtasks[0])


def outputs(count: int, tokens: int, needed: str = "") -> list[dict[str, Any]]:
    return [
        {
            "id": f"out-{i}",
            "kind": "tool_output",
            "tokens": tokens,
            "needed_later": f"out-{i}" == needed,
        }
        for i in range(1, count + 1)
    ]


class BasicReplayTests(unittest.TestCase):
    def test_filler_text_has_the_exact_estimated_size(self) -> None:
        for tokens in (1, 3, 250):
            self.assertEqual(estimate_tokens(filler_text("item", tokens)), tokens)

    def test_unconditional_script_is_verified_in_one_attempt(self) -> None:
        outcome = run_script([{"id": "read", "kind": "tool_output", "tokens": 100}, VERIFY])
        self.assertEqual(outcome.status, TaskStatus.VERIFIED)
        self.assertEqual((outcome.attempts, outcome.duration_units, outcome.failure), (1, 2, ""))
        self.assertEqual([(v.step_id, v.passed) for v in outcome.verifications], [("check", True)])

    def test_script_without_verification_is_partial_not_verified(self) -> None:
        task = task_data()
        task["subtasks"] = [{"id": "s"}, {"id": "other"}]
        extra = {"id": "n", "subtask": "other", "kind": "note", "tokens": 5}
        task["script"] = [*task["script"], extra]
        parsed = parse_task(task)
        agent = ScriptedAgent(parsed, parse_configs({"configs": [{"id": "c"}]})[0])
        self.assertEqual(agent.run_subtask(parsed.subtasks[1]).status, TaskStatus.PARTIAL)

    def test_cost_is_context_tokens_times_the_tier_price(self) -> None:
        steps = [{"id": "read", "kind": "tool_output", "tokens": 100}, VERIFY]
        seed = estimate_tokens("The thing works.") + PLAN_TOKENS
        expected_tokens = (seed + 100) + (seed + 100)
        for tier, price in SIMULATED_PRICE_PER_TOKEN.items():
            with self.subTest(tier):
                outcome = run_script(steps, routing="fixed", fixed_tier=tier)
                self.assertEqual(outcome.cost_units, expected_tokens * price)
                self.assertEqual(outcome.final_tier, tier)

    def test_plan_item_is_only_in_context_when_planned(self) -> None:
        steps = [{"id": "read", "kind": "tool_output", "tokens": 100}, VERIFY]
        planned = run_script(steps, planning="on", routing="fixed", fixed_tier="economy")
        direct = run_script(steps, planning="off", routing="fixed", fixed_tier="economy")
        self.assertEqual(planned.cost_units - direct.cost_units, 2 * PLAN_TOKENS)


class ConditionTests(unittest.TestCase):
    def test_pass_from_attempt_needs_enough_attempts(self) -> None:
        steps = [{**VERIFY, "conditions": {"pass_from_attempt": 2}}]
        single = run_script(steps, max_attempts=1)
        self.assertEqual((single.status, single.failure), (TaskStatus.FAILED, "attempt_gate"))
        self.assertEqual([v.passed for v in single.verifications], [False])
        double = run_script(steps, max_attempts=2)
        self.assertEqual((double.status, double.attempts), (TaskStatus.VERIFIED, 2))

    def test_min_tier_is_reached_by_policy_escalation_on_the_third_attempt(self) -> None:
        moderate = {"objective": "x", "files_touched_estimate": 6, "unknowns": 1}
        steps = [{"id": "edit", "kind": "edit"}, {**VERIFY, "conditions": {"min_tier": "premium"}}]
        policy = run_script(steps, signals=moderate, max_attempts=3)
        self.assertEqual((policy.status, policy.attempts), (TaskStatus.VERIFIED, 3))
        self.assertEqual((policy.final_tier, policy.tier_escalations), ("premium", 1))
        self.assertEqual(policy.guard_trips, ("repeated_error",))
        short = run_script(steps, signals=moderate, max_attempts=2)
        self.assertEqual((short.status, short.failure), (TaskStatus.FAILED, "tier_gate"))
        self.assertEqual(short.escalations, 1)

    def test_min_tier_with_fixed_routing(self) -> None:
        steps = [{"id": "edit", "kind": "edit"}, {**VERIFY, "conditions": {"min_tier": "premium"}}]
        low = run_script(steps, routing="fixed", fixed_tier="standard")
        self.assertEqual((low.status, low.attempts), (TaskStatus.FAILED, 3))
        self.assertEqual(low.tier_escalations, 0)
        high = run_script(steps, routing="fixed", fixed_tier="premium")
        self.assertEqual((high.status, high.attempts), (TaskStatus.VERIFIED, 1))

    def test_requires_verbatim_fails_once_the_item_is_elided(self) -> None:
        steps = [
            *outputs(5, 600, needed="out-1"),
            {"id": "use", "kind": "edit", "conditions": {"requires_verbatim": ["out-1"]}},
            VERIFY,
        ]
        kept = run_script(steps, context_policy="none")
        self.assertEqual((kept.status, kept.info_loss_failures), (TaskStatus.VERIFIED, 0))
        lost = run_script(steps, context_policy="elide")
        self.assertEqual((lost.status, lost.failure), (TaskStatus.FAILED, "info_loss"))
        self.assertEqual((lost.info_loss_failures, lost.attempts), (1, 1))
        self.assertGreaterEqual(lost.items_elided, 1)
        self.assertEqual(lost.verifications, ())

    def test_requires_verbatim_fails_once_the_item_is_summarized(self) -> None:
        notes = [
            {"id": f"note-{i}", "kind": "note", "tokens": 700, "needed_later": i == 1}
            for i in range(1, 6)
        ]
        use = {"id": "use", "kind": "edit", "conditions": {"requires_verbatim": ["note-1"]}}
        steps = [*notes, use, VERIFY]
        elide_only = run_script(steps, context_policy="elide")
        self.assertEqual(elide_only.status, TaskStatus.VERIFIED)
        self.assertEqual(elide_only.items_summarized, 0)
        summarized = run_script(steps, context_policy="elide_and_summarize")
        self.assertEqual(summarized.failure, "info_loss")
        self.assertGreaterEqual(summarized.items_summarized, 2)


class ContextPolicyTests(unittest.TestCase):
    def test_unmanaged_context_overflows_and_is_not_retried(self) -> None:
        steps = [*outputs(6, 900), VERIFY]
        outcome = run_script(steps, context_policy="none")
        self.assertEqual(outcome.status, TaskStatus.FAILED)
        self.assertEqual(outcome.failure, "context_overflow")
        self.assertEqual((outcome.context_overflows, outcome.attempts), (1, 1))
        self.assertEqual(outcome.duration_units, 5)

    def test_elision_keeps_the_same_trajectory_inside_the_window(self) -> None:
        outcome = run_script([*outputs(6, 900), VERIFY], context_policy="elide")
        self.assertEqual(outcome.status, TaskStatus.VERIFIED)
        self.assertEqual(outcome.context_overflows, 0)
        self.assertEqual(outcome.items_elided, 3)

    def test_notes_overflow_under_elision_but_fit_with_the_stub_summarizer(self) -> None:
        notes = [{"id": f"note-{i}", "kind": "note", "tokens": 700} for i in range(1, 7)]
        elided = run_script([*notes, VERIFY], context_policy="elide")
        self.assertEqual((elided.failure, elided.items_elided), ("context_overflow", 0))
        summarized = run_script([*notes, VERIFY], context_policy="elide_and_summarize")
        self.assertEqual(summarized.status, TaskStatus.VERIFIED)
        self.assertGreater(summarized.items_summarized, 0)


class GuardTests(unittest.TestCase):
    def test_repeated_failing_command_is_stopped_and_never_succeeds(self) -> None:
        loop = {**FAILING_BUILD, "repeat": 20}
        outcome = run_script([loop, VERIFY])
        self.assertEqual(outcome.status, TaskStatus.FAILED)
        self.assertIn("consecutive_failures", outcome.guard_trips)
        self.assertTrue(outcome.failure.startswith("guard:"))
        self.assertEqual(outcome.verifications, ())
        self.assertLess(outcome.duration_units, 20)

    def test_a_trip_that_aborts_an_attempt_is_counted_once(self) -> None:
        loop = {**FAILING_BUILD, "repeat": 9}
        outcome = run_script([loop, VERIFY], max_attempts=1)
        self.assertEqual(outcome.guard_trips, ("consecutive_failures", "attempts"))
        self.assertEqual((outcome.attempts, outcome.duration_units), (1, 3))

    def test_without_the_guard_the_loop_runs_to_its_end_every_attempt(self) -> None:
        loop = {**FAILING_BUILD, "repeat": 20}
        outcome = run_script([loop, {**VERIFY, "outcome": "fail"}], guard_enabled=False)
        self.assertEqual((outcome.guard_trips, outcome.failure), ((), "verify_failed"))
        self.assertEqual((outcome.attempts, outcome.duration_units), (3, 63))

    def test_identical_passing_command_trips_unless_it_is_polling(self) -> None:
        repeated = {"id": "status", "kind": "command", "signature": "git status", "repeat": 6}
        looped = run_script([repeated, VERIFY])
        self.assertEqual(looped.status, TaskStatus.FAILED)
        self.assertIn("identical_commands", looped.guard_trips)
        polled = run_script([{**repeated, "polling": True}, VERIFY])
        self.assertEqual((polled.status, polled.guard_trips), (TaskStatus.VERIFIED, ()))

    def test_handoff_cycle_ends_the_subtask_at_once(self) -> None:
        pairs = [("a", "b"), ("b", "a")] * 4
        steps = [
            {"id": f"h{i}", "kind": "handoff", "from_agent": src, "to_agent": dst}
            for i, (src, dst) in enumerate(pairs)
        ]
        outcome = run_script([*steps, VERIFY])
        self.assertEqual((outcome.failure, outcome.attempts), ("guard:handoff_cycle", 1))
        self.assertEqual(outcome.guard_trips[0], "handoff_cycle")

    def test_budget_rule_uses_simulated_cost_units(self) -> None:
        steps = [*outputs(3, 300), VERIFY]
        outcome = run_script(steps, guard={"budget_units": 1000.0})
        self.assertEqual((outcome.failure, outcome.attempts), ("guard:budget", 1))

    def test_last_allowed_attempt_passing_is_not_a_guard_trip(self) -> None:
        steps = [{**VERIFY, "conditions": {"pass_from_attempt": 2}}]
        outcome = run_script(steps, max_attempts=2)
        self.assertEqual((outcome.status, outcome.guard_trips), (TaskStatus.VERIFIED, ()))


class DecisionTests(unittest.TestCase):
    def agent(self, signals: dict[str, Any], **config: Any) -> ScriptedAgent:
        task = parse_task(task_data(signals=signals))
        return ScriptedAgent(task, parse_configs({"configs": [{"id": "c", **config}]})[0])

    def test_auto_planning_follows_the_local_policy(self) -> None:
        trivial = {"objective": "x", "files_touched_estimate": 1}
        remote = {"objective": "x", "touches_remote": True, "unknowns": 2}
        self.assertFalse(self.agent(trivial, planning="auto").planned)
        self.assertEqual(self.agent(trivial, planning="auto").policy_flow, "direct")
        self.assertTrue(self.agent(remote, planning="auto").planned)
        self.assertTrue(self.agent(trivial, planning="on").planned)
        self.assertFalse(self.agent(remote, planning="off").planned)

    def test_auto_planning_depends_on_the_executor_tier(self) -> None:
        simple = {"objective": "x", "files_touched_estimate": 2}
        trivial = {"objective": "x", "files_touched_estimate": 1}
        economy = self.agent(simple, planning="auto", executor_tier="economy")
        premium = self.agent(simple, planning="auto", executor_tier="premium")
        routed = self.agent(simple, planning="auto")
        self.assertEqual((economy.executor_tier, economy.planned), ("economy", True))
        self.assertEqual((premium.executor_tier, premium.planned), ("premium", False))
        self.assertEqual((routed.executor_tier, routed.planned), ("standard", False))
        self.assertFalse(self.agent(trivial, planning="auto", executor_tier="economy").planned)
        self.assertTrue(self.agent(simple, planning="on", executor_tier="premium").planned)
        self.assertFalse(self.agent(simple, planning="off", executor_tier="economy").planned)

    def test_auto_executor_tier_follows_fixed_routing(self) -> None:
        simple = {"objective": "x", "files_touched_estimate": 2}
        fixed = self.agent(simple, planning="auto", routing="fixed", fixed_tier="economy")
        self.assertEqual((fixed.executor_tier, fixed.planned), ("economy", True))

    def test_tool_profile_lists_the_reference_tools_it_offers(self) -> None:
        simple = {"objective": "x", "files_touched_estimate": 2}
        full = ("Read", "Grep", "Glob", "Edit", "Write", "Bash")
        structured = self.agent(simple)
        lean = self.agent(simple, tool_profile="lean")
        self.assertEqual((structured.tool_profile, structured.tools), ("structured", full))
        self.assertEqual((lean.tool_profile, lean.tools), ("lean", ("Read", "Edit", "Bash")))
        strong = self.agent(simple, tool_profile="auto", executor_tier="premium")
        weak = self.agent(simple, tool_profile="auto", executor_tier="economy")
        self.assertEqual((strong.tool_profile, weak.tool_profile), ("lean", "structured"))

    def test_profile_choices_are_validated(self) -> None:
        for bad in ({"executor_tier": "gold"}, {"tool_profile": "bash"}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_configs({"configs": [{"id": "c", **bad}]})

    def test_parallelism_needs_a_plan_and_independent_subtasks(self) -> None:
        many = {"objective": "x", "independent_subtasks": 3}
        single = {"objective": "x", "independent_subtasks": 1}
        self.assertEqual(self.agent(many, max_parallel=3).max_parallel, 3)
        self.assertEqual(self.agent(single, max_parallel=3).max_parallel, 1)
        self.assertEqual(self.agent(many, max_parallel=3, planning="off").max_parallel, 1)


if __name__ == "__main__":
    unittest.main()
