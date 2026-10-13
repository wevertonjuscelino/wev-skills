"""Budgeting for the context the engine itself assembles (contracts, summaries, logs).

Scope, stated plainly: this package manages only the items the engine puts together and
hands out. It has no access to, and no control over, the model runtime's own context window
(for example Claude Code's conversation context): it cannot read it, measure it, compact it,
or clear it. Token counts here are estimates (see ``context.tokens``), not tokenizer output.
"""

from __future__ import annotations

from wev_skills.context.manager import (
    ALWAYS_PINNED,
    KINDS,
    CompactionReport,
    ContextItem,
    ContextManager,
    recall_archived,
    validate_item_id,
)
from wev_skills.context.tokens import estimate_tokens

__all__ = [
    "ALWAYS_PINNED",
    "KINDS",
    "CompactionReport",
    "ContextItem",
    "ContextManager",
    "estimate_tokens",
    "recall_archived",
    "validate_item_id",
]
