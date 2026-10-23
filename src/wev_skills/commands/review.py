"""Layered review: ``review md check`` validates the repository's ``REVIEW.md``."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._scope import resolve_scope
from wev_skills.review import guide


def _md_check(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_scope(args.config).root
    loaded = guide.load_guide(root)
    return {"valid": True, "present": (root / guide.FILE_NAME).is_file(), "guide": asdict(loaded)}


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("review", help=i18n.t("review.md.help"))
    actions = parser.add_subparsers(dest="review_command", required=True)
    md = actions.add_parser("md", help=i18n.t("review.md.group_help"))
    md_actions = md.add_subparsers(dest="review_md_command", required=True)
    check = md_actions.add_parser("check", help=i18n.t("review.md.check_help"))
    check.set_defaults(handler=_md_check)
