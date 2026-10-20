"""Tests for scripts/release_prep.py, release_changelog.py and collect_release_prs.py.

The release preparation runs on a temporary copy of the real target files, so a drifting pattern
in the repository breaks a test here before it breaks a release.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import release_changelog  # noqa: E402
import release_prep  # noqa: E402


def _load_collect():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "collect_release_prs", SCRIPTS / "collect_release_prs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = _load_collect()

PRS = [
    {
        "number": 12,
        "title": "feat(intake): add a thing",
        "url": "https://example.invalid/pull/12",
        "labels": [],
    },
    {
        "number": 10,
        "title": "fix: repair a thing",
        "url": "https://example.invalid/pull/10",
        "labels": [{"name": "bug"}],
    },
    {
        "number": 11,
        "title": "docs: explain",
        "url": "https://example.invalid/pull/11",
        "labels": [],
    },
    {
        "number": 13,
        "title": "refactor(core): tidy",
        "url": "https://example.invalid/pull/13",
        "labels": ["x"],
    },
    {
        "number": 14,
        "title": "fix: close a hole",
        "url": "https://example.invalid/pull/14",
        "labels": ["security"],
    },
    {
        "number": 15,
        "title": "no conventional prefix",
        "url": "https://example.invalid/pull/15",
        "labels": [],
    },
]


class ClassifyTests(unittest.TestCase):
    def pr(self, title: str, *labels: str) -> release_changelog.Pr:
        return release_changelog.Pr(1, title, "u", labels)

    def test_types_map_to_sections(self) -> None:
        cases = {
            "feat: a": "Added",
            "fix(x): a": "Fixed",
            "docs: a": "Documentation",
            "security: a": "Security",
            "refactor: a": "Changed",
            "perf: a": "Changed",
            "test: a": "Changed",
            "ci: a": "Changed",
            "chore: a": "Changed",
            "build: a": "Changed",
            "free text": "Changed",
        }
        for title, section in cases.items():
            self.assertEqual(section, release_changelog.classify(self.pr(title))[0], title)

    def test_security_label_wins_over_the_type(self) -> None:
        self.assertEqual("Security", release_changelog.classify(self.pr("feat: a", "security"))[0])

    def test_description_drops_type_and_scope(self) -> None:
        self.assertEqual("add it", release_changelog.classify(self.pr("feat(core)!: add it"))[1])

    def test_bad_entries_are_rejected(self) -> None:
        with self.assertRaises(release_changelog.PrepError):
            release_changelog.Pr.from_json({"number": "1", "title": "t", "url": "u"})
        with self.assertRaises(release_changelog.PrepError):
            release_changelog.Pr.from_json("text")


class ChangelogTests(unittest.TestCase):
    TEXT = (
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- hand written\n\n"
        "## [2.0.0] - 2026-10-15\n\nOld.\n\n### Added\n\n- old\n\n"
        "[Unreleased]: https://example.invalid/compare/v2.0.0...HEAD\n"
        "[2.0.0]: https://example.invalid/compare/v1.0.0...v2.0.0\n"
    )

    def prs(self) -> list[release_changelog.Pr]:
        return [release_changelog.Pr.from_json(item) for item in PRS]

    def test_section_links_and_unreleased_merge(self) -> None:
        out = release_changelog.update_changelog(self.TEXT, "3.0.0", "2026-11-01", self.prs())
        self.assertIn(
            "## [Unreleased]\n\n## [3.0.0] - 2026-11-01\n\n### Added\n\n- hand written\n- add a",
            out,
        )
        self.assertIn("- add a thing ([#12](https://example.invalid/pull/12))", out)
        self.assertIn("### Changed\n\n- tidy ([#13]", out)
        self.assertIn("- no conventional prefix ([#15]", out)
        self.assertIn("### Security\n\n- close a hole ([#14]", out)
        self.assertLess(out.index("### Fixed"), out.index("### Documentation"))
        self.assertIn("[Unreleased]: https://example.invalid/compare/v3.0.0...HEAD\n", out)
        self.assertIn("[3.0.0]: https://example.invalid/compare/v2.0.0...v3.0.0\n[2.0.0]: ", out)
        self.assertLess(out.index("## [3.0.0]"), out.index("## [2.0.0]"))

    def test_refuses_an_existing_version(self) -> None:
        with self.assertRaises(release_changelog.PrepError):
            release_changelog.update_changelog(self.TEXT, "2.0.0", "2026-11-01", [])

    def test_fails_loudly_without_the_compare_link(self) -> None:
        with self.assertRaises(release_changelog.PrepError):
            release_changelog.update_changelog("## [Unreleased]\n", "3.0.0", "2026-11-01", [])

    def test_empty_unreleased_with_no_prs_still_makes_a_section(self) -> None:
        text = "## [Unreleased]\n\n[Unreleased]: https://x.invalid/compare/v2.0.0...HEAD\n"
        out = release_changelog.update_changelog(text, "3.0.0", "2026-11-01", [])
        self.assertIn("## [3.0.0] - 2026-11-01", out)

    def test_output_is_readable_by_changelog_section(self) -> None:
        import changelog_section

        out = release_changelog.update_changelog(self.TEXT, "3.0.0", "2026-11-01", self.prs())
        body = changelog_section.section(out, "3.0.0")
        self.assertIsNotNone(body)
        self.assertIn("### Fixed", body or "")
        self.assertNotIn("[2.0.0]", body or "")


class MarkerTests(unittest.TestCase):
    def test_replaces_one_pair_only(self) -> None:
        text = "a <!-- wev:version -->1<!-- /wev:version --> b"
        self.assertEqual(
            "a <!-- wev:version -->2<!-- /wev:version --> b",
            release_prep.set_marker(text, "version", "2", "f"),
        )

    def test_fails_when_missing_or_duplicated(self) -> None:
        pair = "<!-- wev:version -->1<!-- /wev:version -->"
        for text in ("none", pair + pair):
            with self.assertRaises(release_changelog.PrepError):
                release_prep.set_marker(text, "version", "2", "f")

    def test_set_version_requires_a_single_match(self) -> None:
        with self.assertRaises(release_changelog.PrepError):
            release_prep.set_version(
                'version = "1"\nversion = "2"\n', r'(?m)^version = "([^"]+)"$', "3", "f"
            )


class EndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        names = (
            [n for n, _ in release_prep.REGEX_TARGETS]
            + list(release_prep.MARKER_FILES)
            + ["CHANGELOG.md"]
        )
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, target)
        self.prs = self.root / "prs.json"
        self.prs.write_text(json.dumps(PRS), encoding="utf-8")

    def run_prep(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "release_prep.py"),
                "--root",
                str(self.root),
                "--date",
                "2026-11-01",
                "--prs",
                str(self.prs),
                *extra,
            ],
            capture_output=True,
            text=True,
        )

    def read(self, name: str) -> str:
        return (self.root / name).read_text(encoding="utf-8")

    def test_rewrites_every_target(self) -> None:
        result = self.run_prep("--version", "9.0.0")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('version = "9.0.0"', self.read("pyproject.toml"))
        self.assertEqual("9.0.0", json.loads(self.read(".claude-plugin/plugin.json"))["version"])
        self.assertIn('__version__ = "9.0.0"', self.read("src/wev_skills/__init__.py"))
        for name in ("docs/guides/installation.md", "docs/guides/installation.pt-BR.md"):
            self.assertIn('  "version": "9.0.0"', self.read(name))
        for name in ("README.md", "README.pt-BR.md"):
            self.assertIn("<!-- wev:version -->9.0.0<!-- /wev:version -->", self.read(name))
        claude = self.read("CLAUDE.md")
        self.assertIn("<!-- wev:release-date -->2026-11-01<!-- /wev:release-date -->", claude)
        self.assertIn("## [9.0.0] - 2026-11-01", self.read("CHANGELOG.md"))

    def test_status_blocks_are_localized_and_link_the_release(self) -> None:
        self.run_prep("--version", "9.0.0", "--milestone-url", "https://example.invalid/m/4")
        roadmap = self.read("ROADMAP.md")
        self.assertIn(
            "Latest release: [v9.0.0]("
            + release_prep.REPOSITORY_URL
            + "/releases/tag/v9.0.0), published on 2026-11-01.",
            roadmap,
        )
        self.assertIn("[v10.0.0](https://example.invalid/m/4)", roadmap)
        self.assertIn("Última versão publicada: [v9.0.0]", self.read("ROADMAP.pt-BR.md"))
        mvp = self.read("docs/mvp-status.md")
        self.assertIn("Latest release: [v9.0.0]", mvp)
        self.assertNotIn(
            "milestone",
            mvp.split("<!-- /wev:release-status -->")[0].split("<!-- wev:release-status -->")[1],
        )

    def test_second_run_is_refused_and_changes_nothing(self) -> None:
        self.assertEqual(0, self.run_prep("--version", "9.0.0").returncode)
        before = self.read("CHANGELOG.md")
        result = self.run_prep("--version", "9.0.0")
        self.assertEqual(1, result.returncode)
        self.assertIn("already has version", result.stderr)
        self.assertEqual(before, self.read("CHANGELOG.md"))

    def test_a_missing_pattern_aborts_before_any_write(self) -> None:
        (self.root / "README.md").write_text("no marker here\n", encoding="utf-8")
        before = self.read("pyproject.toml")
        result = self.run_prep("--version", "9.0.0")
        self.assertEqual(1, result.returncode)
        self.assertIn("README.md", result.stderr)
        self.assertEqual(before, self.read("pyproject.toml"))

    def test_rejects_bad_version_and_date(self) -> None:
        self.assertEqual(1, self.run_prep("--version", "v9.0").returncode)
        bad = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "release_prep.py"),
                "--root",
                str(self.root),
                "--version",
                "9.0.0",
                "--date",
                "tomorrow",
                "--prs",
                str(self.prs),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, bad.returncode)


class CollectTests(unittest.TestCase):
    def test_pr_numbers_are_oldest_first_and_filter_other_merges(self) -> None:
        subjects = [
            "Merge pull request #7 from owner/feature-b",
            "Merge branch 'dev' into feature",
            "Merge pull request #3 from owner/feature-a",
        ]
        self.assertEqual([3, 7], collect.pr_numbers(subjects))
        self.assertEqual([3], collect.pr_numbers(["Merge pull request #3 from a/b"] * 2))

    def test_merged_subjects_reads_first_parent_merges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            def git(*args: str) -> None:
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.name=T",
                        "-c",
                        "user.email=t@example.invalid",
                        "-c",
                        "commit.gpgsign=false",
                        *args,
                    ],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                )

            git("init", "-q", "-b", "dev")
            (repo / "a").write_text("1")
            git("add", "-A")
            git("commit", "-q", "-m", "chore: seed")
            git("tag", "v1.0.0")
            git("switch", "-q", "-c", "f")
            (repo / "b").write_text("1")
            git("add", "-A")
            git("commit", "-q", "-m", "feat: x")
            git("switch", "-q", "dev")
            git("merge", "-q", "--no-ff", "-m", "Merge pull request #5 from o/f", "f")
            subjects = collect.merged_subjects(repo, "v1.0.0", "dev")
            self.assertEqual([5], collect.pr_numbers(subjects))


if __name__ == "__main__":
    unittest.main()
