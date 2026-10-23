"""The shipped cases name reproducing tests that must pass on the current tree."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from wev_skills.core.ports import SubprocessRunner
from wev_skills.evaluation.cases import load_cases
from wev_skills.evaluation.workspace import passed

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT_SECONDS = 300.0


class FirstCasesTest(unittest.TestCase):
    def test_each_case_passes_on_current_tree(self) -> None:
        env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "PYTHONPATH": "src"}
        cases = [c for c in load_cases(ROOT) if not c.head_commit]  # review cases have no check
        self.assertGreaterEqual(len(cases), 3)
        for case in cases:
            with self.subTest(case.id):
                result = SubprocessRunner().run(case.check, str(ROOT), TIMEOUT_SECONDS, env)
                self.assertTrue(passed(result), result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
