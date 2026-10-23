"""The report as a pull request body, with the headings of ``.github/PULL_REQUEST_TEMPLATE.md``.

Headings are fixed English strings because the template is English. Plan and finding text is
written by an agent or a model, so every field goes through ``clean_text`` first."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wev_skills import i18n
from wev_skills.core.textsafe import clean_text
from wev_skills.security import untrusted

NOTE_MAX_CHARS = 4000
BACKTICK = "`"


def _text(value: object, lang: str, limit: int = NOTE_MAX_CHARS) -> str:
    return clean_text(value, limit) or i18n.t("review.pr.none", lang)


def _tested(report: Mapping[str, Any]) -> list[str]:
    lines = []
    for task in report["tasks"]:
        for check in task["checks_run"]:
            command = clean_text(check["command"]).replace(BACKTICK, "'")
            lines.append(f"- `{command}` ({clean_text(task['id'])}): {clean_text(check['state'])}")
    return lines


def _dismissed(report: Mapping[str, Any], lang: str) -> list[str]:
    return [
        "- "
        + i18n.t(
            "review.pr.dismissed",
            lang,
            id=clean_text(f["id"]),
            tag=clean_text(f["tag"]),
            outcome=clean_text(f["outcome"]),
            reason=clean_text(f["reason"]),
        )
        for f in report["review"]["dismissed"]
    ]


def render_pr(report: Mapping[str, Any], lang: str) -> str:
    """Summary, what was tested, risk, how to revert and the review, in template order."""
    summary = clean_text(report["objective"], NOTE_MAX_CHARS)
    review = untrusted.sanitize(report["review"]["summary"])  # keeps its line breaks
    blocks = [
        ("Summary", [summary]),
        ("What was tested", _tested(report) or [i18n.t("review.pr.none", lang)]),
        ("Risk", [_text(report.get("risk_notes", ""), lang)]),
        ("How to revert", [_text(report.get("revert", ""), lang)]),
        ("Review", [review, *_dismissed(report, lang)]),
    ]
    return "\n\n".join(f"## {name}\n\n" + "\n".join(lines) for name, lines in blocks) + "\n"
