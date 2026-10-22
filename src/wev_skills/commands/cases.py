"""Scored cases: list and validate the case set under ``evals/cases``."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._scope import resolve_scope
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.evaluation import cases, workspace

# Replaced by the configured score_timeout_seconds once that setting exists.
AT_BASE_TIMEOUT_SECONDS = 600.0


def _check_at_base(scope: Any, loaded: tuple[cases.Case, ...]) -> list[dict[str, Any]]:
    runner = SubprocessRunner()
    scratch = scope.state_dir / "scoring"
    results = []
    for case in loaded:
        with workspace.case_workspace(runner, scope.root, case, scratch) as path:
            result = workspace.run_check(runner, case, scope.root, path, AT_BASE_TIMEOUT_SECONDS)
        results.append({"id": case.id, "fails_at_base": not workspace.passed(result)})
    bad = [str(r["id"]) for r in results if not r["fails_at_base"]]
    if bad:
        message = i18n.t("evaluation.cases.passes_at_base", ids=", ".join(bad))
        raise ValidationError("case_passes_at_base", message, {"cases": results})
    return results


def _handle(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    root = scope.root
    loaded = cases.load_cases(root)
    if args.cases_command == "validate":
        payload: dict[str, Any] = {"valid": True, "count": len(loaded)}
        if args.at_base:
            payload["cases"] = _check_at_base(scope, loaded)
        return payload
    return {
        "cases": [case.to_dict() for case in loaded],
        "digest": cases.case_set_digest(root),
    }


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("cases", help=i18n.t("evaluation.cases.help"))
    actions = parser.add_subparsers(dest="cases_command", required=True)
    for name in ("list", "validate"):
        sub = actions.add_parser(name, help=i18n.t(f"evaluation.cases.{name}"))
        sub.set_defaults(handler=_handle)
        if name == "validate":
            sub.add_argument(
                "--at-base", action="store_true", help=i18n.t("evaluation.cases.at_base")
            )
