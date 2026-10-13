"""``wev context compact|recall``: compaction of engine-assembled context items.

The CLI injects no summarizer, so stage 2 is always reported as skipped here.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._orchestration import config_for
from wev_skills.context.manager import ContextManager, recall_archived
from wev_skills.core.errors import NotFound, ValidationError


def _read_items(path: str) -> list[dict[str, Any]]:
    """Items from a JSON file holding either a list or ``{"items": [...]}``."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise NotFound("file_not_found", f"file not found: {path}", {"path": path}) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "invalid_items_file", f"cannot read items from {path}: {exc}", {"path": path}
        ) from exc
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValidationError(
            "invalid_items_file", f"{path}: expected a list of item objects", {"path": path}
        )
    return items


def _compact(args: argparse.Namespace) -> dict[str, Any]:
    settings = config_for(args).context
    manager = ContextManager(
        budget_tokens=args.budget if args.budget is not None else settings.budget_tokens,
        elide_at=settings.elide_at,
        summarize_at=settings.summarize_at,
        archive_dir=args.archive_dir,
    )
    for item in _read_items(args.items_file):
        manager = manager.add(item)
    compacted, report = manager.compact()
    return {
        "items": [item.to_dict() for item in compacted.render()],
        "usage": compacted.usage(),
        "report": report.to_dict(),
    }


def _recall(args: argparse.Namespace) -> dict[str, Any]:
    return {"id": args.id, "text": recall_archived(args.archive_dir, args.id)}


def register(subparsers: Subparsers) -> None:
    context = subparsers.add_parser("context", help=i18n.t("context.help"))
    actions = context.add_subparsers(dest="context_command", metavar="<command>", required=True)
    compact = actions.add_parser("compact", help=i18n.t("context.compact.help"))
    compact.add_argument("--items-file", required=True, help=i18n.t("context.arg.items_file"))
    compact.add_argument("--budget", type=int, default=None, help=i18n.t("context.arg.budget"))
    compact.add_argument("--archive-dir", default=None, help=i18n.t("context.arg.archive_dir"))
    compact.set_defaults(handler=_compact)
    recall = actions.add_parser("recall", help=i18n.t("context.recall.help"))
    recall.add_argument("--archive-dir", required=True, help=i18n.t("context.arg.archive_dir"))
    recall.add_argument("id", help=i18n.t("context.arg.id"))
    recall.set_defaults(handler=_recall)
