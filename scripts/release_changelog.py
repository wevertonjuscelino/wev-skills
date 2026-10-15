"""CHANGELOG.md rewriting for ``release_prep.py``. Standard library only."""

from __future__ import annotations

import re
from dataclasses import dataclass

TITLE_RE = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]*\))?(?P<breaking>!)?:\s*(?P<text>\S.*)$")
UNRELEASED = "## [Unreleased]"
SECTION_ORDER = ("Added", "Changed", "Fixed", "Security", "Documentation")
TYPE_SECTION = {"feat": "Added", "fix": "Fixed", "security": "Security", "docs": "Documentation"}
COMPARE_RE = re.compile(
    r"(?m)^\[Unreleased\]: (?P<base>\S+)/compare/v(?P<prev>\d+\.\d+\.\d+)\.\.\.HEAD$"
)


class PrepError(Exception):
    """Input or target files are not what the release preparation expects."""


@dataclass(frozen=True)
class Pr:
    number: int
    title: str
    url: str
    labels: tuple[str, ...]

    @staticmethod
    def from_json(item: object) -> Pr:
        if not isinstance(item, dict):
            raise PrepError(f"pull request entry is not an object: {item!r}")
        number, title, url = item.get("number"), item.get("title"), item.get("url")
        if not isinstance(number, int) or not isinstance(title, str) or not isinstance(url, str):
            raise PrepError(f"pull request needs int number, str title and str url: {item!r}")
        labels = item.get("labels") or []
        names = [x.get("name") if isinstance(x, dict) else x for x in labels]
        if not all(isinstance(x, str) for x in names):
            raise PrepError(f"pull request #{number}: labels must be strings or {{name}} objects")
        return Pr(number, title.strip(), url, tuple(str(x) for x in names))


def classify(pr: Pr) -> tuple[str, str]:
    """The changelog section and the description line for one pull request."""
    match = TITLE_RE.match(pr.title)
    kind = match["type"] if match else ""
    text = match["text"] if match else pr.title
    if "security" in pr.labels or kind == "security":
        return "Security", text
    return TYPE_SECTION.get(kind, "Changed"), text


def _split_sections(body: str) -> tuple[str, dict[str, list[str]]]:
    """Split a section body into the text before the first ``###`` and the lines per heading."""
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in body.splitlines():
        if line.startswith("### "):
            current = sections.setdefault(line[4:].strip(), [])
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    return "\n".join(preamble).strip(), sections


def build_section(version: str, release_date: str, unreleased: str, prs: list[Pr]) -> str:
    preamble, sections = _split_sections(unreleased)
    for pr in sorted(prs, key=lambda item: item.number):
        name, text = classify(pr)
        lines = sections.setdefault(name, [])
        while lines and not lines[-1].strip():
            lines.pop()
        lines.append(f"- {text} ([#{pr.number}]({pr.url}))")
    ordered = [n for n in SECTION_ORDER if n in sections]
    ordered += [n for n in sections if n not in SECTION_ORDER]
    blocks = [f"## [{version}] - {release_date}"]
    if preamble:
        blocks.append(preamble)
    for name in ordered:
        body = "\n".join(sections[name]).strip("\n")
        blocks.append(f"### {name}\n\n{body}")
    return "\n\n".join(blocks) + "\n"


def update_changelog(text: str, version: str, release_date: str, prs: list[Pr]) -> str:
    if f"## [{version}]" in text or re.search(rf"(?m)^\[{re.escape(version)}\]:", text):
        raise PrepError(f"CHANGELOG.md already has version {version}")
    if text.count(UNRELEASED) != 1:
        raise PrepError(f"CHANGELOG.md: expected exactly one {UNRELEASED!r} heading")
    links = list(COMPARE_RE.finditer(text))
    if len(links) != 1:
        raise PrepError("CHANGELOG.md: expected exactly one [Unreleased] compare link")
    link = links[0]
    start = text.index(UNRELEASED) + len(UNRELEASED)
    end = text.find("\n## [", start)
    end = end if end != -1 else link.start()
    section = build_section(version, release_date, text[start:end].strip("\n"), prs)
    base, prev = link["base"], link["prev"]
    new_links = (
        f"[Unreleased]: {base}/compare/v{version}...HEAD\n"
        f"[{version}]: {base}/compare/v{prev}...v{version}"
    )
    head = text[:start].rstrip("\n") + "\n\n" + section + "\n"
    middle = text[end : link.start()].lstrip("\n")
    return head + middle + new_links + text[link.end() :]
