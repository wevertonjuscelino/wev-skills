"""Ranking against the agent's own average: only demote, only with enough evidence."""

from __future__ import annotations

import unittest
from typing import Any

from tests.unit._agent_helpers import make
from tests.unit.test_agents_experience import lesson
from wev_skills.agents.experience import Lesson, active_lessons, adjusted_rate, pooled_rate


def lessons(*items: dict[str, Any]) -> tuple[Lesson, ...]:
    return make("worker", experience=list(items)).experience


def used(lesson_id: str, confirmations: int, verified: int, unverified: int) -> dict[str, Any]:
    return lesson(
        lesson_id,
        confirmations=confirmations,
        shown_verified=verified,
        shown_unverified=unverified,
    )


def order(items: tuple[Lesson, ...]) -> list[str]:
    return [item.id for item in active_lessons(items)]


class BalanceTests(unittest.TestCase):
    def test_the_average_pools_every_active_lesson(self) -> None:
        found = lessons(used("a", 1, 8, 2), used("b", 1, 0, 10))
        self.assertAlmostEqual(pooled_rate(found) or 0.0, 0.4)
        self.assertIsNone(pooled_rate(lessons(used("a", 1, 0, 0))))

    def test_few_samples_stay_near_the_average(self) -> None:
        self.assertAlmostEqual(adjusted_rate(lessons(used("a", 1, 0, 1))[0], 0.8), 0.6)
        self.assertAlmostEqual(adjusted_rate(lessons(used("a", 1, 0, 0))[0], 0.8), 0.8)

    def test_a_lesson_clearly_below_the_average_is_demoted(self) -> None:
        found = lessons(
            used("weak", 9, 0, 6),
            used("good", 1, 9, 1),
            used("fine", 2, 8, 2),
        )
        self.assertEqual(order(found), ["fine", "good", "weak"])

    def test_too_few_samples_never_demote(self) -> None:
        found = lessons(used("new", 9, 0, 2), used("good", 1, 9, 1))
        self.assertEqual(order(found), ["new", "good"])

    def test_a_good_rate_never_promotes_past_confirmations(self) -> None:
        found = lessons(used("star", 1, 10, 0), used("plain", 5, 8, 2))
        self.assertEqual(order(found), ["plain", "star"])

    def test_the_bar_follows_the_agent_average(self) -> None:
        middling = used("mid", 9, 2, 3)
        high_peers = lessons(middling, used("p", 1, 19, 1))
        low_peers = lessons(middling, used("p", 1, 3, 17))
        self.assertEqual(order(high_peers), ["p", "mid"])
        self.assertEqual(order(low_peers), ["mid", "p"])

    def test_without_usage_the_order_is_unchanged(self) -> None:
        found = lessons(lesson("a", confirmations=1), lesson("b", confirmations=5))
        self.assertEqual(order(found), ["b", "a"])


if __name__ == "__main__":
    unittest.main()
