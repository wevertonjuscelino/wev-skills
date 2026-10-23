"""``REVIEW.md``: what a repository tells its reviewers (repository content, so untrusted)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import ValidationError

FILE_NAME = "REVIEW.md"
MAX_CHARS = 20_000
MAX_NIT_CAP = 50
DEFAULT_NIT_CAP = 3

HEADINGS: Mapping[str, str] = {
    "what failure looks like": "failure",
    "como é uma falha": "failure",
    "skip": "skip",
    "ignorar": "skip",
    "nits": "nits",
    "important": "important",
    "importante": "important",
}
_MAX_LINE = re.compile(r"^max:\s*(\S*)\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^[-*]\s+")


@dataclass(frozen=True)
class ReviewGuide:
    failure: str = ""
    skip: tuple[str, ...] = ()
    nit_cap: int = DEFAULT_NIT_CAP
    nits: str = ""
    important: str = ""


def _invalid(line: int, why: str) -> ValidationError:
    return ValidationError(
        "invalid_review_md", i18n.t("review.error.invalid_md", line=line, why=why), {"line": line}
    )


def _sections(text: str) -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    current: list[tuple[int, str]] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            title = line[3:].strip()
            field = HEADINGS.get(title.casefold())
            if field is None:
                raise _invalid(number, i18n.t("review.error.unknown_heading", title=title))
            current = found.setdefault(field, [])
        elif current is not None:
            current.append((number, line))
    return found


def _body(lines: list[tuple[int, str]]) -> str:
    return "\n".join(line for _, line in lines).strip()


def _nit_cap(lines: list[tuple[int, str]]) -> tuple[int, list[tuple[int, str]]]:
    cap, rest = DEFAULT_NIT_CAP, []
    for number, line in lines:
        match = _MAX_LINE.match(line.strip())
        if match is None:
            rest.append((number, line))
            continue
        value = match.group(1)
        if not (value.isascii() and value.isdigit() and int(value) <= MAX_NIT_CAP):
            raise _invalid(number, i18n.t("review.error.bad_max", maximum=MAX_NIT_CAP))
        cap = int(value)
    return cap, rest


def parse_guide(text: str) -> ReviewGuide:
    if len(text) > MAX_CHARS:
        raise _invalid(1, i18n.t("review.error.too_long", limit=MAX_CHARS))
    sections = _sections(text)
    cap, nit_lines = _nit_cap(sections.get("nits", []))
    skip = tuple(
        pattern
        for _, line in sections.get("skip", [])
        if (pattern := _BULLET.sub("", line.strip()).strip("`"))
    )
    return ReviewGuide(
        failure=_body(sections.get("failure", [])),
        skip=skip,
        nit_cap=cap,
        nits=_body(nit_lines),
        important=_body(sections.get("important", [])),
    )


def load_guide(root: Path) -> ReviewGuide:
    path = root / FILE_NAME
    if not path.is_file():
        return ReviewGuide()
    if not path.resolve().is_relative_to(root.resolve()):
        raise _invalid(1, i18n.t("review.error.outside_repo"))
    with path.open(encoding="utf-8", errors="replace") as handle:
        text = handle.read(MAX_CHARS + 1)
    return parse_guide(text)


def skipped(path: str, guide: ReviewGuide) -> bool:
    return any(fnmatch(path, pattern) for pattern in guide.skip)
