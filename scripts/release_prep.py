#!/usr/bin/env python3
"""Rewrite the version-bearing files of the working tree for one release. Standard library only.

Usage: ``release_prep.py --version X.Y.Z --date YYYY-MM-DD --prs prs.json [--root DIR]
[--milestone-url URL]``.

``prs.json`` is a list of ``{"number", "title", "url", "labels"}`` for the pull requests merged
into ``dev`` since the previous release. Every pattern must match exactly once; otherwise nothing
is written and the exit code is 1 (2 for a usage error). The CHANGELOG logic is in
``release_changelog.py``, next to this file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_changelog import Pr, PrepError, update_changelog  # noqa: E402

REPOSITORY_URL = "https://github.com/wevertonjuscelino/wev-skills"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# (file, pattern) pairs whose single capture group is the version string.
REGEX_TARGETS = (
    ("pyproject.toml", r'(?m)^version = "([^"]+)"$'),
    (".claude-plugin/plugin.json", r'(?m)^  "version": "([^"]+)",$'),
    ("src/wev_skills/__init__.py", r'(?m)^__version__ = "([^"]+)"$'),
    ("docs/guides/installation.md", r'(?m)^  "version": "([^"]+)"$'),
    ("docs/guides/installation.pt-BR.md", r'(?m)^  "version": "([^"]+)"$'),
)
# Files with <!-- wev:NAME -->...<!-- /wev:NAME --> markers: (file, marker names).
MARKER_FILES = {
    "README.md": ("version",),
    "README.pt-BR.md": ("version",),
    "CLAUDE.md": ("version", "release-date"),
    "ROADMAP.md": ("release-status",),
    "ROADMAP.pt-BR.md": ("release-status",),
    "docs/mvp-status.md": ("release-status",),
    "docs/mvp-status.pt-BR.md": ("release-status",),
}
STATUS_TEXT = {
    "en": {
        "latest": "Latest release: [{tag}]({url}), published on {date}.",
        "next": "Open milestone for the next release: [{tag}]({milestone}).",
    },
    "pt-BR": {
        "latest": "Última versão publicada: [{tag}]({url}), em {date}.",
        "next": "Milestone aberto da próxima versão: [{tag}]({milestone}).",
    },
}
ROADMAP_FILES = ("ROADMAP.md", "ROADMAP.pt-BR.md")


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    """Replace the single match of ``pattern``; fail loudly on zero or several."""
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise PrepError(f"{label}: expected exactly one match of {pattern!r}, found {len(matches)}")
    return text[: matches[0].start()] + replacement + text[matches[0].end() :]


def set_version(text: str, pattern: str, version: str, label: str) -> str:
    """Replace the capture group of ``pattern`` (exactly one match) with ``version``."""
    match = re.search(pattern, text)
    if match is None or len(re.findall(pattern, text)) != 1:
        raise PrepError(f"{label}: expected exactly one match of {pattern!r}")
    return text[: match.start(1)] + version + text[match.end(1) :]


def set_marker(text: str, name: str, content: str, label: str) -> str:
    """Replace what sits between ``<!-- wev:name -->`` and ``<!-- /wev:name -->``."""
    pattern = rf"(<!-- wev:{re.escape(name)} -->)(.*?)(<!-- /wev:{re.escape(name)} -->)"
    matches = list(re.finditer(pattern, text, re.DOTALL))
    if len(matches) != 1:
        raise PrepError(
            f"{label}: expected exactly one wev:{name} marker pair, found {len(matches)}"
        )
    found = matches[0]
    return text[: found.start(2)] + content + text[found.end(2) :]


def render_status(name: str, version: str, release_date: str, milestone_url: str) -> str:
    lang = "pt-BR" if name.endswith(".pt-BR.md") else "en"
    words = STATUS_TEXT[lang]
    tag = f"v{version}"
    parts = [
        words["latest"].format(
            tag=tag, url=f"{REPOSITORY_URL}/releases/tag/{tag}", date=release_date
        )
    ]
    if name in ROADMAP_FILES:
        major = int(version.split(".")[0]) + 1
        parts.append(words["next"].format(tag=f"v{major}.0.0", milestone=milestone_url))
    return " ".join(parts)


def marker_content(
    marker: str, name: str, version: str, release_date: str, milestone_url: str
) -> str:
    if marker == "version":
        return version
    if marker == "release-date":
        return release_date
    return render_status(name, version, release_date, milestone_url)


def plan(
    root: Path, version: str, release_date: str, prs: list[Pr], milestone_url: str
) -> dict[Path, str]:
    """The new text of every file to change; nothing is written here."""
    changes: dict[Path, str] = {}
    for name, pattern in REGEX_TARGETS:
        path = root / name
        changes[path] = set_version(_read(path), pattern, version, name)
    for name, markers in MARKER_FILES.items():
        path = root / name
        text = _read(path)
        for marker in markers:
            content = marker_content(marker, name, version, release_date, milestone_url)
            text = set_marker(text, marker, content, name)
        changes[path] = text
    path = root / "CHANGELOG.md"
    changes[path] = update_changelog(_read(path), version, release_date, prs)
    return changes


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise PrepError(f"cannot read {path}: {error}") from error


def load_prs(path: Path) -> list[Pr]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PrepError(f"cannot read {path}: {error}") from error
    if not isinstance(raw, list):
        raise PrepError(f"{path}: expected a JSON list of pull requests")
    return [Pr.from_json(item) for item in raw]


def apply(
    root: Path, version: str, release_date: str, prs_file: Path, milestone_url: str
) -> list[Path]:
    if not VERSION_RE.match(version):
        raise PrepError(f"invalid version {version!r}; expected X.Y.Z")
    try:
        date.fromisoformat(release_date)
    except ValueError as error:
        raise PrepError(f"invalid date {release_date!r}; expected YYYY-MM-DD") from error
    changes = plan(root, version, release_date, load_prs(prs_file), milestone_url)
    for path, text in changes.items():
        path.write_text(text, encoding="utf-8")
    return sorted(changes)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Rewrite version-bearing files for a release.")
    parser.add_argument("--version", required=True, help="release version X.Y.Z (no leading v)")
    parser.add_argument("--date", required=True, help="release date YYYY-MM-DD")
    parser.add_argument("--prs", required=True, type=Path, help="JSON list of merged pull requests")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--milestone-url", default=f"{REPOSITORY_URL}/milestones")
    args = parser.parse_args(argv[1:])
    try:
        changed = apply(args.root, args.version, args.date, args.prs, args.milestone_url)
    except PrepError as error:
        print(f"release_prep: {error}", file=sys.stderr)
        return 1
    for path in changed:
        print(f"updated {path.relative_to(args.root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
