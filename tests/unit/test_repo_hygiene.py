"""Repository hygiene: nothing personal or machine-specific is in a file git would track.

The files checked are the tracked files plus the untracked files that ``.gitignore`` does not
exclude, so the test gives the same answer before and after the first commit. The personal
strings and the home-directory prefixes are built from fragments, so this file does not contain
what it forbids.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_URL = "https://github.com/wevertonjuscelino/wev-skills"

# Built at runtime so that this file passes its own check.
PERSONAL_STRINGS = ("ton" + "ton", "ton" + "ton" + "alu")
HOME_ROOTS = ("Us" + "ers", "ho" + "me")
SCRATCH_MARKERS = ("/private/tmp/" + "claude", "scratch" + "pad")

# Home-directory paths that are obviously examples, used as fixtures for redaction and similar.
PLACEHOLDER_HOME_NAMES = frozenset(
    {"ana", "user", "username", "you", "name", "me", "example", "runner", "alice", "bob"}
)
PLACEHOLDER_EMAIL_DOMAINS = frozenset(
    {"example.com", "example.org", "example.net", "users.noreply.github.com"}
)
PLACEHOLDER_EMAIL_SUFFIXES = (".invalid", ".example", ".test", ".localhost")
# Addresses that are not personal: the SSH user of GitHub clone URLs and a two-letter fixture.
PLACEHOLDER_EMAILS = frozenset({"git@github.com", "a@b.org"})

HOME_PATH = re.compile(r"/(?:" + "|".join(HOME_ROOTS) + r")/([A-Za-z0-9._-]+)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def candidate_files() -> list[Path]:
    """Tracked files plus untracked files not ignored by ``.gitignore``."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    names = [n for n in result.stdout.decode("utf-8", "replace").split("\0") if n]
    return sorted(ROOT / n for n in set(names) if (ROOT / n).is_file())


def read_text(path: Path) -> str | None:
    """File text, or ``None`` for a binary file."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def is_placeholder_email(address: str) -> bool:
    if address in PLACEHOLDER_EMAILS:
        return True
    domain = address.rsplit("@", 1)[1].lower()
    return domain in PLACEHOLDER_EMAIL_DOMAINS or domain.endswith(PLACEHOLDER_EMAIL_SUFFIXES)


def scan(text: str) -> list[str]:
    """Findings in ``text`` as short descriptions that never repeat a matched address."""
    findings: list[str] = []
    lowered = text.lower()
    for needle in PERSONAL_STRINGS:
        if needle in lowered:
            findings.append("personal string")
    for marker in SCRATCH_MARKERS:
        if marker in lowered:
            findings.append("scratch or temp path")
    for match in HOME_PATH.finditer(text):
        if match.group(1).lower() not in PLACEHOLDER_HOME_NAMES:
            findings.append("home-directory path")
    for match in EMAIL.finditer(text):
        if not is_placeholder_email(match.group(0)):
            findings.append("email address")
    return findings


class ScannerTests(unittest.TestCase):
    """The checks themselves, on fabricated text."""

    def test_flags_a_real_looking_home_path_and_accepts_placeholders(self) -> None:
        root = "/" + HOME_ROOTS[0] + "/"
        self.assertEqual(scan(root + "jdoe/project"), ["home-directory path"])
        self.assertEqual(scan(root + "you/project"), [])
        self.assertEqual(scan("/" + HOME_ROOTS[1] + "/ana/project"), [])

    def test_flags_the_personal_strings_in_any_case(self) -> None:
        self.assertEqual(scan(PERSONAL_STRINGS[0].upper()), ["personal string"])
        self.assertIn("personal string", scan("x" + PERSONAL_STRINGS[1]))

    def test_flags_a_personal_email_and_accepts_placeholders(self) -> None:
        self.assertEqual(scan("jdoe" + "@" + "gmail.com"), ["email address"])
        for address in (
            "ana@example.com",
            "t@example.invalid",
            "12345+jdoe@users.noreply.github.com",
            "git@github.com",
        ):
            self.assertEqual(scan(address), [], address)

    def test_a_package_at_marketplace_reference_is_not_an_email(self) -> None:
        self.assertEqual(scan("claude plugin install wev-skills@wev-skills-marketplace"), [])

    def test_flags_scratch_paths(self) -> None:
        self.assertEqual(scan(SCRATCH_MARKERS[0] + "-501/x"), ["scratch or temp path"])


class RepositoryTests(unittest.TestCase):
    def test_the_candidate_file_list_is_not_empty_and_excludes_local_state(self) -> None:
        names = {path.relative_to(ROOT).as_posix() for path in candidate_files()}
        self.assertIn("pyproject.toml", names)
        forbidden_parts = {".remember", ".wev", "__pycache__", ".mypy_cache", ".ruff_cache"}
        leaked = [n for n in names if forbidden_parts & set(Path(n).parts)]
        self.assertEqual(leaked, [])

    def test_no_local_override_or_environment_files_are_candidates(self) -> None:
        names = {path.name for path in candidate_files()}
        self.assertNotIn("wev.config.local.json", names)
        self.assertNotIn("." + "env", names)

    def test_no_file_holds_personal_or_machine_specific_text(self) -> None:
        problems: list[str] = []
        for path in candidate_files():
            text = read_text(path)
            if text is None:
                continue
            problems.extend(f"{path.relative_to(ROOT)}: {finding}" for finding in scan(text))
        self.assertEqual(problems, [])

    def test_the_version_is_the_same_in_every_place_it_is_written(self) -> None:
        from wev_skills import __version__

        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8"))
        self.assertEqual(
            {pyproject["project"]["version"], manifest["version"], __version__}, {__version__}
        )

    def test_pyproject_declares_python_3_14_and_the_repository_urls(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["requires-python"], ">=3.14")
        self.assertEqual(project["authors"], [{"name": "Weverton Juscelino"}])
        urls = project["urls"]
        self.assertEqual(set(urls), {"Homepage", "Repository", "Issues", "Changelog"})
        self.assertTrue(all(v.startswith(REPOSITORY_URL) for v in urls.values()))

    def test_file_names_hold_no_personal_text(self) -> None:
        names = [path.relative_to(ROOT).as_posix() for path in candidate_files()]
        self.assertEqual([n for n in names if scan(n)], [])


if __name__ == "__main__":
    unittest.main()
