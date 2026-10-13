"""Staged compaction of engine-assembled context: elide old tool output, then summarize.

Archived originals are written as private files and are not redacted here: callers pass
redacted text. See the package docstring for what this module does not control.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.context.tokens import estimate_tokens
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError, WevError
from wev_skills.core.fsutil import atomic_write_text
from wev_skills.core.ports import Summarizer

KINDS = ("requirement", "decision", "error", "evidence", "tool_output", "note")
ALWAYS_PINNED = frozenset({"requirement", "decision", "evidence"})
SUMMARIZABLE = frozenset({"note", "error", "tool_output"})
ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ARCHIVE_SUFFIX = ".txt"


def _invalid(message: str) -> ValidationError:
    return ValidationError("invalid_context", message)


def validate_item_id(item_id: object) -> str:
    """Return ``item_id`` when it is safe as an archive file name; raise otherwise."""
    if not isinstance(item_id, str) or not ITEM_ID_RE.match(item_id):
        raise ValidationError("invalid_item_id", f"invalid context item id: {item_id!r}")
    return item_id


@dataclass(frozen=True)
class ContextItem(Serializable):
    id: str
    kind: str
    text: str
    tokens: int = 0
    created_seq: int = 0
    pinned: bool = False
    elided: bool = False
    summarized: bool = False
    ref: str = ""

    def __post_init__(self) -> None:
        validate_item_id(self.id)
        if self.kind not in KINDS:
            raise _invalid(f"item {self.id}: kind {self.kind!r} is not one of {list(KINDS)}")


@dataclass(frozen=True)
class CompactionReport(Serializable):
    elided_ids: tuple[str, ...]
    summarized_ids: tuple[str, ...]
    tokens_before: int
    tokens_after: int
    stage2_skipped_reason: str
    over_budget: bool


def _archive_path(archive_dir: Path, item_id: str) -> Path:
    return archive_dir / f"{validate_item_id(item_id)}{ARCHIVE_SUFFIX}"


def recall_archived(archive_dir: str | Path | None, item_id: str) -> str:
    """Original text archived for ``item_id``; ``NotFound`` when there is none."""
    validate_item_id(item_id)
    missing = NotFound("archive_not_found", f"no archived text for {item_id!r}", {"id": item_id})
    if archive_dir is None:
        raise missing
    path = _archive_path(Path(archive_dir), item_id)
    if path.is_symlink():
        raise PermissionDenied("archive_escape", f"archive entry for {item_id!r} is a link")
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise missing from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise WevError("archive_unreadable", f"cannot read archive for {item_id!r}: {exc}") from exc


def _archive(archive_dir: Path, item: ContextItem) -> None:
    """Persist the original text; never overwrite a different original with the same id."""
    path = _archive_path(archive_dir, item.id)
    try:
        if path.is_symlink():
            raise PermissionDenied("archive_escape", f"archive entry for {item.id!r} is a link")
        if path.exists():
            if path.read_text(encoding="utf-8") == item.text:
                return
            raise ValidationError(
                "archive_conflict", f"a different original is already archived as {item.id!r}"
            )
        atomic_write_text(path, item.text)
    except (OSError, UnicodeDecodeError) as exc:
        raise WevError("archive_write_failed", f"cannot archive {item.id!r}: {exc}") from exc


@dataclass(frozen=True)
class ContextManager:
    """Immutable budgeted context: ``add`` and ``compact`` return a new manager."""

    budget_tokens: int
    elide_at: float = 0.6
    summarize_at: float = 0.85
    summarizer: Summarizer | None = None
    archive_dir: str | Path | None = None
    min_elide_tokens: int = 200
    keep_recent: int = 3
    items: tuple[ContextItem, ...] = ()
    next_seq: int = 0

    def __post_init__(self) -> None:
        budget = self.budget_tokens
        if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
            raise _invalid("budget_tokens must be a positive integer")
        if not 0 < self.elide_at < self.summarize_at <= 1:
            raise _invalid("thresholds must satisfy 0 < elide_at < summarize_at <= 1")
        if self.min_elide_tokens < 0 or self.keep_recent < 0:
            raise _invalid("min_elide_tokens and keep_recent must not be negative")
        if self.archive_dir is not None:
            object.__setattr__(self, "archive_dir", Path(self.archive_dir))

    def add(self, item: ContextItem | Mapping[str, Any]) -> ContextManager:
        """Return a manager with ``item`` appended; tokens and sequence are set here."""
        fields = item.to_dict() if isinstance(item, ContextItem) else dict(item)
        fields.setdefault("id", f"item-{self.next_seq}")
        parsed = ContextItem.from_dict(fields)
        if any(existing.id == parsed.id for existing in self.items):
            raise _invalid(f"duplicate context item id: {parsed.id!r}")
        stored = replace(
            parsed,
            tokens=estimate_tokens(parsed.text),
            created_seq=self.next_seq,
            pinned=parsed.pinned or parsed.kind in ALWAYS_PINNED,
        )
        return replace(self, items=(*self.items, stored), next_seq=self.next_seq + 1)

    def total_tokens(self) -> int:
        return sum(item.tokens for item in self.items)

    def usage(self) -> float:
        return self.total_tokens() / self.budget_tokens

    def render(self) -> list[ContextItem]:
        return list(self.items)

    def recall(self, item_id: str) -> str:
        return recall_archived(self.archive_dir, item_id)

    def compact(self) -> tuple[ContextManager, CompactionReport]:
        """Run stage 1 (elide) and, if still needed, stage 2 (summarize).

        ``over_budget`` in the report means the context is still above the budget: the caller
        must surface that; nothing is ever truncated silently.
        """
        before = self.total_tokens()
        elided_manager, elided = self._elide()
        final, summarized, reason = elided_manager._summarize()
        after = final.total_tokens()
        over_budget = after > self.budget_tokens
        return final, CompactionReport(elided, summarized, before, after, reason, over_budget)

    def _recent(self, kind: str, count: int) -> frozenset[str]:
        """Ids of the ``count`` most recent unpinned items of ``kind``."""
        of_kind = [item.id for item in self.items if item.kind == kind and not item.pinned]
        return frozenset(of_kind[-count:]) if count > 0 else frozenset()

    def _stub(self, item: ContextItem) -> ContextItem:
        if isinstance(self.archive_dir, Path):
            ref = str(_archive_path(self.archive_dir, item.id))
            text = i18n.t("context.stub.archived", id=item.id, tokens=item.tokens, ref=ref)
        else:
            ref = ""
            text = i18n.t("context.stub.unarchived", id=item.id, tokens=item.tokens)
        return replace(item, text=text, tokens=estimate_tokens(text), elided=True, ref=ref)

    def _elide(self) -> tuple[ContextManager, tuple[str, ...]]:
        recent = self._recent("tool_output", self.keep_recent)
        total = self.total_tokens()
        stubs: dict[str, ContextItem] = {}
        for item in self.items:
            if total / self.budget_tokens < self.elide_at:
                break
            eligible = item.kind == "tool_output" and not (item.pinned or item.elided)
            if not eligible or item.id in recent or item.tokens < self.min_elide_tokens:
                continue
            stub = self._stub(item)
            if stub.tokens >= item.tokens:
                continue
            if isinstance(self.archive_dir, Path):
                _archive(self.archive_dir, item)
            stubs[item.id] = stub
            total -= item.tokens - stub.tokens
        items = tuple(stubs.get(item.id, item) for item in self.items)
        return replace(self, items=items), tuple(stubs)

    def _summary_candidates(self) -> list[ContextItem]:
        protected = (
            self._recent("tool_output", self.keep_recent)
            | self._recent("note", self.keep_recent)
            | self._recent("error", 1)
        )
        return [
            item
            for item in self.items
            if item.kind in SUMMARIZABLE and not item.pinned and item.id not in protected
        ]

    def _summarize(self) -> tuple[ContextManager, tuple[str, ...], str]:
        if self.usage() < self.summarize_at:
            return self, (), ""
        if self.summarizer is None:
            return self, (), i18n.t("context.stage2.no_summarizer")
        candidates = self._summary_candidates()
        if not candidates:
            return self, (), i18n.t("context.stage2.nothing_to_summarize")
        try:
            summary = self.summarizer.summarize(tuple(item.text for item in candidates))
        except Exception as exc:  # noqa: BLE001 - a failing provider must not lose context
            reason = i18n.t("context.stage2.summarizer_failed", error=type(exc).__name__)
            return self, (), reason
        if not isinstance(summary, str) or not summary.strip():
            return self, (), i18n.t("context.stage2.summarizer_failed", error="empty summary")
        if estimate_tokens(summary) >= sum(item.tokens for item in candidates):
            return self, (), i18n.t("context.stage2.summary_not_smaller")
        return self._apply_summary(candidates, summary)

    def _apply_summary(
        self, candidates: list[ContextItem], summary: str
    ) -> tuple[ContextManager, tuple[str, ...], str]:
        if isinstance(self.archive_dir, Path):
            for item in candidates:
                if not item.elided:
                    _archive(self.archive_dir, item)
        taken = {item.id for item in self.items}
        seq = self.next_seq
        while f"summary-{seq}" in taken:
            seq += 1
        merged = ContextItem(
            id=f"summary-{seq}",
            kind="note",
            text=summary,
            tokens=estimate_tokens(summary),
            created_seq=candidates[0].created_seq,
            summarized=True,
        )
        replaced = {item.id for item in candidates}
        kept = [item for item in self.items if item.id not in replaced]
        position = sum(1 for item in kept if item.created_seq < merged.created_seq)
        items = (*kept[:position], merged, *kept[position:])
        summarized = tuple(item.id for item in candidates)
        return replace(self, items=items, next_seq=seq + 1), summarized, ""
