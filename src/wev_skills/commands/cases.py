"""Scored cases: list and validate the case set under ``evals/cases``."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._scope import resolve_scope
from wev_skills.evaluation import cases


def _handle(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_scope(args.config).root
    loaded = cases.load_cases(root)
    if args.cases_command == "validate":
        return {"valid": True, "count": len(loaded)}
    return {
        "cases": [case.to_dict() for case in loaded],
        "digest": cases.case_set_digest(root),
    }


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("cases", help=i18n.t("evaluation.cases.help"))
    actions = parser.add_subparsers(dest="cases_command", required=True)
    for name in ("list", "validate"):
        actions.add_parser(name, help=i18n.t(f"evaluation.cases.{name}")).set_defaults(
            handler=_handle
        )
