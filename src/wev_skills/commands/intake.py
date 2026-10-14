"""Bounded interview CLI: start, set, next, finish and show."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._orchestration import locate
from wev_skills.intake import model
from wev_skills.intake.model import IntakeRecord, QuestionRound
from wev_skills.intake.store import IntakeStore


def _handle(args: argparse.Namespace) -> dict[str, Any]:
    location = locate(args)
    store = IntakeStore(location.state_dir, location.resolved.config.limits.lock_timeout_seconds)
    action = args.intake_command
    if action == "start":
        intake_id, record = store.start(args.request)
        return {"id": intake_id, "intake": record.to_dict(), "missing": list(model.missing(record))}
    intake_id = args.id
    if action == "set":
        record = store.update(
            intake_id,
            lambda current: model.set_field(current, args.field, tuple(args.value), args.source),
        )
    elif action == "next":
        rounds: list[QuestionRound] = []

        def transition(current: IntakeRecord) -> IntakeRecord:
            after, questions = model.next_round(current, location.resolved.config.intake.max_rounds)
            rounds.append(questions)
            return after

        record = store.update(intake_id, transition)
        return {"id": intake_id, "intake": record.to_dict(), "round": rounds[0].to_dict()}
    elif action == "finish":
        record = store.update(intake_id, lambda current: model.finish(current)[0])
    else:
        record = store.load(intake_id)
    result = {"id": intake_id, "intake": record.to_dict(), "missing": list(model.missing(record))}
    if record.complete:
        brief = model.finish(record)[1]
        result.update(
            brief=brief.to_dict(), run_start_command=model.run_start_command(brief, intake_id)
        )
    return result


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("intake", help=i18n.t("intake.help"))
    actions = parser.add_subparsers(dest="intake_command", required=True)
    for name in ("start", "set", "next", "finish", "show"):
        action = actions.add_parser(name, help=i18n.t(f"intake.help.{name}"))
        if name == "start":
            action.add_argument("--request", required=True, help=i18n.t("intake.arg.request"))
        else:
            action.add_argument("id", help=i18n.t("intake.arg.id"))
        if name == "set":
            action.add_argument("--field", required=True, choices=model.FIELDS)
            action.add_argument("--value", action="append", default=[])
            action.add_argument("--source", choices=model.SOURCES, default="answer")
        action.set_defaults(handler=_handle)
