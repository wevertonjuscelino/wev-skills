from __future__ import annotations

import json
import unittest
from dataclasses import dataclass

from wev_skills import i18n
from wev_skills.config import HarnessSettings, LimitsConfig
from wev_skills.core.contracts import (
    AttemptRecord,
    Complexity,
    Evidence,
    EvidenceLabel,
    Flow,
    GuardAction,
    Mode,
    PlanTask,
    RiskLevel,
    TaskContract,
    TaskResult,
    TaskSignals,
    TaskStatus,
    Verdict,
)
from wev_skills.core.errors import NotFound, ValidationError
from wev_skills.decisions.local import LocalPolicyProvider


@dataclass(frozen=True)
class FakeAgent:
    id: str
    description: str = ""
    specialties: tuple[str, ...] = ()


def sig(**kw: object) -> TaskSignals:
    return TaskSignals(objective="do it", **kw)  # type: ignore[arg-type]


def contract() -> TaskContract:
    return TaskContract("t", "o", "", (), (), (), (), (), "", (), "a", "m", RiskLevel.LOW)


def ev(label: EvidenceLabel, exit_code: int | None = 0, kind: str = "command") -> Evidence:
    return Evidence(kind, "s", exit_code=exit_code, label=label)


def attempt(n: int, sig_: str = "", status: TaskStatus = TaskStatus.FAILED) -> AttemptRecord:
    return AttemptRecord("t", n, status, "m", sig_)


class RiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = LocalPolicyProvider(LimitsConfig())

    def risk(self, **kw: object) -> RiskLevel:
        return self.p.classify_task(sig(**kw)).risk

    def test_high_triggers(self) -> None:
        for kw in (
            {"touches_production": True},
            {"destructive": True},
            {"external_side_effects": True},
            {"touches_remote": True, "reversible": False},
        ):
            self.assertEqual(self.risk(**kw), RiskLevel.HIGH, kw)

    def test_medium_triggers(self) -> None:
        for kw in (
            {"touches_remote": True},
            {"reversible": False},
            {"files_touched_estimate": 6},
            {"has_tests": False, "files_touched_estimate": 2},
        ):
            self.assertEqual(self.risk(**kw), RiskLevel.MEDIUM, kw)

    def test_low_boundaries(self) -> None:
        self.assertEqual(self.risk(files_touched_estimate=5), RiskLevel.LOW)
        self.assertEqual(self.risk(has_tests=False, files_touched_estimate=1), RiskLevel.LOW)

    def test_reason_per_fired_rule(self) -> None:
        c = self.p.classify_task(sig(touches_production=True, destructive=True))
        risk_reasons = [r for r in c.reasons if r.startswith("High risk")]
        self.assertEqual(len(risk_reasons), 2)
        self.assertEqual(c.source, "local-policy")


class ComplexityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = LocalPolicyProvider(LimitsConfig())

    def cx(self, **kw: object) -> Complexity:
        return self.p.classify_task(sig(**kw)).complexity

    def test_levels(self) -> None:
        self.assertEqual(self.cx(files_touched_estimate=1), Complexity.TRIVIAL)
        self.assertEqual(self.cx(files_touched_estimate=1, unknowns=1), Complexity.SIMPLE)
        self.assertEqual(
            self.cx(files_touched_estimate=1, independent_subtasks=2), Complexity.SIMPLE
        )
        self.assertEqual(self.cx(files_touched_estimate=3), Complexity.SIMPLE)
        self.assertEqual(self.cx(files_touched_estimate=4), Complexity.MODERATE)
        self.assertEqual(self.cx(files_touched_estimate=10, unknowns=3), Complexity.MODERATE)
        self.assertEqual(self.cx(files_touched_estimate=11), Complexity.COMPLEX)
        self.assertEqual(self.cx(unknowns=4), Complexity.COMPLEX)

    def test_uncertainty_and_parallel(self) -> None:
        c = self.p.classify_task(sig(unknowns=2, has_tests=False, independent_subtasks=3))
        self.assertAlmostEqual(c.uncertainty, 0.6)
        self.assertTrue(c.parallelizable)
        self.assertEqual(self.p.classify_task(sig(unknowns=10)).uncertainty, 1.0)
        self.assertFalse(self.p.classify_task(sig()).parallelizable)

    def test_invalid_signals(self) -> None:
        with self.assertRaises(ValidationError):
            self.p.classify_task(sig(unknowns=-1))
        with self.assertRaises(ValidationError):
            self.p.classify_task(sig(independent_subtasks=0))


class StrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = LocalPolicyProvider(LimitsConfig(max_parallel=4, max_attempts=5))

    def strat(self, mode: Mode = Mode.AUTO, **kw: object):  # type: ignore[no-untyped-def]
        return self.p.select_strategy(self.p.classify_task(sig(**kw)), mode)

    def test_direct_for_small_low_risk(self) -> None:
        s = self.strat()
        self.assertEqual(s.flow, Flow.DIRECT)
        self.assertFalse(s.needs_plan or s.needs_independent_review or s.needs_approval)
        self.assertEqual((s.max_parallel, s.max_attempts), (1, 5))

    def test_gated_for_high_risk(self) -> None:
        s = self.strat(destructive=True)
        self.assertEqual(s.flow, Flow.GATED)
        self.assertTrue(s.needs_approval and s.needs_independent_review and s.needs_plan)

    def test_planned_with_review_rules(self) -> None:
        medium = self.strat(touches_remote=True)
        self.assertEqual(medium.flow, Flow.PLANNED)
        self.assertTrue(medium.needs_independent_review)
        moderate = self.strat(files_touched_estimate=4)
        self.assertEqual(moderate.flow, Flow.PLANNED)
        self.assertFalse(moderate.needs_independent_review)
        self.assertTrue(self.strat(files_touched_estimate=20).needs_independent_review)

    def test_plan_mode_and_parallel(self) -> None:
        s = self.strat(Mode.PLAN, independent_subtasks=3, destructive=True)
        self.assertEqual(s.flow, Flow.PLANNED)
        self.assertTrue(s.needs_plan)
        self.assertEqual(s.max_parallel, 4)
        self.assertTrue(all(isinstance(r, str) and r for r in s.reasons))


SMALL = {"files_touched_estimate": 2}
"""Low risk, SIMPLE complexity: the class of task on which the tiers differ."""


class CapabilityStrategyTests(unittest.TestCase):
    def strat(self, tier: str, planning: str = "auto", mode: Mode = Mode.AUTO, **kw: object):  # type: ignore[no-untyped-def]
        provider = LocalPolicyProvider(LimitsConfig(), HarnessSettings(planning=planning))
        return provider.select_strategy(provider.classify_task(sig(**kw)), mode, tier)

    def test_economy_plans_anything_above_trivial(self) -> None:
        simple = self.strat("economy", **SMALL)
        self.assertEqual((simple.flow, simple.needs_plan), (Flow.PLANNED, True))
        trivial = self.strat("economy", files_touched_estimate=1)
        self.assertEqual((trivial.flow, trivial.needs_plan), (Flow.DIRECT, False))

    def test_standard_keeps_the_rule_that_existed_before_tiers(self) -> None:
        legacy = LocalPolicyProvider(LimitsConfig())
        for kw in ({}, SMALL, {"files_touched_estimate": 4}, {"touches_remote": True}):
            with self.subTest(kw=kw):
                classification = legacy.classify_task(sig(**kw))
                implicit = legacy.select_strategy(classification, Mode.AUTO)
                explicit = self.strat("standard", **kw)
                self.assertEqual(
                    (implicit.flow, implicit.needs_plan), (explicit.flow, explicit.needs_plan)
                )
        self.assertFalse(self.strat("standard", **SMALL).needs_plan)
        self.assertTrue(self.strat("standard", files_touched_estimate=4).needs_plan)

    def test_premium_plans_only_from_moderate_up_or_above_low_risk(self) -> None:
        self.assertFalse(self.strat("premium", files_touched_estimate=1).needs_plan)
        self.assertFalse(self.strat("premium", **SMALL).needs_plan)
        self.assertTrue(self.strat("premium", files_touched_estimate=4).needs_plan)
        self.assertTrue(self.strat("premium", files_touched_estimate=20).needs_plan)
        self.assertTrue(self.strat("premium", touches_remote=True, **SMALL).needs_plan)

    def test_always_and_never_override_the_tier_rule(self) -> None:
        for tier in ("economy", "standard", "premium"):
            with self.subTest(tier=tier):
                always = self.strat(tier, "always", files_touched_estimate=1)
                self.assertEqual((always.flow, always.needs_plan), (Flow.PLANNED, True))
                never = self.strat(tier, "never", files_touched_estimate=20, touches_remote=True)
                self.assertEqual((never.flow, never.needs_plan), (Flow.DIRECT, False))

    def test_gated_and_plan_mode_flows_always_have_a_plan(self) -> None:
        for tier in ("economy", "standard", "premium"):
            with self.subTest(tier=tier):
                gated = self.strat(tier, "never", destructive=True)
                self.assertEqual((gated.flow, gated.needs_plan), (Flow.GATED, True))
                planned = self.strat(tier, "never", Mode.PLAN)
                self.assertEqual((planned.flow, planned.needs_plan), (Flow.PLANNED, True))

    def test_risk_approval_and_review_do_not_depend_on_tier_or_planning(self) -> None:
        cases = ({}, SMALL, {"files_touched_estimate": 20}, {"touches_remote": True},
                 {"destructive": True})  # fmt: skip
        for kw in cases:
            seen = {
                (s.needs_approval, s.needs_independent_review, s.max_parallel, s.max_attempts)
                for tier in ("economy", "standard", "premium")
                for planning in ("auto", "always", "never")
                for s in (self.strat(tier, planning, **kw),)
            }
            with self.subTest(kw=kw):
                self.assertEqual(len(seen), 1)

    def test_reasons_name_the_tier_and_the_rule(self) -> None:
        for tier in ("economy", "standard", "premium"):
            for planning in ("auto", "always", "never"):
                with self.subTest(tier=tier, planning=planning):
                    reasons = " ".join(self.strat(tier, planning, **SMALL).reasons)
                    self.assertIn(f"Executor tier {tier}", reasons)
                    self.assertIn(f"planning {planning}", reasons)
        self.assertIn("anything above trivial", " ".join(self.strat("economy", **SMALL).reasons))
        gated = " ".join(self.strat("premium", "never", destructive=True).reasons)
        self.assertIn("Executor tier premium", gated)

    def test_an_unknown_tier_is_treated_as_standard(self) -> None:
        odd = self.strat("pinned", **SMALL)
        self.assertFalse(odd.needs_plan)
        self.assertIn("Executor tier standard", " ".join(odd.reasons))


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = LocalPolicyProvider(LimitsConfig())
        self.agents = [
            FakeAgent("zeta", "writes documentation", ("docs",)),
            FakeAgent("alpha", "fixes python bugs", ("python", "debugging")),
            FakeAgent("beta", "fixes python bugs", ("python", "debugging")),
        ]

    def test_hint_wins(self) -> None:
        task = PlanTask("1", "fix python bug", "debugging", agent_hint="zeta")
        self.assertEqual(self.p.route_agent(task, self.agents), "zeta")

    def test_unknown_hint_ignored_and_scored(self) -> None:
        task = PlanTask("1", "Fix the Python bug", "debugging", agent_hint="ghost")
        self.assertEqual(self.p.route_agent(task, self.agents), "alpha")

    def test_ties_break_by_id_and_zero_score_is_deterministic(self) -> None:
        task = PlanTask("1", "unrelated", "nothing")
        self.assertEqual(self.p.route_agent(task, self.agents), "alpha")
        self.assertEqual(self.p.route_agent(task, list(reversed(self.agents))), "alpha")

    def test_empty_raises(self) -> None:
        with self.assertRaises(NotFound):
            self.p.route_agent(PlanTask("1", "t", "o"), [])


class EvaluateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = LocalPolicyProvider(LimitsConfig())

    def judge(self, status: TaskStatus, *evidence: Evidence) -> Verdict:
        return self.p.evaluate_result(contract(), TaskResult("t", status, "s", evidence))

    def test_accepts_verified_tested(self) -> None:
        v = self.judge(TaskStatus.VERIFIED, ev(EvidenceLabel.TESTED), ev(EvidenceLabel.UNTESTED))
        self.assertTrue(v.accepted)
        self.assertAlmostEqual(v.score, 0.5)

    def test_rejections(self) -> None:
        self.assertFalse(self.judge(TaskStatus.VERIFIED).accepted)
        self.assertEqual(self.judge(TaskStatus.VERIFIED).score, 0.0)
        self.assertFalse(self.judge(TaskStatus.PARTIAL, ev(EvidenceLabel.TESTED)).accepted)
        self.assertFalse(self.judge(TaskStatus.VERIFIED, ev(EvidenceLabel.MOCKED)).accepted)
        bad = self.judge(
            TaskStatus.VERIFIED, ev(EvidenceLabel.TESTED), ev(EvidenceLabel.UNTESTED, 1)
        )
        self.assertFalse(bad.accepted)
        self.assertTrue(bad.reasons)

    def test_failing_tested_command_not_supporting(self) -> None:
        v = self.judge(TaskStatus.VERIFIED, ev(EvidenceLabel.TESTED, 2))
        self.assertFalse(v.accepted)
        self.assertEqual(v.score, 0.0)

    def test_non_command_evidence_ignores_exit_code(self) -> None:
        v = self.judge(TaskStatus.VERIFIED, ev(EvidenceLabel.TESTED, 5, kind="file"))
        self.assertTrue(v.accepted)


class ConflictTests(unittest.TestCase):
    def test_resolution(self) -> None:
        p = LocalPolicyProvider(LimitsConfig())
        v = p.resolve_conflict(
            [Verdict(True, 0.9, ("a",)), Verdict(False, 0.4, ("b", "a")), Verdict(True, 1.0)]
        )
        self.assertFalse(v.accepted)
        self.assertEqual(v.score, 0.4)
        self.assertEqual(v.reasons, ("a", "b"))
        self.assertTrue(p.resolve_conflict([Verdict(True, 0.8), Verdict(True, 0.7)]).accepted)
        with self.assertRaises(ValidationError):
            p.resolve_conflict([])


class EscalationTests(unittest.TestCase):
    """The rule itself is covered in test_decisions_floor.EscalationRuleTests."""

    def setUp(self) -> None:
        self.p = LocalPolicyProvider(LimitsConfig(max_attempts=3))

    def act(self, *records: AttemptRecord) -> GuardAction:
        return self.p.should_escalate(records).action

    def test_ladder(self) -> None:
        self.assertEqual(self.act(), GuardAction.CONTINUE)
        self.assertEqual(self.act(attempt(0, "x")), GuardAction.CONTINUE)
        self.assertEqual(self.act(attempt(0, "x"), attempt(1, "y")), GuardAction.ESCALATE)
        self.assertEqual(self.act(attempt(0, "x"), attempt(1, "x")), GuardAction.ESCALATE)
        three = [attempt(0, "a"), attempt(1, "b"), attempt(2, "c")]
        self.assertEqual(self.act(*three), GuardAction.ASK_HUMAN)
        six = [attempt(i, str(i)) for i in range(6)]
        self.assertEqual(self.act(*six), GuardAction.ASK_HUMAN)

    def test_successes_are_not_failures(self) -> None:
        ok = attempt(2, "x", TaskStatus.VERIFIED)
        self.assertEqual(self.act(attempt(0, "x"), ok), GuardAction.CONTINUE)

    def test_escalation_is_decided_while_attempts_remain(self) -> None:
        decision = self.p.should_escalate([attempt(0, "a"), attempt(1, "b")])
        self.assertTrue(decision.escalate)


class CatalogTests(unittest.TestCase):
    def test_locale_key_parity_and_languages(self) -> None:
        files = {lang: i18n.LOCALES_DIR / f"decisions.{lang}.json" for lang in ("en", "pt-BR")}
        keys = {lang: set(json.loads(p.read_text(encoding="utf-8"))) for lang, p in files.items()}
        self.assertEqual(keys["en"], keys["pt-BR"])

    def test_reasons_follow_language(self) -> None:
        p = LocalPolicyProvider(LimitsConfig())
        with i18n.use_language("pt-BR"):
            c = p.classify_task(sig(destructive=True))
        self.assertTrue(any("Risco alto" in r for r in c.reasons))


if __name__ == "__main__":
    unittest.main()
