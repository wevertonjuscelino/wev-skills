"""The prompts of finders and verifiers. Everything from the repository or a model is fenced."""

from __future__ import annotations

import json
from collections.abc import Sequence

from wev_skills import i18n
from wev_skills.core.errors import StateConflict
from wev_skills.review.findings import BODY_MAX, MAX_FINDINGS, TITLE_MAX, RawFinding
from wev_skills.review.guide import ReviewGuide
from wev_skills.security.redact import redact
from wev_skills.security.untrusted import wrap
from wev_skills.state.review_records import FindingRecord

MAX_PROMPT_CHARS = 100_000
"""Refused, never cut: ``wrap`` caps at twice as much, so it cannot cut a diff."""


def check_size(prompt: str, lang: str) -> str:
    """``prompt`` when it fits; else the round is refused before any agent runs."""
    if len(prompt) > MAX_PROMPT_CHARS:
        text = i18n.t("review.error.diff_too_large", lang, size=len(prompt), cap=MAX_PROMPT_CHARS)
        raise StateConflict("review_diff_too_large", text)
    return prompt


def _fenced(text: str, source: str) -> str:
    return wrap(redact(text), source=source)


def _guide_text(guide: ReviewGuide) -> str:
    parts = {
        "failure": guide.failure,
        "nits": guide.nits,
        "important": guide.important,
        "skip": "\n".join(guide.skip),
    }
    return "\n".join(_fenced(text, f"REVIEW.md {name}") for name, text in parts.items() if text)


def _listing(records: Sequence[FindingRecord], first_index: int | None = None) -> str:
    rows = [
        {"id": r.id, "file": r.file, "line": r.line, "title": r.title, "body": r.body}
        for r in records
    ]
    if first_index is not None:
        rows = [{"index": first_index + i, **row} for i, row in enumerate(rows)]
    return json.dumps(rows, ensure_ascii=False)


def finder_prompt(
    diff: str,
    intent: str,
    guide: ReviewGuide,
    claude_md: str,
    posted: Sequence[FindingRecord],
    lang: str,
) -> str:
    return i18n.t(
        "review.prompt.finder",
        lang,
        max_findings=MAX_FINDINGS,
        title_max=TITLE_MAX,
        body_max=BODY_MAX,
        nit_cap=guide.nit_cap,
        intent=_fenced(intent, "change intent"),
        guide=_guide_text(guide),
        claude_md=_fenced(claude_md, "CLAUDE.md"),
        posted=_fenced(_listing(posted), "findings already posted"),
        diff=_fenced(diff, "diff"),
    )


def verifier_prompt(
    diff: str,
    candidates: Sequence[RawFinding],
    rechecks: Sequence[FindingRecord],
    guide: ReviewGuide,
    lang: str,
) -> str:
    rows = [
        {"index": i, "file": c.file, "line": c.line, "title": c.title, "body": c.body}
        for i, c in enumerate(candidates)
    ]
    return i18n.t(
        "review.prompt.verifier",
        lang,
        guide=_guide_text(guide),
        candidates=_fenced(json.dumps(rows, ensure_ascii=False), "candidate findings"),
        rechecks=_fenced(_listing(rechecks, len(candidates)), "findings to recheck"),
        diff=_fenced(diff, "diff"),
    )
