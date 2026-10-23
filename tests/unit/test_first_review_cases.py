import unittest
from pathlib import Path

from wev_skills.evaluation import cases
from wev_skills.review.trees import touched_lines

ROOT = Path(__file__).resolve().parents[2]


class FirstReviewCasesTest(unittest.TestCase):
    def test_first_review_cases_are_consistent(self) -> None:
        review = [c for c in cases.load_cases(ROOT) if c.head_commit]
        bugs = [c for c in review if c.expect]
        self.assertEqual(len(bugs), 3)
        self.assertEqual(len(review) - len(bugs), 2)
        for case in review:
            self.assertEqual(case.agents, ("wev-reviewer",))
            diff = (ROOT / cases.CASES_DIR / case.id / "change.diff").read_text(encoding="utf-8")
            touched = touched_lines(diff)
            for e in case.expect:
                lines = touched.get(e.file, frozenset())
                self.assertTrue(any(e.first <= n <= e.last for n in lines), case.id)


if __name__ == "__main__":
    unittest.main()
