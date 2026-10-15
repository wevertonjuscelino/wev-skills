"""Documentation checks: bilingual parity, working relative links, credits last, project name.

These tests read Markdown files only. They need no network and no model.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.claude_code import readme_check

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
PT_SUFFIX = ".pt-BR.md"

TWIN_EXEMPT = frozenset({DOCS / "research" / "sources.md", DOCS / "glossary.md"})
ROOT_TWINNED = ("README", "CONTRIBUTING", "SECURITY", "ROADMAP", "SUPPORT")
ROOT_GUIDES = (
    "README",
    "CONTRIBUTING",
    "SECURITY",
    "CHANGELOG",
    "CODE_OF_CONDUCT",
    "ROADMAP",
    "SUPPORT",
)
LINK_SCAN_DIRS = (DOCS, ROOT / "skills", ROOT / "evals", ROOT / "examples")
CREDITS_HEADINGS = {"README.md": "Credits", "README.pt-BR.md": "Créditos"}

FENCE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN = re.compile(r"`[^`\n]*`")
INLINE_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE_DEFINITION = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*(\S+)", re.MULTILINE)
SINGULAR_NAME = re.compile(r"wev-skill(?!s)")
EXTERNAL = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*:|//)")


def markdown_under(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.md"))


def root_markdown(names: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for name in names:
        for suffix in (".md", PT_SUFFIX):
            path = ROOT / f"{name}{suffix}"
            if path.exists():
                paths.append(path)
    return paths


def documentation_files() -> list[Path]:
    files: set[Path] = set(root_markdown(ROOT_GUIDES))
    for directory in LINK_SCAN_DIRS:
        files.update(markdown_under(directory))
    return sorted(files)


def prose_lines(text: str) -> list[str]:
    """Lines outside fenced code blocks."""
    kept: list[str] = []
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            kept.append(line)
    return kept


def second_level_headings(path: Path) -> list[str]:
    lines = prose_lines(path.read_text(encoding="utf-8"))
    return [line[3:].strip() for line in lines if line.startswith("## ")]


def relative_targets(path: Path) -> list[str]:
    prose = "\n".join(CODE_SPAN.sub("", line) for line in prose_lines(path.read_text("utf-8")))
    targets = INLINE_LINK.findall(prose) + REFERENCE_DEFINITION.findall(prose)
    kept: list[str] = []
    for target in targets:
        cleaned = target.strip("<>")
        if not cleaned or cleaned.startswith("#") or EXTERNAL.match(cleaned):
            continue
        kept.append(cleaned)
    return kept


def twin_of(path: Path) -> Path:
    if path.name.endswith(PT_SUFFIX):
        return path.with_name(path.name[: -len(PT_SUFFIX)] + ".md")
    return path.with_name(path.name[: -len(".md")] + PT_SUFFIX)


def twinned_files() -> list[Path]:
    files = [p for p in markdown_under(DOCS) if p not in TWIN_EXEMPT]
    return sorted([*files, *root_markdown(ROOT_TWINNED)])


class TwinTests(unittest.TestCase):
    def test_every_document_has_its_twin(self) -> None:
        missing = [
            str(twin_of(p).relative_to(ROOT)) for p in twinned_files() if not twin_of(p).exists()
        ]
        self.assertEqual([], missing, "documents without a twin in the other language")

    def test_twins_have_the_same_number_of_second_level_headings(self) -> None:
        mismatches: list[str] = []
        for path in twinned_files():
            if path.name.endswith(PT_SUFFIX) or not twin_of(path).exists():
                continue
            english, portuguese = second_level_headings(path), second_level_headings(twin_of(path))
            if len(english) != len(portuguese):
                mismatches.append(f"{path.relative_to(ROOT)}: {len(english)} vs {len(portuguese)}")
        self.assertEqual([], mismatches)

    def test_the_two_languages_link_to_each_other(self) -> None:
        unlinked: list[str] = []
        for path in twinned_files():
            twin = twin_of(path)
            if not twin.exists():
                continue
            if twin.name not in path.read_text(encoding="utf-8"):
                unlinked.append(str(path.relative_to(ROOT)))
        self.assertEqual([], unlinked, "documents that do not mention their twin by file name")


class LinkTests(unittest.TestCase):
    def test_relative_links_resolve_to_existing_files(self) -> None:
        broken: list[str] = []
        for path in documentation_files():
            for target in relative_targets(path):
                location = target.split("#", 1)[0].split("?", 1)[0]
                if not location:
                    continue
                if not (path.parent / location).resolve().exists():
                    broken.append(f"{path.relative_to(ROOT)} -> {target}")
        self.assertEqual([], broken)

    def test_the_link_extraction_ignores_code(self) -> None:
        text = "```\n[x](nowhere.md)\n```\nand `[y](nowhere.md)` and [z](https://example.org)\n"
        prose = "\n".join(CODE_SPAN.sub("", line) for line in prose_lines(text))
        self.assertEqual(["https://example.org"], INLINE_LINK.findall(prose))


class ReadmeTests(unittest.TestCase):
    def test_the_last_second_level_heading_of_each_readme_is_the_credits(self) -> None:
        for name, expected in CREDITS_HEADINGS.items():
            with self.subTest(readme=name):
                headings = second_level_headings(ROOT / name)
                self.assertTrue(headings, f"{name} has no second-level heading")
                self.assertEqual(expected, headings[-1])

    def test_nothing_follows_the_credits_but_their_own_content(self) -> None:
        for name, expected in CREDITS_HEADINGS.items():
            with self.subTest(readme=name):
                lines = prose_lines((ROOT / name).read_text(encoding="utf-8"))
                after = lines[lines.index(f"## {expected}") + 1 :]
                later = [line for line in after if line.startswith("#")]
                self.assertEqual([], later)


class ReadmeStandardTests(unittest.TestCase):
    def test_both_readmes_pass_the_readme_checker_with_zero_findings(self) -> None:
        with i18n.use_language("en"):
            report = readme_check.check_directory(ROOT, ROOT)
        found = [f"{f.file}:{f.line} {f.rule}" for f in report.findings]
        self.assertEqual([], found)
        self.assertEqual(["README.md", "README.pt-BR.md"], list(report.files))
        self.assertTrue(report.twin_checked)
        self.assertTrue(report.credits_checked)
        self.assertEqual((), report.warnings)

    def test_the_credits_name_the_sources_of_both_documentation_features(self) -> None:
        for name in CREDITS_HEADINGS:
            text = (ROOT / name).read_text(encoding="utf-8")
            credits = text[text.index(f"## {CREDITS_HEADINGS[name]}") :]
            for source in ("github/awesome-copilot", "andrej-karpathy-skills", "forrestchang"):
                with self.subTest(readme=name, source=source):
                    self.assertIn(source, credits)

    def test_each_readme_names_every_skill_in_the_skills_directory(self) -> None:
        skills = sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir())
        self.assertIn("wev-skill-maintenance", skills)
        for name in CREDITS_HEADINGS:
            text = (ROOT / name).read_text(encoding="utf-8")
            for skill in skills:
                with self.subTest(readme=name, skill=skill):
                    self.assertIn(f"`{skill}`", text)


class NameTests(unittest.TestCase):
    def test_no_document_uses_the_singular_project_name(self) -> None:
        offenders: list[str] = []
        for path in documentation_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if SINGULAR_NAME.search(line.replace("wev-skill-maintenance", "")):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
