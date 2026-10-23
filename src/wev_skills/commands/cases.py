"""Scored cases: list and validate the case set under ``evals/cases``."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._scope import resolve_scope
from wev_skills.core import wiring
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.evaluation import cases, workspace


def _check_at_base(scope: Any, loaded: tuple[cases.Case, ...]) -> list[dict[str, Any]]:
    runner = SubprocessRunner()
    policy = wiring.build_grantless_policy(scope.config, scope.root)
    scratch = Path(tempfile.mkdtemp(prefix="wev-scoring-"))
    try:
        results = _run_all(runner, policy, scope, loaded, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return _verdict(results)


def _run_all(
    runner: SubprocessRunner,
    policy: Any,
    scope: Any,
    loaded: tuple[cases.Case, ...],
    scratch: Path,
) -> list[dict[str, Any]]:
    results = []
    for case in loaded:
        with workspace.case_workspace(runner, scope.root, case, scratch) as path:
            result = workspace.run_check(
                runner,
                policy,
                case,
                scope.root,
                path,
                scope.config.specialists.score_timeout_seconds,
            )
        results.append(
            {
                "id": case.id,
                "fails_at_base": not workspace.passed(result),
                "timed_out": result.timed_out,
                "broken": workspace.not_started(result),
            }
        )
    return results


def _verdict(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for key, code, text in (
        ("broken", "case_check_broken", "evaluation.cases.check_broken"),
        ("fails_at_base", "case_passes_at_base", "evaluation.cases.passes_at_base"),
    ):
        bad = [str(r["id"]) for r in results if (r[key] if key == "broken" else not r[key])]
        if bad:
            raise ValidationError(code, i18n.t(text, ids=", ".join(bad)), {"cases": results})
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
