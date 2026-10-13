from __future__ import annotations

import unittest

from wev_skills.decisions.jev_tools import TOOL_PREFIX, build_questions
from wev_skills.tools.registry import ToolSpec


def question_text(description: str) -> str:
    questions = build_questions(["Write"], [ToolSpec(name="Write", description=description)], False)
    return str(questions[f"{TOOL_PREFIX}Write"]["instructions"])


class ToolQuestionTextTests(unittest.TestCase):
    def test_description_ending_in_a_period_has_no_period_before_the_mark(self) -> None:
        self.assertEqual(
            question_text("Create or overwrite a file."),
            "Does this task need the Write tool: Create or overwrite a file?",
        )

    def test_description_without_a_period_is_unchanged(self) -> None:
        self.assertEqual(
            question_text("Create or overwrite a file"),
            "Does this task need the Write tool: Create or overwrite a file?",
        )

    def test_trailing_punctuation_and_spaces_are_removed(self) -> None:
        self.assertEqual(
            question_text("Create a file. ; "),
            "Does this task need the Write tool: Create a file?",
        )

    def test_missing_description_gives_a_plain_question(self) -> None:
        self.assertEqual(question_text(""), "Does this task need the Write tool?")


if __name__ == "__main__":
    unittest.main()
