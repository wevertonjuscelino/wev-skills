"""The refusals of ``run finish`` that layered review adds."""

from __future__ import annotations

import json
import posixpath
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from wev_skills import i18n
from wev_skills.config import (
    CONFIG_FILE_NAME,
    SOURCE_DEFAULTS,
    SOURCE_JOIN,
    Config,
    resolve_config,
    user_config_path,
)
from wev_skills.config_review import DEPTH_OFF, PRESETS
from wev_skills.core.errors import StateConflict, WevError
from wev_skills.evaluation.ratchet import improves
from wev_skills.state.model import RunState
from wev_skills.state.review_records import all_findings

REVIEW_FILE = "REVIEW.md"
DEPTHS = (DEPTH_OFF, *PRESETS)
"""Depths from the weakest to the strongest."""


def _norm(path: str) -> str:
    return posixpath.normpath(path)


def reviewer_path(config: Config) -> str:
    """The reviewer's spec, relative to the repository root, in the form git prints."""
    return _norm(f"{config.agents.project_dir}/{config.review.agent}.json")


def current_config(source: str, root: Path) -> Config | None:
    """The effective configuration now, resolved as the run's start did: the single file of
    ``source`` when it is neither the repository file nor the user file (an explicit
    ``--config``), else the user file under the repository's. None when it cannot be resolved."""
    files = [] if source == SOURCE_DEFAULTS else source.split(SOURCE_JOIN)
    tiers = {str(root / CONFIG_FILE_NAME), str(user_config_path())}
    explicit = files[0] if len(files) == 1 and files[0] not in tiers else None
    try:
        return resolve_config(explicit, root).config
    except WevError:
        return None


def config_weakened(pinned: Config, current: Config | None) -> bool:
    """True when ``current`` lowers the pinned ``review.depth`` or changes ``review.agent`` or
    ``agents.project_dir``; a configuration that cannot be read counts. Only meaningful when
    the pinned depth is not off (turning review on is never weakening)."""
    if current is None:
        return True
    return (
        DEPTHS.index(current.review.depth) < DEPTHS.index(pinned.review.depth)
        or current.review.agent != pinned.review.agent
        or _norm(current.agents.project_dir) != _norm(pinned.agents.project_dir)
    )


def _pass_counts(value: object) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(k, str) and type(v) is int for k, v in value.items()):
        return None
    return {str(k): int(v) for k, v in value.items()}


def _improving(record: Mapping[str, object], fingerprint: str, depth: str, agent: str) -> bool:
    """A recorded comparison counts only when ``improves`` is true on its own numbers:
    a hand-edited flag does not pass."""
    baseline, current = _pass_counts(record.get("baseline")), _pass_counts(record.get("current"))
    if record.get("fingerprint") != fingerprint or record.get("depth") != depth:
        return False
    if record.get("agent") != agent:  # the comparison must be of the configured reviewer
        return False
    if baseline is None or current is None:
        return False
    return record.get("improves") is True and improves(baseline, current)


def finish_refusal(
    state: RunState,
    config: Config,
    fingerprint: str,
    changed: Collection[str],
    comparisons: Sequence[Mapping[str, object]],
    weakened: bool = False,
) -> WevError | None:
    """Why ``run finish`` must refuse, or None. Order: an open Important finding, a review
    that does not cover the tree, a changed reviewer that no comparison vouches for."""
    found = all_findings(state.review_rounds)
    open_ids = [f.id for f in found if f.tag == "important" and f.status == "open"]
    if open_ids:
        text = i18n.t("review.gate.open_important", ids=", ".join(open_ids))
        return StateConflict("review_open_important", text)
    if weakened:
        return StateConflict("review_config_weakened", i18n.t("review.gate.config_weakened"))
    depth = config.review.depth
    if depth == DEPTH_OFF:
        return None
    last = state.review_rounds[-1] if state.review_rounds else None
    if last is None or last.fingerprint != fingerprint:
        return StateConflict("review_stale", i18n.t("review.gate.stale"))
    protected = [p for p in (REVIEW_FILE, reviewer_path(config)) if p in changed]
    if protected and not any(
        _improving(c, fingerprint, depth, config.review.agent) for c in comparisons
    ):
        return StateConflict(
            "reviewer_unscored", i18n.t("review.gate.reviewer_unscored", paths=", ".join(protected))
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
