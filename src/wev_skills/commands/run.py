"""``wev run start|status|resume|brief|finish|report|adopt``: the life of one orchestration run."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from typing import Any

from wev_skills import i18n
from wev_skills.cli import CommandResult
from wev_skills.commands import Subparsers
from wev_skills.commands._fence import fence_discovery
from wev_skills.commands._human import confirm_human, summary_lines
from wev_skills.commands._orchestration import (
    add_run_argument,
    locate,
    new_orchestrator,
    orchestrator_for,
)
from wev_skills.commands.decide import add_signal_args, signals_from
from wev_skills.core import active, run_start
from wev_skills.core.contracts import Mode
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.core.orchestrator import START_MODES, Orchestrator
from wev_skills.core.report_markdown import render_markdown
from wev_skills.intake.store import load_brief
from wev_skills.state.model import Phase, with_discovery

FORMATS = ("json", "md")


def _start(args: argparse.Namespace) -> dict[str, Any]:
    intake_id = args.from_intake
    brief = load_brief(locate(args).state_dir, intake_id) if intake_id else None
    if brief is not None:
        if args.objective is not None and args.objective != brief.goal:
            raise ValidationError(
                "intake_objective_mismatch", i18n.t("intake.error.objective_mismatch")
            )
        args.objective = brief.goal
    signals = signals_from(args)
    if brief is not None:
        signals = replace(
            signals,
            external_side_effects=signals.external_side_effects or brief.kind == "operations",
            unknowns=max(signals.unknowns, len(brief.assumptions)),
        )
    orchestrator, run_id = new_orchestrator(args, args.run_id)
    started = orchestrator.start(signals.objective, Mode(args.mode), signals, run_id)
    if brief is not None:
        orchestrator.commit(
            lambda state: with_discovery(
                state, "intake", {"id": intake_id, "brief": brief.to_dict()}
            ),
            "run.intake_attached",
            {"intake_id": intake_id, "brief": brief.to_dict()},
        )
        started.update(intake_id=intake_id, intake_brief=brief.to_dict())
    return fence_discovery(started)


def _status(args: argparse.Namespace) -> dict[str, Any]:
    orchestrator = orchestrator_for(args, reads=True)
    registered = active.is_registered(orchestrator.services.state_dir, _run_id(orchestrator))
    return {**fence_discovery(orchestrator.status()), "registered": registered}


def _run_id(orchestrator: Orchestrator) -> str:
    return orchestrator.store.run_dir.name


def _resume(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args).resume()


def _brief(args: argparse.Namespace) -> CommandResult:
    lang = i18n.resolve_language(args.brief_lang)
    return CommandResult(orchestrator_for(args, reads=True).brief(args.max_chars, lang), raw=True)


def _finish(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args).finish()


def _adopt(args: argparse.Namespace) -> dict[str, Any]:
    """Human-operator command: register a run found in the tree, after the person has read
    its pinned configuration, so the engine applies it as policy."""
    orchestrator = orchestrator_for(args, reads=True)
    services, run_id = orchestrator.services, _run_id(orchestrator)
    state = orchestrator.store.load()
    if state.phase is Phase.DONE:
        message = i18n.t("orch.error.adopt_finished", run=run_id)
        raise StateConflict("run_finished", message, {"run_id": run_id})
    if not active.is_registered(services.state_dir, run_id):
        shown = {
            "run": run_id,
            "root": services.root,
            "state_dir": services.state_dir,
            "mode": state.mode.value,
            "objective": state.objective,
            "config": json.dumps(dict(state.config), sort_keys=True),
        }
        confirmed = confirm_human(
            services.audit,
            "run.adopt_refused",
            {"run_id": run_id},
            i18n.t("orch.error.adopt_human", run=run_id),
            summary_lines(i18n.t("orch.confirm.adopt"), shown),
        )
        run_start.register(orchestrator, run_id)
        services.audit.append("run.adopted", {"run_id": run_id, "operator": confirmed.label()})
    return {"run_id": run_id, "registered": True, "state_dir": str(services.state_dir)}


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
    start.add_argument("--from-intake", default=None, help=i18n.t("intake.arg.from_intake"))
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

    adopt = actions.add_parser("adopt", help=i18n.t("orch.run.adopt.help"))
    adopt.add_argument("--run", default=None, help=i18n.t("orch.arg.active_run"))
    adopt.set_defaults(handler=_adopt)

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
