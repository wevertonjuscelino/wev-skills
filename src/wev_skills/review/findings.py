"""Parse what finders and verifiers answer. The answer is untrusted text: every doubt drops."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

from wev_skills.core.errors import PermissionDenied
from wev_skills.evaluation.score_pass import unfence
from wev_skills.security.paths import resolve_within
from wev_skills.security.redact import redact
from wev_skills.security.untrusted import sanitize, scan

MAX_FINDINGS = 20
TITLE_MAX = 120
BODY_MAX = 1200
FILE_MAX = 500
MAX_ANSWER_CHARS = 100_000
TAGS = ("important", "nit", "pre_existing")
KINDS = ("bug", "security", "style", "diagnostic", "cleanup")
BINARY_PROBE = 8192
MAX_SCAN_BYTES = 4 * 1024 * 1024  # a file longer than this proves lines only within its head
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class RawFinding:
    file: str
    line: int
    title: str
    body: str
    tag: str
    class_wide: bool


@dataclass(frozen=True)
class Vote:
    index: int
    real: bool
    tag: str
    kind: str


def finding_id(file: str, line: int, title: str) -> str:
    normal = _SPACES.sub(" ", title.strip()).lower()
    digest = hashlib.sha256(f"{file}\0{line}\0{normal}".encode()).hexdigest()
    return digest[:12]


def _items(answer: str, key: str) -> list[Any]:
    if len(answer) > MAX_ANSWER_CHARS:
        return []
    try:
        data = json.loads(unfence(answer))
    except ValueError, RecursionError:
        return []
    items = data.get(key) if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _clean(text: object, limit: int, multiline: bool = False) -> str | None:
    """``text`` when it is a plain, short, non-empty string with nothing instruction-like."""
    if not isinstance(text, str) or not 1 <= len(text) <= limit:
        return None
    if sanitize(text) != text or (not multiline and "\n" in text) or scan(text):
        return None
    return text


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _finding(item: object) -> RawFinding | None:
    if not isinstance(item, dict):
        return None
    file = _clean(item.get("file"), FILE_MAX)
    title = _clean(item.get("title"), TITLE_MAX)
    body = _clean(item.get("body"), BODY_MAX, multiline=True)
    line, tag, wide = item.get("line"), item.get("tag"), item.get("class_wide", False)
    if file is None or title is None or body is None or "\0" in file or redact(file) != file:
        return None
    title, body = redact(title), redact(body)  # a secret the finder read must not be stored
    if not _is_int(line) or tag not in TAGS or not isinstance(wide, bool):
        return None
    return RawFinding(file, line, title, body, tag, wide)


def parse_findings(answer: str) -> tuple[RawFinding, ...]:
    found = (_finding(item) for item in _items(answer, "findings"))
    return tuple([item for item in found if item is not None][:MAX_FINDINGS])


def parse_votes(answer: str, count: int) -> tuple[Vote, ...]:
    """``count`` is candidates plus rechecks: rechecks are indexed after the candidates."""
    votes: dict[int, Vote] = {}
    for item in _items(answer, "votes"):
        if not isinstance(item, dict):
            continue
        index, real = item.get("index"), item.get("real")
        tag, kind = item.get("tag"), item.get("kind")
        if not _is_int(index) or not 0 <= index < count or index in votes:
            continue
        if isinstance(real, bool) and tag in TAGS and kind in KINDS:
            votes[index] = Vote(index, real, tag, kind)
    return tuple(votes.values())


def _line_count(path: Path) -> int | None:
    """Lines in the head of a regular, text file; ``None`` for anything else."""
    try:
        if not path.is_file():
            return None
        with path.open("rb") as handle:
            data = handle.read(MAX_SCAN_BYTES)
    except OSError:
        return None
    if b"\0" in data[:BINARY_PROBE]:
        return None
    return data.count(b"\n") + (0 if not data or data.endswith(b"\n") else 1)


def proven(raw: RawFinding, root: Path) -> bool:
    """The cited file is a text file inside ``root`` and has the cited line."""
    try:
        path = resolve_within(root, raw.file)
    except PermissionDenied:
        return False
    count = _line_count(path)
    return count is not None and 1 <= raw.line <= count
