"""Create and maintain the managed guidelines block of a project's ``CLAUDE.md``.

The guidelines live between two HTML comment markers. Everything outside the markers belongs to
the author and is never changed. The planning functions are pure (text in, text out); only
``read_existing``, ``resolve_target`` and ``apply`` touch the filesystem.
"""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.core.discovery import CheckSuggestion
from wev_skills.core.errors import NotFound, PermissionDenied, StateConflict, ValidationError
from wev_skills.core.fsutil import atomic_write_text
from wev_skills.security.paths import resolve_within

BLOCK_VERSION = 1
START_MARKER = f"<!-- wev-skills:guidelines:start v{BLOCK_VERSION} -->"
END_MARKER = "<!-- wev-skills:guidelines:end -->"
MAX_RECOMMENDED_LINES = 200
CLAUDE_MD_NAME = "CLAUDE.md"
NEW_FILE_MODE = 0o644
GUIDELINES_DIR = Path(__file__).resolve().parent / "guidelines"
HEADER_LINE = "# CLAUDE.md"
INTRO_LINE = (
    "This file provides guidance to Claude Code (claude.ai/code) when working with code "
    "in this repository."
)
SECTION_KEYS = ("commands", "architecture", "rules")

_START_RE = re.compile(r"<!-- wev-skills:guidelines:start[^>]*-->")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*?)\s*$")


class MarkerError(ValidationError):
    """The managed markers are duplicated or unbalanced; the author must fix them by hand."""


@dataclass(frozen=True)
class ClaudeMdPlan:
    path: str
    before: str
    after: str
    changed: bool
    diff: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ClaudeMdReport:
    exists: bool
    has_header: bool
    has_block: bool
    block_current: bool
    sections_missing: tuple[str, ...]
    sections_placeholder: tuple[str, ...]
    undocumented_commands: tuple[str, ...]
    lines: int
    line_warning: bool
    marker_error: str | None
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return (
            self.exists
            and self.has_header
            and self.has_block
            and self.block_current
            and not self.sections_missing
            and not self.sections_placeholder
            and not self.undocumented_commands
            and self.marker_error is None
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


# --- rendering -------------------------------------------------------------------------------


def _template(lang: str) -> str:
    language = i18n.resolve_language(lang)
    try:
        return (GUIDELINES_DIR / f"guidelines.{language}.md").read_text(encoding="utf-8")
    except OSError as exc:
        message = i18n.t("claudemd.error.no_template", None, lang=language)
        raise NotFound("claude_md_no_template", message, {"lang": language}) from exc


def render_block(lang: str) -> str:
    """The managed block for ``lang``, markers included, with LF line endings, no final newline."""
    return f"{START_MARKER}\n{_template(lang).strip()}\n{END_MARKER}"


def _skeleton(lang: str, discovered: tuple[CheckSuggestion, ...]) -> str:
    def placeholder(key: str) -> str:
        return f"<!-- {i18n.t(f'claudemd.placeholder.{key}', lang)} -->"

    detected = [
        f"- `{item.command}` ({i18n.t('claudemd.detected_in', lang, source=f'`{item.source}`')})"
        for item in discovered
    ]
    bodies = {
        "commands": "\n".join(detected) if detected else placeholder("commands"),
        "architecture": placeholder("architecture"),
        "rules": placeholder("rules"),
    }
    return "\n\n".join(
        f"## {i18n.t(f'claudemd.section.{key}', lang)}\n\n{bodies[key]}" for key in SECTION_KEYS
    )


# --- locating the block ----------------------------------------------------------------------


def _marker_error(key: str) -> MarkerError:
    return MarkerError("claude_md_markers", i18n.t(f"claudemd.error.{key}"), {"reason": key})


def _find_block(text: str) -> tuple[int, int] | None:
    """Span of the managed block (start marker through end marker), or ``None`` when absent."""
    starts = list(_START_RE.finditer(text))
    ends = [m for m in re.finditer(re.escape(END_MARKER), text)]
    if not starts and not ends:
        return None
    if len(starts) > 1 or len(ends) > 1:
        raise _marker_error("markers_duplicate")
    if not starts or not ends or ends[0].start() < starts[0].end():
        raise _marker_error("markers_unbalanced")
    return starts[0].start(), ends[0].end()


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


# --- planning --------------------------------------------------------------------------------


def _diff(path: str, before: str, after: str) -> str:
    def lines(text: str) -> list[str]:
        out = text.splitlines(keepends=True)
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        return out

    source = f"a/{Path(path).name}" if before else "/dev/null"
    return "".join(
        difflib.unified_diff(lines(before), lines(after), source, f"b/{Path(path).name}")
    )


def _plan(path: str, before: str, after: str, note: str) -> ClaudeMdPlan:
    changed = before != after
    diff = _diff(path, before, after) if changed else ""
    return ClaudeMdPlan(path, before, after, changed, diff, (note,))


def _note(key: str) -> str:
    return i18n.t(f"claudemd.note.{key}")


def plan_update(existing: str | None, lang: str, *, path: str = CLAUDE_MD_NAME) -> ClaudeMdPlan:
    """Replace only the text between the markers with the current template."""
    if existing is None:
        message = i18n.t("claudemd.error.no_file", None, path=path)
        raise NotFound("claude_md_no_file", message, {"path": path})
    span = _find_block(existing)
    if span is None:
        raise ValidationError("claude_md_no_block", i18n.t("claudemd.error.no_block"), {})
    start, end = span
    block = render_block(lang).replace("\n", _eol(existing))
    after = existing[:start] + block + existing[end:]
    note = _note("current" if after == existing else "updated")
    return _plan(path, existing, after, note)


def _header_end(lines: list[str]) -> int:
    """Number of leading lines that form the standard header (``# CLAUDE.md`` + intro line)."""
    if not lines or lines[0].rstrip() != HEADER_LINE:
        return 0
    index = 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].startswith(INTRO_LINE[:40]):
        return index + 1
    return 1


def _insert_block(existing: str, lang: str) -> tuple[str, str]:
    """The text with the block inserted after the header (or on top), and the note key."""
    eol = _eol(existing)
    block = render_block(lang).replace("\n", eol)
    lines = existing.splitlines(keepends=True)
    split = _header_end(lines)
    prefix, rest = "".join(lines[:split]), "".join(lines[split:])
    if prefix:
        prefix += ("" if prefix.endswith("\n") else eol) + eol
    spacing = "" if rest.startswith(("\n", "\r\n")) else eol
    after = prefix + block + eol + (spacing + rest if rest else "")
    if not rest and not existing.endswith("\n"):
        after = after[: -len(eol)]
    return after, "inserted_after_header" if split else "inserted_top"


def plan_init(
    existing: str | None,
    lang: str,
    discovered: tuple[CheckSuggestion, ...],
    *,
    path: str = CLAUDE_MD_NAME,
) -> ClaudeMdPlan:
    """A new document, or the block inserted into an existing file (update if already there)."""
    if existing is None:
        parts = (HEADER_LINE, INTRO_LINE, render_block(lang), _skeleton(lang, discovered))
        return _plan(path, "", "\n\n".join(parts) + "\n", _note("created"))
    if _find_block(existing) is not None:
        return plan_update(existing, lang, path=path)
    after, note_key = _insert_block(existing, lang)
    return _plan(path, existing, after, _note(note_key))


# --- checking --------------------------------------------------------------------------------


def _headings() -> dict[str, str]:
    """Casefolded localized heading text mapped to its section key."""
    return {
        i18n.t(f"claudemd.section.{key}", lang).casefold(): key
        for lang in i18n.SUPPORTED_LANGS
        for key in SECTION_KEYS
    }


def _section_bodies(text: str) -> dict[str, str]:
    known = _headings()
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = known.get(match.group(2).casefold()) if len(match.group(1)) == 2 else None
            if current:
                bodies.setdefault(current, [])
        elif current:
            bodies[current].append(line)
    return {key: "\n".join(body) for key, body in bodies.items()}


def _block_is_current(text: str, span: tuple[int, int]) -> bool:
    found = text[span[0] : span[1]].replace("\r\n", "\n")
    return any(found == render_block(lang) for lang in i18n.SUPPORTED_LANGS)


def _is_placeholder(body: str) -> bool:
    return not _COMMENT_RE.sub("", body).strip()


def _unmentioned(text: str, discovered: tuple[CheckSuggestion, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(i.command for i in discovered if i.command not in text))


def check(existing: str | None, discovered: tuple[CheckSuggestion, ...]) -> ClaudeMdReport:
    """What is missing or stale in the file. Never raises for broken markers; it reports them."""
    if existing is None:
        return ClaudeMdReport(False, False, False, False, SECTION_KEYS, (), (), 0, False, None, ())
    marker_error: str | None = None
    span: tuple[int, int] | None = None
    try:
        span = _find_block(existing)
    except MarkerError as exc:
        marker_error = exc.message
    outside = existing if span is None else existing[: span[0]] + existing[span[1] :]
    bodies = _section_bodies(outside)
    first = next((line for line in existing.splitlines() if line.strip()), "")
    count = len(existing.splitlines())
    too_long = count > MAX_RECOMMENDED_LINES
    warnings = (
        (i18n.t("claudemd.warn.too_long", None, lines=count, limit=MAX_RECOMMENDED_LINES),)
        if too_long
        else ()
    )
    return ClaudeMdReport(
        exists=True,
        has_header=first.rstrip() == HEADER_LINE,
        has_block=span is not None,
        block_current=span is not None and _block_is_current(existing, span),
        sections_missing=tuple(k for k in SECTION_KEYS if k not in bodies),
        sections_placeholder=tuple(
            k for k in SECTION_KEYS if k in bodies and _is_placeholder(bodies[k])
        ),
        undocumented_commands=_unmentioned(existing, discovered),
        lines=count,
        line_warning=too_long,
        marker_error=marker_error,
        warnings=warnings,
    )


# --- filesystem ------------------------------------------------------------------------------


def find_repo_root(start: Path) -> Path:
    """Nearest ancestor holding a ``.git`` entry (file or directory); ``start`` when none."""
    base = start.resolve()
    for candidate in (base, *base.parents):
        if os.path.lexists(candidate / ".git"):
            return candidate
    return base


def _refuse_symlink(path: Path) -> None:
    if os.path.islink(path):
        message = i18n.t("claudemd.error.symlink", None, path=str(path))
        raise PermissionDenied("claude_md_symlink", message, {"path": str(path)})


def resolve_target(root: Path, directory: Path) -> Path:
    """The ``CLAUDE.md`` path inside ``directory``; it must stay in ``root`` and not be a link."""
    resolved = resolve_within(root, directory)
    if not resolved.is_dir():
        message = i18n.t("claudemd.error.no_dir", None, path=str(resolved))
        raise NotFound("claude_md_no_dir", message, {"path": str(resolved)})
    target = resolved / CLAUDE_MD_NAME
    _refuse_symlink(target)
    return resolve_within(root, target)


def read_existing(path: Path) -> str | None:
    """File text with its original line endings, or ``None`` when the file does not exist."""
    _refuse_symlink(path)
    if not path.exists():
        return None
    if not path.is_file():
        message = i18n.t("claudemd.error.not_regular", None, path=str(path))
        raise ValidationError("claude_md_not_regular", message, {"path": str(path)})
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        message = i18n.t("claudemd.error.bad_encoding", None, path=str(path))
        raise ValidationError("claude_md_bad_encoding", message, {"path": str(path)}) from exc
    except OSError as exc:
        message = i18n.t("claudemd.error.unreadable", None, path=str(path), reason=exc.strerror)
        raise NotFound("claude_md_unreadable", message, {"path": str(path)}) from exc


def apply(plan: ClaudeMdPlan, target: Path) -> bool:
    """Write ``plan.after`` atomically when it changes something; return whether it wrote."""
    if not plan.changed:
        return False
    if target.name != CLAUDE_MD_NAME:
        message = i18n.t("claudemd.error.bad_name", None, path=str(target))
        raise PermissionDenied("claude_md_bad_name", message, {"path": str(target)})
    current = read_existing(target)
    if (current or "") != plan.before:
        message = i18n.t("claudemd.error.changed", None, path=str(target))
        raise StateConflict("claude_md_changed", message, {"path": str(target)})
    mode = target.stat().st_mode & 0o777 if current is not None else NEW_FILE_MODE
    atomic_write_text(target, plan.after)
    os.chmod(target, mode)
    return True
