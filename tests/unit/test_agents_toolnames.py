"""Tool names: a scoped pattern is a form of its base tool for every rule."""

from __future__ import annotations

import unittest

from wev_skills.agents.toolnames import MUTATING_TOOLS, base_tool, covers, is_mutating


class BaseToolTests(unittest.TestCase):
    def test_a_scoped_pattern_is_a_form_of_its_base_tool(self) -> None:
        for name, base in (
            ("Write(*)", "Write"),
            ("Edit(src/**)", "Edit"),
            ("Bash(git status:*)", "Bash"),
            ("Read", "Read"),
            ("Edit ", "Edit"),
            ("Edit (x)", "Edit"),
            ("mcp__x__y", "mcp__x__y"),
        ):
            with self.subTest(name=name):
                self.assertEqual(base_tool(name), base)

    def test_mutating_tools_include_multi_edit(self) -> None:
        self.assertEqual(MUTATING_TOOLS, {"Edit", "Write", "MultiEdit", "NotebookEdit"})

    def test_scoped_and_wildcard_forms_of_a_mutating_tool_are_mutating(self) -> None:
        for name in ("Write(*)", "Edit(src/**)", "MultiEdit", "NotebookEdit(x)", "Edit ", "E*"):
            with self.subTest(name=name):
                self.assertTrue(is_mutating(name))
        for name in ("Read", "Bash(git status:*)", "WebFetch", "Editor"):
            with self.subTest(name=name):
                self.assertFalse(is_mutating(name))

    def test_covers_matches_the_entry_itself_or_its_unscoped_base(self) -> None:
        self.assertTrue(covers(["Bash"], "Bash(git status:*)"))
        self.assertTrue(covers(["Bash(git status:*)"], "Bash(git status:*)"))
        self.assertTrue(covers(["Edit"], "Edit "))
        self.assertFalse(covers(["Bash(git status:*)"], "Bash"))
        self.assertFalse(covers(["Bash(git status:*)"], "Bash(rm:*)"))
        self.assertFalse(covers(["Read"], "Bash"))


if __name__ == "__main__":
    unittest.main()
