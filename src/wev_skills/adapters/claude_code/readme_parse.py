"""Shared pieces of the README checker: findings, the report, a small Markdown parser and links.

``readme_check`` holds the rules. Nothing here touches the filesystem except ``path_exists``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from wev_skills import i18n
from wev_skills.core.errors import ValidationError
from wev_skills.security.paths import resolve_within

README_NAME = "README.md"
README_PT_NAME = "README.pt-BR.md"
_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
CODE_SPAN = re.compile(r"`[^`\n]*`")
_INLINE_LINK = re.compile(r"\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)")
_REFERENCE = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*<?(\S+?)>?\s*$")
_HTML_TARGET = re.compile(r"""\b(?:src|href)=["']([^"']+)["']""")
_EXTERNAL = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*:|//)")


class ReadmeError(ValidationError):
    """A README cannot be read as UTF-8 text."""


@dataclass(frozen=True)
class Finding:
    rule: str
    line: int
    file: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "line": self.line, "file": self.file, "message": self.message}


@dataclass(frozen=True)
class ReadmeReport:
    files: tuple[str, ...]
    findings: tuple[Finding, ...]
    warnings: tuple[Finding, ...]
    logo: dict[str, Any] | None
    twin_checked: bool
    credits_checked: bool

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "files": list(self.files),
            "findings": [f.to_dict() for f in self.findings],
            "warnings": [f.to_dict() for f in self.warnings],
            "logo": self.logo,
            "twin_checked": self.twin_checked,
            "credits_checked": self.credits_checked,
        }


@dataclass(frozen=True)
class CodeBlock:
    line: int
    language: str
    content: str
    closed: bool


@dataclass(frozen=True)
class Document:
    prose: tuple[tuple[int, str], ...]
    headings: tuple[tuple[int, int, str], ...]
    blocks: tuple[CodeBlock, ...]
    total_lines: int


def make_finding(rule: str, line: int, file: str, **params: object) -> Finding:
    return Finding(rule, line, file, i18n.t(f"readme.finding.{rule}", None, **params))


# --- parsing -----------------------------------------------------------------------------------


def _closes(line: str, mark: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= len(mark) and set(stripped) == {mark[0]}


def parse(text: str) -> Document:
    """Split a document into prose lines, ATX headings and fenced code blocks."""
    prose: list[tuple[int, str]] = []
    blocks: list[CodeBlock] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        opening = _FENCE_OPEN.match(lines[index])
        if opening is None or (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            prose.append((index + 1, lines[index]))
            index += 1
            continue
        mark, info = opening.group(1), opening.group(2).strip()
        end = next((i for i in range(index + 1, len(lines)) if _closes(lines[i], mark)), None)
        body = lines[index + 1 : len(lines) if end is None else end]
        language = info.split()[0] if info else ""
        blocks.append(CodeBlock(index + 1, language, "\n".join(body), end is not None))
        index = len(lines) if end is None else end + 1
    headings = tuple(
        (number, len(m.group(1)), m.group(2).strip())
        for number, line in prose
        if (m := _HEADING.match(line))
    )
    return Document(tuple(prose), headings, tuple(blocks), len(lines))


def normalize_heading(text: str) -> str:
    return text.strip().strip("*_`").rstrip(".:").strip().casefold()


def targets(prose: tuple[tuple[int, str], ...]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, raw in prose:
        line = CODE_SPAN.sub("", raw)
        reference = _REFERENCE.match(line)
        values = [reference.group(1)] if reference else _INLINE_LINK.findall(line)
        values += _HTML_TARGET.findall(line)
        found.extend((number, value) for value in values)
    return found


def link_location(target: str) -> str | None:
    """The path part of a relative link, or ``None`` for external links and anchors."""
    cleaned = target.strip().strip("<>")
    if not cleaned or cleaned.startswith("#") or _EXTERNAL.match(cleaned):
        return None
    return unquote(cleaned.split("#", 1)[0].split("?", 1)[0]) or None


def resolve_link(root: Path, directory: Path, location: str) -> Path | None:
    """The path a relative link names, or ``None`` when it leaves the repository."""
    if location.startswith(("/", "\\")) or Path(location).is_absolute():
        return None
    try:
        return resolve_within(root, directory / location)
    except Exception:  # noqa: BLE001 - any failure to resolve safely means "not inside the root"
        return None


def path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False
