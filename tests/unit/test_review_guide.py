from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from wev_skills import cli, i18n
from wev_skills.core.errors import ValidationError
from wev_skills.review import guide

EN = """# Review

## What failure looks like
Money is lost.

## Skip
- docs/*
- `*.lock`

## Nits
max: 5
Prefer short names.

## Important
Check auth.
"""
PT = "## Como é uma falha\nDados perdidos.\n\n## Ignorar\n- vendor/*\n\n## IMPORTANTE\nAuth.\n"


class ParseTests(unittest.TestCase):
    def test_parses_english_headings(self) -> None:
        g = guide.parse_guide(EN)
        self.assertEqual(g.failure, "Money is lost.")
        self.assertEqual(g.skip, ("docs/*", "*.lock"))
        self.assertEqual((g.nit_cap, g.nits), (5, "Prefer short names."))
        self.assertEqual(g.important, "Check auth.")

    def test_parses_portuguese_headings(self) -> None:
        g = guide.parse_guide(PT)
        self.assertEqual((g.failure, g.skip), ("Dados perdidos.", ("vendor/*",)))
        self.assertEqual(g.important, "Auth.")
        self.assertEqual(g.nit_cap, 3)

    def test_missing_file_gives_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(guide.load_guide(Path(tmp)), guide.ReviewGuide())

    def test_bad_max_refused(self) -> None:
        for bad in ("max: 51", "max: x", "max: -1", "max:"):
            with self.assertRaises(ValidationError, msg=bad) as ctx:
                guide.parse_guide(f"## Nits\n{bad}\n")
            self.assertEqual(ctx.exception.code, "invalid_review_md")
            self.assertEqual(ctx.exception.details["line"], 2)

    def test_unknown_heading_refused(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            guide.parse_guide("## Other\n")
        self.assertEqual(ctx.exception.code, "invalid_review_md")

    def test_too_long_refused(self) -> None:
        with self.assertRaises(ValidationError):
            guide.parse_guide("x" * (guide.MAX_CHARS + 1))

    def test_symlink_out_of_repo_refused(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            Path(b, "x.md").write_text("## Skip\n- a\n")
            Path(a, "REVIEW.md").symlink_to(Path(b, "x.md"))
            with self.assertRaises(ValidationError):
                guide.load_guide(Path(a).resolve())

    def test_skip_glob_matches(self) -> None:
        g = guide.parse_guide(EN)
        self.assertTrue(guide.skipped("docs/a/b.md", g))
        self.assertTrue(guide.skipped("poetry.lock", g))
        self.assertFalse(guide.skipped("src/a.py", g))


class CommandTests(unittest.TestCase):
    def test_md_check_command_reports_ok_and_error(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        (root / ".git").mkdir()
        previous = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, previous)

        def run() -> tuple[int, str]:
            out = io.StringIO()
            with (
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(io.StringIO()),
                i18n.use_language("en"),
            ):
                return cli.main(["review", "md", "check"]), out.getvalue()

        code, out = run()
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["present"])
        (root / "REVIEW.md").write_text(EN)
        code, out = run()
        self.assertEqual((code, json.loads(out)["guide"]["nit_cap"]), (0, 5))
        (root / "REVIEW.md").write_text("## Nope\n")
        self.assertEqual(run()[0], 2)
