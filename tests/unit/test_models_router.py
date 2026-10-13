from __future__ import annotations

import unittest

from wev_skills.config import ModelsConfig, TiersConfig
from wev_skills.core.contracts import Classification, Complexity, RiskLevel
from wev_skills.core.errors import ProviderError, ValidationError
from wev_skills.models.router import ModelRouter

CFG = ModelsConfig(TiersConfig(("e1", "e2"), ("s1",), ("p1", "p2")))


def cls(risk: RiskLevel = RiskLevel.LOW, cx: Complexity = Complexity.SIMPLE) -> Classification:
    return Classification(cx, risk, 0.0, False, (), "t")


class BaseTierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.r = ModelRouter(CFG)

    def test_base_tiers(self) -> None:
        self.assertEqual(self.r.select(cls(cx=Complexity.TRIVIAL)).tier, "economy")
        self.assertEqual(self.r.select(cls()).tier, "standard")
        self.assertEqual(self.r.select(cls(RiskLevel.MEDIUM, Complexity.TRIVIAL)).tier, "standard")
        self.assertEqual(self.r.select(cls(RiskLevel.HIGH)).tier, "premium")
        self.assertEqual(self.r.select(cls(cx=Complexity.COMPLEX)).tier, "premium")

    def test_attempt_escalation(self) -> None:
        trivial = cls(cx=Complexity.TRIVIAL)
        self.assertEqual(self.r.select(trivial, attempt=1).tier, "economy")
        self.assertEqual(self.r.select(trivial, attempt=2).tier, "standard")
        self.assertEqual(self.r.select(trivial, attempt=3).tier, "premium")
        self.assertEqual(self.r.select(trivial, attempt=9).tier, "premium")
        self.assertEqual(self.r.select(cls(RiskLevel.HIGH), attempt=5).tier, "premium")

    def test_reasons_present(self) -> None:
        choice = self.r.select(cls(cx=Complexity.TRIVIAL), attempt=2)
        self.assertGreaterEqual(len(choice.reasons), 3)


class AvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.r = ModelRouter(CFG)

    def test_first_available_in_tier(self) -> None:
        self.assertEqual(self.r.select(cls(RiskLevel.HIGH), unavailable=("p1",)).model, "p2")

    def test_whole_tier_unavailable_goes_up_then_down(self) -> None:
        up = self.r.select(cls(cx=Complexity.TRIVIAL), unavailable=("e1", "e2"))
        self.assertEqual((up.model, up.tier), ("s1", "standard"))
        down = self.r.select(cls(RiskLevel.HIGH), unavailable=("p1", "p2"))
        self.assertEqual((down.model, down.tier), ("s1", "standard"))
        down2 = self.r.select(cls(RiskLevel.HIGH), unavailable=("p1", "p2", "s1"))
        self.assertEqual(down2.tier, "economy")

    def test_none_available(self) -> None:
        with self.assertRaises(ProviderError):
            self.r.select(cls(), unavailable=("e1", "e2", "s1", "p1", "p2"))


class AgentConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.r = ModelRouter(CFG)

    def test_pinned_model(self) -> None:
        choice = self.r.select(cls(), agent_model="custom-x")
        self.assertEqual((choice.model, choice.tier), ("custom-x", "pinned"))
        self.assertEqual(self.r.select(cls(), agent_model="p2").tier, "premium")

    def test_pinned_unavailable_falls_back_to_tier(self) -> None:
        choice = self.r.select(cls(), agent_model="custom-x", unavailable=("custom-x",))
        self.assertEqual(choice.model, "s1")
        self.assertTrue(any("custom-x" in r for r in choice.reasons))

    def test_bounds_clamp(self) -> None:
        self.assertEqual(
            self.r.select(cls(RiskLevel.HIGH), agent_tier_bounds=("economy", "standard")).tier,
            "standard",
        )
        self.assertEqual(
            self.r.select(cls(), agent_tier_bounds=("premium", "premium")).tier, "premium"
        )

    def test_bounds_limit_fallback(self) -> None:
        with self.assertRaises(ProviderError):
            self.r.select(cls(), agent_tier_bounds=("standard", "standard"), unavailable=("s1",))

    def test_bad_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            self.r.select(cls(), agent_tier_bounds=("premium", "economy"))
        with self.assertRaises(ValidationError):
            self.r.select(cls(), agent_tier_bounds=("gold", "economy"))


if __name__ == "__main__":
    unittest.main()
