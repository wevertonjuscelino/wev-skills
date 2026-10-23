"""The text that tells a person what a review round left open."""

from __future__ import annotations

from collections.abc import Sequence

from wev_skills import i18n
from wev_skills.state.review_records import FindingRecord

ORDER = ("important", "nit", "pre_existing")
STATUS_OPEN = "open"


def summarize(findings: Sequence[FindingRecord], skipped: int, lang: str) -> str:
    """Counts of the open findings, then each by severity, then how many REVIEW.md skipped."""
    live = [f for f in findings if f.status == STATUS_OPEN]
    counts = {tag: sum(f.tag == tag for f in live) for tag in ORDER}
    if live:
        parts = (i18n.t(f"review.tag.{tag}", lang, count=counts[tag]) for tag in ORDER)
        head = i18n.t("review.summary.open", lang, counts=", ".join(parts))
    else:
        head = i18n.t("review.summary.nothing", lang)
    lines = [head]
    for tag in ORDER:
        lines.extend(f"- {f.file}:{f.line} [{tag}] {f.title}" for f in live if f.tag == tag)
    if skipped > 0:
        lines.append(i18n.t("review.summary.skipped", lang, count=skipped))
    return "\n".join(lines)
