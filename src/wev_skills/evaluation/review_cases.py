"""Review cases: a stored diff with a known bug (or none) and the rule that scores a reviewer."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.core.errors import ValidationError
from wev_skills.evaluation.cases import Case
from wev_skills.review.trees import touched_lines
from wev_skills.state.review_records import FindingRecord

DIFF_NAME = "change.diff"
# Exactly what `git diff` prints with these flags; `cases validate --at-base` regenerates it.
DIFF_ARGS = ("diff", "--unified=0", "--no-renames", "--no-ext-diff", "--no-textconv")


def _invalid(path: Path, detail: str) -> ValidationError:
    message = i18n.t("evaluation.cases.invalid", file=path.name, detail=detail)
    return ValidationError("invalid_case", message, {"file": str(path)})


def validate(path: Path, store: Path, data: dict[str, Any], case: Case) -> None:
    """Refuse a review case that is malformed or whose ``expect`` lies outside its diff."""
    if "check" in data or "files" in data:
        raise _invalid(path, i18n.t("evaluation.cases.review_no_check"))
    if not case.head_commit:
        raise _invalid(path, i18n.t("evaluation.cases.head_required"))
    diff = store / DIFF_NAME
    if not diff.is_file():
        raise _invalid(path, i18n.t("evaluation.cases.diff_missing"))
    touched = touched_lines(diff.read_text(encoding="utf-8"))
    for e in case.expect:
        lines = touched.get(e.file, frozenset())
        if not any(e.first <= n <= e.last for n in lines):
            raise _invalid(path, i18n.t("evaluation.cases.expect_outside", file=e.file))


def review_case_passed(case: Case, kept: Sequence[FindingRecord]) -> bool:
    """A bug case passes when an important finding sits in an expected range; a clean case
    passes when no finding is important."""
    important = [f for f in kept if f.tag == "important"]
    if not case.expect:
        return not important
    return any(
        e.file == f.file and e.first <= f.line <= e.last for f in important for e in case.expect
    )
