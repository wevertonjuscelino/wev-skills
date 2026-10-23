"""``wev run report --format pr`` prints the sections of the pull request template."""

from __future__ import annotations

import re
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.core.report_pr import render_pr
from wev_skills.state.review_records import FindingRecord, ReviewRoundRecord

HEADINGS = ("## Summary", "## What was tested", "## Risk", "## How to revert", "## Review")


def report(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "objective": "Add a greeting",
        "tasks": [{"id": "a", "checks_run": [{"command": "make test", "state": "passed"}]}],
        "risk_notes": "Touches the login path.",
        "revert": "git revert abc123",
        "review": {"summary": "", "skipped": 0, "open": [], "dismissed": []},
        "classification": {"risk": "medium", "reasons": ["touches the login path"]},
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
        body = render_pr(
            report(review={"summary": "", "skipped": 0, "open": [], "dismissed": dismissed}),
            "pt-BR",
        )
        self.assertIn("f1 [nit] intentional: by design", body)

    def test_risk_section_has_the_tier_and_reasons_before_the_notes(self) -> None:
        body = render_pr(report(), "en")
        tier, reason, notes = (
            body.index(t) for t in ("Risk tier: medium", "login path", "Touches")
        )
        self.assertLess(tier, reason)
        self.assertLess(reason, notes)

    def test_template_has_risk_revert_review(self) -> None:
        path = Path(__file__).parents[2] / ".github" / "PULL_REQUEST_TEMPLATE.md"
        template = re.findall(r"^## (.+)$", path.read_text(), re.M)
        printed = re.findall(r"^## (.+)$", render_pr(report(), "en"), re.M)
        self.assertEqual([h for h in template if h in printed], printed)
        self.assertEqual(printed, [h.removeprefix("## ") for h in HEADINGS])

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

    def test_findings_render_one_line_each_and_cannot_forge_a_heading(self) -> None:
        def finding(fid: str, tag: str, title: str) -> FindingRecord:
            return FindingRecord(fid, 1, "a.py", 3, title, "b", tag, False, 2, 3)

        found = (
            finding("f1", "important", "bad\n## Fake\x1b[31m\n- injected"),
            finding("f2", "nit", "naming"),
        )
        rnd = ReviewRoundRecord(1, "t", "full", "tree", "fp", "standard", found, skipped=2)
        self.start()
        self.set_plan({"id": "a"})
        self.orch().commit(lambda s: replace(s, review_rounds=(rnd,)), "x", {})
        body = render_pr(self.orch().report("en"), "en")
        self.assertEqual(re.findall(r"^## .+$", body, re.M), list(HEADINGS))
        self.assertNotIn("\x1b", body)
        self.assertNotRegex(body, r"(?m)^- injected")
        self.assertIn("- a.py:3 [Important] bad ## Fake - injected", body)
        self.assertIn("1 Important, 1 Nit", body)
        self.assertIn("2 skipped by REVIEW.md", body)
