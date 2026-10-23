"""The ``review`` configuration section."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wev_skills.config import Config, parse_config, resolve_config
from wev_skills.config_review import ReviewConfig, ReviewShape, review_shape
from wev_skills.core.contracts import RiskLevel
from wev_skills.core.errors import ValidationError


class ReviewConfigTests(unittest.TestCase):
    def resolve(self, review: dict[str, object]) -> Config:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "wev.config.json"
            path.write_text(json.dumps({"review": review}), encoding="utf-8")
            return resolve_config(str(path), root).config

    def test_defaults_are_off(self) -> None:
        review = Config().review
        self.assertEqual((review.agent, review.depth), ("", "off"))
        self.assertEqual((review.finders, review.verifiers, review.quorum), (0, 0, 0))
        self.assertEqual((review.max_rounds, review.full_rounds), (3, 2))
        self.assertEqual((review.max_runs_per_round, review.timeout_seconds), (12, 600.0))
        self.assertEqual(review_shape(review, RiskLevel.HIGH), ReviewShape(0, 0, 0))

    def test_presets(self) -> None:
        expected = {"quick": (1, 1, 1), "standard": (3, 3, 2), "deep": (5, 5, 3)}
        for depth, shape in expected.items():
            with self.subTest(depth=depth):
                got = review_shape(ReviewConfig(depth=depth), RiskLevel.LOW)
                self.assertEqual((got.finders, got.verifiers, got.quorum), shape)

    def test_high_risk_raises_quick_to_standard(self) -> None:
        quick = ReviewConfig(depth="quick")
        self.assertEqual(review_shape(quick, RiskLevel.HIGH), ReviewShape(3, 3, 2))
        self.assertEqual(review_shape(quick, RiskLevel.MEDIUM), ReviewShape(1, 1, 1))
        deep = ReviewConfig(depth="deep")
        self.assertEqual(review_shape(deep, RiskLevel.HIGH), ReviewShape(5, 5, 3))

    def test_explicit_keys_override(self) -> None:
        config = ReviewConfig(depth="standard", finders=2, verifiers=4, quorum=4)
        self.assertEqual(review_shape(config, RiskLevel.LOW), ReviewShape(2, 4, 4))
        partial = ReviewConfig(depth="deep", quorum=1)
        self.assertEqual(review_shape(partial, RiskLevel.LOW), ReviewShape(5, 5, 1))

    def test_depth_on_needs_agent(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            self.resolve({"depth": "quick"})
        self.assertIn("review.agent", caught.exception.message)
        config = self.resolve({"depth": "quick", "agent": "reviewer"})
        self.assertEqual(config.review.depth, "quick")

    def test_quorum_above_verifiers_refused(self) -> None:
        for review in (
            {"depth": "quick", "agent": "a", "quorum": 2},
            {"depth": "deep", "agent": "a", "verifiers": 1},
            {"verifiers": 1, "quorum": 2},
        ):
            with self.subTest(review=review), self.assertRaises(ValidationError):
                self.resolve(review)
        self.assertEqual(self.resolve({"verifiers": 2, "quorum": 2}).review.quorum, 2)

    def test_unknown_key_refused(self) -> None:
        with self.assertRaises(ValidationError):
            parse_config(None, {"review": {"unknown": 1}})

    def test_values_outside_the_bounds_are_refused(self) -> None:
        bad = (
            {"depth": "maximum"},
            {"finders": 11},
            {"verifiers": -1},
            {"quorum": 11},
            {"max_rounds": 0},
            {"max_rounds": 11},
            {"full_rounds": 11},
            {"max_runs_per_round": 0},
            {"max_runs_per_round": 51},
            {"timeout_seconds": 0},
            {"timeout_seconds": 3600.5},
        )
        for review in bad:
            with self.subTest(review=review), self.assertRaises(ValidationError):
                parse_config(None, {"review": review})


if __name__ == "__main__":
    unittest.main()
