import unittest

from wev_skills.evaluation.ratchet import improves, not_lower


class RatchetTest(unittest.TestCase):
    def test_enters_when_nothing_regresses_and_total_rises(self) -> None:
        self.assertTrue(improves({"a": 1, "b": 0}, {"a": 1, "b": 1}))

    def test_tie_does_not_enter(self) -> None:
        self.assertFalse(improves({"a": 1, "b": 1}, {"a": 1, "b": 1}))

    def test_regression_blocks_even_with_higher_total(self) -> None:
        self.assertFalse(improves({"a": 2, "b": 0}, {"a": 1, "b": 3}))

    def test_different_keys_never_improve(self) -> None:
        self.assertFalse(improves({"a": 0}, {"a": 1, "b": 1}))
        self.assertFalse(improves({"a": 0, "b": 0}, {"a": 1}))

    def test_not_lower_accepts_a_tie_and_a_rise(self) -> None:
        self.assertTrue(not_lower({"a": 1, "b": 1}, {"a": 1, "b": 1}))
        self.assertTrue(not_lower({"a": 1, "b": 0}, {"a": 1, "b": 2}))

    def test_not_lower_rejects_a_lost_pass_even_with_a_higher_total(self) -> None:
        self.assertFalse(not_lower({"a": 2, "b": 0}, {"a": 1, "b": 3}))

    def test_not_lower_needs_the_same_cases(self) -> None:
        self.assertFalse(not_lower({"a": 0}, {"a": 1, "b": 1}))
        self.assertFalse(not_lower({"a": 0, "b": 0}, {"a": 1}))


if __name__ == "__main__":
    unittest.main()
