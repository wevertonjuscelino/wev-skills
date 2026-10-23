"""``reviews.jsonl``: one line per review round and per finding outcome, and the noise stats.

The file holds ids, tags, outcomes and counts only, never a title, body or reason. It is
local data an agent can edit, so ``review_stats`` skips lines it cannot trust.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.core.fsutil import append_line
from wev_skills.state.review_records import FindingRecord, ReviewRoundRecord

REVIEWS_FILE = "reviews.jsonl"
BY_PERSON, BY_AGENT, BY_ENGINE = "person", "agent", "engine"
OUTCOME_WRONG = "wrong"
TAGS = ("important", "nit", "pre_existing")
ROUND_COUNTS = (*TAGS, "skipped", "runs_used")


def _write(path: Path, line: dict[str, Any]) -> None:
    append_line(path, json.dumps(line, ensure_ascii=False))


def warn_unwritten(error: OSError, lang: str | None = None) -> None:
    """The round or the outcome is already committed to the run; a stats file that cannot be
    written costs only the stats, so it is a warning and never a failure."""
    print(i18n.t("review.warn.stats_unwritten", lang, error=error), file=sys.stderr)


def record_round(path: Path, at: str, run_id: str, record: ReviewRoundRecord) -> None:
    counts = {tag: sum(1 for f in record.findings if f.tag == tag) for tag in TAGS}
    _write(path, {
        "kind": "round", "at": at, "run_id": run_id, "round": record.number,
        "depth": record.depth, **counts, "skipped": record.skipped, "runs_used": record.runs_used,
    })  # fmt: skip


def record_outcome(
    path: Path, at: str, run_id: str, finding: FindingRecord, depth: str, by: str
) -> None:
    """``finding`` as closed (its outcome set); ``by`` is person, agent or engine."""
    _write(path, {
        "kind": "outcome", "at": at, "run_id": run_id, "finding": finding.id, "tag": finding.tag,
        "outcome": finding.outcome, "depth": depth, "round": finding.round, "by": by,
    })  # fmt: skip


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid(line: object) -> dict[str, Any] | None:
    """The line when it has the expected keys and types, else None."""
    if not isinstance(line, dict):
        return None
    strs = ("run_id", "depth")
    if line.get("kind") == "round":
        ok = all(_is_int(line.get(k)) for k in ("round", *ROUND_COUNTS))
        return line if ok and all(isinstance(line.get(k), str) for k in strs) else None
    if line.get("kind") == "outcome":
        keys = (*strs, "finding", "tag", "outcome", "by")
        ok = all(isinstance(line.get(k), str) for k in keys) and _is_int(line.get("round"))
        return line if ok else None
    return None


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines: list[dict[str, Any]] = []
    for raw in text.splitlines():
        try:
            line = _valid(json.loads(raw))
        except ValueError, RecursionError:
            continue
        if line is not None:
            lines.append(line)
    return lines


def _depth_stats(rounds: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    last: dict[str, int] = defaultdict(int)
    for row in rounds:
        last[row["run_id"]] = max(last[row["run_id"]], row["round"])
    found = sum(row[tag] for row in rounds for tag in TAGS)
    share: dict[str, float] = {}
    for name in sorted({row["outcome"] for row in outcomes}):
        share[name] = sum(1 for row in outcomes if row["outcome"] == name) / len(outcomes)
    return {
        "rounds": len(rounds),
        "runs": len(last),
        "findings_per_round": found / len(rounds) if rounds else 0.0,
        "outcome_share": share,
        "rounds_per_run": len(rounds) / len(last) if last else 0.0,
        "runs_passing_after_one_round": sum(1 for n in last.values() if n == 1),
    }


def review_stats(path: Path) -> dict[str, object]:
    """Per depth: findings per round, share by outcome, rounds per run, runs done after one
    round; plus the findings a person dismissed as ``wrong`` (ids only)."""
    lines = _read(path)
    depths = sorted({row["depth"] for row in lines})
    by_depth = {
        depth: _depth_stats(
            [r for r in lines if r["kind"] == "round" and r["depth"] == depth],
            [r for r in lines if r["kind"] == "outcome" and r["depth"] == depth],
        )
        for depth in depths
    }
    candidates = [
        {"run_id": r["run_id"], "finding": r["finding"]}
        for r in lines
        if r["kind"] == "outcome" and r["by"] == BY_PERSON and r["outcome"] == OUTCOME_WRONG
    ]
    return {"depths": by_depth, "clean_case_candidates": candidates}
