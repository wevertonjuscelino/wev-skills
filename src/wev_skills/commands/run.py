"""``wev run start|status|resume|brief|finish|report``: the life of one orchestration run."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.cli import CommandResult
from wev_skills.commands import Subparsers
from wev_skills.commands._fence import fence_discovery
from wev_skills.commands._orchestration import (
    add_run_argument,
    new_orchestrator,
    orchestrator_for,
)
from wev_skills.commands.decide import add_signal_args, signals_from
from wev_skills.core.contracts import Mode
from wev_skills.core.orchestrator import START_MODES
from wev_skills.core.report_markdown import render_markdown

FORMATS = ("json", "md")


def _start(args: argparse.Namespace) -> dict[str, Any]:
    signals = signals_from(args)
    orchestrator, run_id = new_orchestrator(args, args.run_id)
    started = orchestrator.start(signals.objective, Mode(args.mode), signals, run_id)
    return fence_discovery(started)


def _status(args: argparse.Namespace) -> dict[str, Any]:
    return fence_discovery(orchestrator_for(args).status())


def _resume(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args).resume()


def _brief(args: argparse.Namespace) -> CommandResult:
    lang = i18n.resolve_language(args.brief_lang)
    return CommandResult(orchestrator_for(args).brief(args.max_chars, lang), raw=True)


def _finish(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args).finish()


def _report(args: argparse.Namespace) -> CommandResult:
    lang = i18n.resolve_language(args.report_lang)
    report = orchestrator_for(args).report(lang)
    if args.format == "md":
        return CommandResult(render_markdown(report, lang), raw=True)
    return CommandResult(report)


def register(subparsers: Subparsers) -> None:
    run = subparsers.add_parser("run", help=i18n.t("orch.run.help"))
    actions = run.add_subparsers(dest="run_command", metavar="<command>", required=True)

    start = actions.add_parser("start", help=i18n.t("orch.run.start.help"))
    add_signal_args(start)
    start.add_argument(
        "--mode",
        choices=[mode.value for mode in START_MODES],
        default=Mode.AUTO.value,
        help=i18n.t("orch.arg.mode"),
    )
    start.add_argument("--run-id", default=None, help=i18n.t("orch.arg.run_id"))
    start.set_defaults(handler=_start)

    for name, handler in (("status", _status), ("resume", _resume)):
        parser = actions.add_parser(name, help=i18n.t(f"orch.run.{name}.help"))
        add_run_argument(parser)
        parser.set_defaults(handler=handler)

    brief = actions.add_parser("brief", help=i18n.t("orch.run.brief.help"))
    brief.add_argument("--run", default=None, help=i18n.t("orch.arg.active_run"))
    brief.add_argument("--max-chars", type=int, default=None, help=i18n.t("orch.arg.max_chars"))
    brief.add_argument(
        "--lang", dest="brief_lang", default=None, help=i18n.t("orch.arg.brief_lang")
    )
    brief.set_defaults(handler=_brief)

    finish = actions.add_parser("finish", help=i18n.t("orch.run.finish.help"))
    finish.add_argument("--run", default=None, help=i18n.t("orch.arg.active_run"))
    finish.set_defaults(handler=_finish)

    report = actions.add_parser("report", help=i18n.t("orch.run.report.help"))
    add_run_argument(report)
    report.add_argument("--format", choices=FORMATS, default="json", help=i18n.t("orch.arg.format"))
    report.add_argument(
        "--lang", dest="report_lang", default=None, help=i18n.t("orch.arg.report_lang")
    )
    report.set_defaults(handler=_report)
