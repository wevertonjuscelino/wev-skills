"""The report as a pull request body, with the headings of ``.github/PULL_REQUEST_TEMPLATE.md``.

Headings are fixed English strings because the template is English. Plan and finding text is
written by an agent or a model, so every field goes through ``clean_text`` first."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wev_skills import i18n
from wev_skills.core.textsafe import clean_text

NOTE_MAX_CHARS = 4000
BACKTICK = "`"
TAGS = ("important", "nit", "pre_existing")


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


def _review(report: Mapping[str, Any], lang: str) -> list[str]:
    """Count-first head, one bullet per open finding, then the dismissed ones. Every field
    is one cleaned line, so a model-written title cannot open a heading or a list item."""
    live = report["review"]["open"]
    tags = [clean_text(f["tag"]) for f in live]
    status = report["review"].get("status", "current")
    if status == "not_reviewed":
        return [i18n.t("review.summary.not_reviewed", lang)]
    if status == "stale":
        head = i18n.t("review.summary.stale", lang)
    elif live:
        counts = ", ".join(i18n.t(f"review.tag.{tag}", lang, count=tags.count(tag)) for tag in TAGS)
        head = i18n.t("review.summary.open", lang, counts=counts)
    else:
        head = i18n.t("review.summary.nothing", lang)
    lines = [head]
    for tag in TAGS:
        label = i18n.t(f"review.label.{tag}", lang)
        for f in live:
            if clean_text(f["tag"]) == tag:
                where = f"{clean_text(f['file'])}:{clean_text(f['line'])}"
                lines.append(f"- {where} [{label}] {clean_text(f['title'])}")
    if report["review"]["skipped"] > 0:
        lines.append(i18n.t("review.summary.skipped", lang, count=report["review"]["skipped"]))
    return [*lines, *_dismissed(report, lang)]


def _risk(report: Mapping[str, Any], lang: str) -> list[str]:
    found = report.get("classification") or {}
    lines = []
    if found:
        lines.append(i18n.t("review.pr.risk_tier", lang, tier=clean_text(found["risk"])))
        lines.extend(f"- {clean_text(reason)}" for reason in found.get("reasons", ()))
        lines.append("")
    return [*lines, _text(report.get("risk_notes", ""), lang)]


def render_pr(report: Mapping[str, Any], lang: str) -> str:
    """Summary, what was tested, risk, how to revert and the review, in template order."""
    blocks = [
        ("Summary", [clean_text(report["objective"], NOTE_MAX_CHARS)]),
        ("What was tested", _tested(report) or [i18n.t("review.pr.none", lang)]),
        ("Risk", _risk(report, lang)),
        ("How to revert", [_text(report.get("revert", ""), lang)]),
        ("Review", _review(report, lang)),
    ]
    return "\n\n".join(f"## {name}\n\n" + "\n".join(lines) for name, lines in blocks) + "\n"
