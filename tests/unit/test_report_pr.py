"""``wev run report --format pr`` prints the sections of the pull request template."""

from __future__ import annotations

import unittest
from typing import Any

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.core.report_pr import render_pr

HEADINGS = ("## Summary", "## What was tested", "## Risk", "## How to revert", "## Review")


def report(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "objective": "Add a greeting",
        "tasks": [{"id": "a", "checks_run": [{"command": "make test", "state": "passed"}]}],
        "risk_notes": "Touches the login path.",
        "revert": "git revert abc123",
        "review": {"summary": "Nothing open.", "dismissed": []},
    }
    return {**base, **over}


class RenderPrTests(unittest.TestCase):
    def test_pr_body_sections_in_order(self) -> None:
        body = render_pr(report(), "en")
        positions = [body.index(h) for h in HEADINGS]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("`make test` (a): passed", body)
        self.assertIn("git revert abc123", body)

    def test_pr_body_lists_dismissed_findings(self) -> None:
        dismissed = [{"id": "f1", "tag": "nit", "outcome": "intentional", "reason": "by design"}]
        body = render_pr(report(review={"summary": "x", "dismissed": dismissed}), "pt-BR")
        self.assertIn("f1 [nit] intentional: by design", body)

    def test_blank_notes_say_so_and_control_characters_are_stripped(self) -> None:
        body = render_pr(report(revert="", risk_notes="a\x1b[31mred\x07"), "en")
        self.assertIn("Not given.", body)
        self.assertIn("ared", body)
        self.assertNotIn("\x1b", body)
        self.assertNotIn("\x07", body)


class BuiltReportTests(OrchestratorCase):
    def test_report_carries_notes_and_review(self) -> None:
        self.start()
        self.set_plan({"id": "a"})
        built = self.orch().report("en")
        self.assertEqual(built["revert"], "git revert the commit.")
        self.assertEqual(built["review"]["dismissed"], [])
        self.assertIn("## Review", render_pr(built, "en"))
