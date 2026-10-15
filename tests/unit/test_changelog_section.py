"""Tests for scripts/changelog_section.py."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "changelog_section.py"
CHANGELOG = SCRIPT.parents[1] / "CHANGELOG.md"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("changelog_section", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


changelog = _load()

SAMPLE = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-10-15

Second.

### Added

- two

## [0.1.0] - 2026-10-13

First.

## [0.0.1] - 2026-01-01

[Unreleased]: https://example.invalid/compare/v0.2.0...HEAD
[0.1.0]: https://example.invalid/releases/tag/v0.1.0
"""


class SectionTests(unittest.TestCase):
    def test_returns_the_body_up_to_the_next_heading(self) -> None:
        self.assertEqual("Second.\n\n### Added\n\n- two", changelog.section(SAMPLE, "0.2.0"))

    def test_the_last_section_stops_before_the_link_definitions(self) -> None:
        text = SAMPLE.replace("## [0.0.1] - 2026-01-01\n", "")
        self.assertEqual("First.", changelog.section(text, "0.1.0"))

    def test_a_missing_version_is_none(self) -> None:
        self.assertIsNone(changelog.section(SAMPLE, "9.9.9"))

    def test_an_empty_section_is_none(self) -> None:
        self.assertIsNone(changelog.section(SAMPLE, "0.0.1"))
        self.assertIsNone(changelog.section(SAMPLE, "Unreleased"))

    def test_a_version_prefix_does_not_match(self) -> None:
        self.assertIsNone(changelog.section(SAMPLE, "0.2"))

    def test_the_repository_changelog_has_the_current_version(self) -> None:
        from wev_skills import __version__

        self.assertIsNotNone(changelog.section(CHANGELOG.read_text(encoding="utf-8"), __version__))


class MainTests(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = changelog.main(["changelog_section.py", *args])
        return code, out.getvalue(), err.getvalue()

    def test_prints_the_section_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CHANGELOG.md"
            path.write_text(SAMPLE, encoding="utf-8")
            code, out, _ = self._run(["0.1.0", str(path)])
        self.assertEqual((0, "First.\n"), (code, out))

    def test_exits_nonzero_when_the_version_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CHANGELOG.md"
            path.write_text(SAMPLE, encoding="utf-8")
            code, out, err = self._run(["9.9.9", str(path)])
        self.assertEqual((1, ""), (code, out))
        self.assertIn("9.9.9", err)

    def test_exits_nonzero_when_the_file_is_unreadable(self) -> None:
        code, _, err = self._run(["0.1.0", "/nonexistent/CHANGELOG.md"])
        self.assertEqual(1, code)
        self.assertIn("cannot read", err)

    def test_wrong_argument_count_is_a_usage_error(self) -> None:
        self.assertEqual(2, self._run([])[0])


if __name__ == "__main__":
    unittest.main()
