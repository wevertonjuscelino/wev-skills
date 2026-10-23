"""Layered review: ``review run|show|stats|resolve|dismiss`` and ``review md check``.

``review dismiss`` is a human-operator command: it needs a terminal and a typed word
(``commands._human``), and an agent never runs it.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._agent_runner import claude_agent_runner
from wev_skills.commands._human import confirm_human, summary_lines
from wev_skills.commands._orchestration import add_run_argument, locate, orchestrator_for
from wev_skills.commands._scope import resolve_scope
from wev_skills.core.textsafe import clean_text
from wev_skills.review import guide, resolve
from wev_skills.review.round import run_round
from wev_skills.review.stats import REVIEWS_FILE, review_stats
from wev_skills.review.summary import STATUS_OPEN, summarize
from wev_skills.state.review_records import FindingRecord, all_findings

SHOWN_MAX = 300


def _md_check(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_scope(args.config).root
    loaded = guide.load_guide(root)
    return {"valid": True, "present": (root / guide.FILE_NAME).is_file(), "guide": asdict(loaded)}


def _shown(finding: FindingRecord) -> dict[str, Any]:
    """The finding as a dict, with a round-closed ``resolved_by`` (``round:N``) in words."""
    data = finding.to_dict()
    kind, _, number = finding.resolved_by.partition(":")
    if kind == "round" and number:
        data["resolved_by"] = i18n.t("review.resolved_by.round", number=number)
    return data


def _run(args: argparse.Namespace) -> dict[str, Any]:
    engine = orchestrator_for(args)
    agent = claude_agent_runner(engine.services.config, engine.services.runner)
    record = run_round(engine, agent, i18n.resolve_language())
    return {"run_id": engine.load().run_id, "round": record.to_dict(), "summary": record.summary}


def _show(args: argparse.Namespace) -> dict[str, Any]:
    state = orchestrator_for(args, reads=True).load()
    findings = all_findings(state.review_rounds)
    last = state.review_rounds[-1] if state.review_rounds else None
    summary = summarize(findings, last.skipped if last else 0, i18n.resolve_language())
    return {
        "run_id": state.run_id,
        "round": last.to_dict() if last else None,
        "open": [_shown(f) for f in findings if f.status == STATUS_OPEN],
        "summary": summary,
    }


def _stats(args: argparse.Namespace) -> dict[str, Any]:
    return review_stats(locate(args).state_dir / REVIEWS_FILE)


def _resolve(args: argparse.Namespace) -> dict[str, Any]:
    engine = orchestrator_for(args)
    return resolve.close(
        engine, args.finding, args.outcome, args.reason, resolve.RESOLVED_BY_AGENT, False
    )


def _dismiss(args: argparse.Namespace) -> dict[str, Any]:
    engine = orchestrator_for(args)
    found = resolve.find(engine.load(), args.finding)
    shown = {
        "finding": found.id,
        "where": f"{found.file}:{found.line}",
        "tag": found.tag,
        "title": clean_text(found.title, SHOWN_MAX),
        "as": args.outcome,
        "reason": clean_text(args.reason, SHOWN_MAX),
    }
    confirmed = confirm_human(
        engine.services.audit,
        "review.dismiss_refused",
        {"finding_id": found.id},
        i18n.t("review.error.human_required", id=found.id),
        summary_lines(i18n.t("review.confirm.dismiss"), shown),
    )
    result = resolve.close(engine, found.id, args.outcome, args.reason, confirmed.label(), True)
    return {**result, "operator": confirmed.os_user, "confirmation": confirmed.label()}


def _decision_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("finding", help=i18n.t("review.arg.finding"))
    parser.add_argument(
        "--as", dest="outcome", required=True, choices=resolve.OUTCOMES,
        help=i18n.t("review.arg.outcome"),
    )  # fmt: skip
    parser.add_argument("--reason", required=True, help=i18n.t("review.arg.reason"))
    add_run_argument(parser)


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("review", help=i18n.t("review.md.help"))
    actions = parser.add_subparsers(dest="review_command", required=True)
    md = actions.add_parser("md", help=i18n.t("review.md.group_help"))
    md_actions = md.add_subparsers(dest="review_md_command", required=True)
    check = md_actions.add_parser("check", help=i18n.t("review.md.check_help"))
    check.set_defaults(handler=_md_check)

    run = actions.add_parser("run", help=i18n.t("review.run.help"))
    add_run_argument(run)
    run.set_defaults(handler=_run)
    show = actions.add_parser("show", help=i18n.t("review.show.help"))
    add_run_argument(show)
    show.set_defaults(handler=_show)
    stats = actions.add_parser("stats", help=i18n.t("review.stats.help"))
    stats.set_defaults(handler=_stats)
    closing = actions.add_parser("resolve", help=i18n.t("review.resolve.help"))
    _decision_arguments(closing)
    closing.set_defaults(handler=_resolve)
    human_only = i18n.t("review.dismiss.help")
    dismiss = actions.add_parser("dismiss", help=human_only, description=human_only)
    _decision_arguments(dismiss)
    dismiss.set_defaults(handler=_dismiss)
