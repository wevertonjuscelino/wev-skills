"""The refusals of ``run finish`` that layered review adds."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from wev_skills import i18n
from wev_skills.config import Config
from wev_skills.config_review import DEPTH_OFF
from wev_skills.core.errors import StateConflict, WevError
from wev_skills.evaluation.ratchet import improves
from wev_skills.state.model import RunState
from wev_skills.state.review_records import all_findings

REVIEW_FILE = "REVIEW.md"


def reviewer_path(config: Config) -> str:
    """The reviewer's spec, relative to the repository root."""
    return f"{config.agents.project_dir}/{config.review.agent}.json"


def _pass_counts(value: object) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(k, str) and type(v) is int for k, v in value.items()):
        return None
    return {str(k): int(v) for k, v in value.items()}


def _improving(record: Mapping[str, object], fingerprint: str, depth: str) -> bool:
    """A recorded comparison counts only when ``improves`` is true on its own numbers:
    a hand-edited flag does not pass."""
    baseline, current = _pass_counts(record.get("baseline")), _pass_counts(record.get("current"))
    if record.get("fingerprint") != fingerprint or record.get("depth") != depth:
        return False
    if baseline is None or current is None:
        return False
    return record.get("improves") is True and improves(baseline, current)


def finish_refusal(
    state: RunState,
    config: Config,
    fingerprint: str,
    touched: Mapping[str, frozenset[int]],
    comparisons: Sequence[Mapping[str, object]],
) -> WevError | None:
    """Why ``run finish`` must refuse, or None. Order: an open Important finding, a review
    that does not cover the tree, a changed reviewer that no comparison vouches for."""
    found = all_findings(state.review_rounds)
    open_ids = [f.id for f in found if f.tag == "important" and f.status == "open"]
    if open_ids:
        text = i18n.t("review.gate.open_important", ids=", ".join(open_ids))
        return StateConflict("review_open_important", text)
    depth = config.review.depth
    if depth == DEPTH_OFF:
        return None
    last = state.review_rounds[-1] if state.review_rounds else None
    if last is None or last.fingerprint != fingerprint:
        return StateConflict("review_stale", i18n.t("review.gate.stale"))
    changed = [p for p in (REVIEW_FILE, reviewer_path(config)) if p in touched]
    if changed and not any(_improving(c, fingerprint, depth) for c in comparisons):
        return StateConflict(
            "reviewer_unscored", i18n.t("review.gate.reviewer_unscored", paths=", ".join(changed))
        )
    return None


def read_comparisons(path: Path) -> list[dict[str, object]]:
    """The comparison records (lines with a ``compare`` key) of a scores file; a missing
    file gives none and a malformed line is skipped."""
    if not path.is_file():
        return []
    found: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and "compare" in record:
            found.append(record)
    return found
