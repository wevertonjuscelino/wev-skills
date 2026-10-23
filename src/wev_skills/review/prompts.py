"""The prompts of finders and verifiers. Everything from the repository or a model is fenced."""

from __future__ import annotations

import json
from collections.abc import Sequence

from wev_skills import i18n
from wev_skills.review.findings import BODY_MAX, MAX_FINDINGS, TITLE_MAX, RawFinding
from wev_skills.review.guide import ReviewGuide
from wev_skills.security.redact import redact
from wev_skills.security.untrusted import wrap
from wev_skills.state.review_records import FindingRecord


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


def _listing(records: Sequence[FindingRecord]) -> str:
    rows = [
        {"id": r.id, "file": r.file, "line": r.line, "title": r.title, "body": r.body}
        for r in records
    ]
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
        rechecks=_fenced(_listing(rechecks), "findings to recheck"),
        diff=_fenced(diff, "diff"),
    )
