"""``wev guard evaluate|signature`` (pure) and ``wev guard check`` (over a recorded run)."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from wev_skills import i18n
from wev_skills.cli import CommandResult
from wev_skills.commands import Subparsers
from wev_skills.commands._human import confirm_human, summary_lines
from wev_skills.commands._orchestration import config_for, orchestrator_for
from wev_skills.core.contracts import GuardAction
from wev_skills.core.errors import GuardTripped, NotFound, ValidationError
from wev_skills.guards.events import GuardEvent, command_signature
from wev_skills.guards.execution import GuardLimits, GuardVerdict, evaluate


def _read_events(path: str) -> tuple[GuardEvent, ...]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise NotFound("file_not_found", f"file not found: {path}", {"path": path}) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(
            "file_unreadable", f"cannot read {path}: {exc}", {"path": path}
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "invalid_json", f"{path} is not valid JSON: {exc}", {"path": path}
        ) from exc
    items = data.get("events") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValidationError("invalid_events", i18n.t("guard.error.events_shape"), {"path": path})
    return tuple(GuardEvent.from_dict(item, _path=f"/events/{i}") for i, item in enumerate(items))


def verdict_result(verdict: GuardVerdict, extra: dict[str, Any] | None = None) -> CommandResult:
    """The verdict on stdout; exit 6 (the ``GuardTripped`` code) unless it says CONTINUE."""
    tripped = verdict.action is not GuardAction.CONTINUE
    payload = {**verdict.to_dict(), **(extra or {})}
    return CommandResult(payload, GuardTripped.exit_code if tripped else 0)


def _evaluate(args: argparse.Namespace) -> CommandResult:
    events = _read_events(args.events_file)
    limits = GuardLimits.from_config(config_for(args).limits)
    verdict = evaluate(events, limits, now=args.now, unresolved_dependencies=tuple(args.dep))
    return verdict_result(verdict)


def _check(args: argparse.Namespace) -> CommandResult:
    orchestrator = orchestrator_for(args)
    verdict = orchestrator.guard_check(args.task)
    return verdict_result(verdict, {"run_id": orchestrator.store.run_dir.name})


def _acknowledge(args: argparse.Namespace) -> dict[str, Any]:
    orchestrator = orchestrator_for(args)
    shown = {"run": args.run, "task": args.task or "-", "reason": args.reason}
    confirmed = confirm_human(
        orchestrator.services.audit,
        "guard.acknowledge_refused",
        {"run_id": args.run, "task_id": args.task or ""},
        i18n.t("guard.error.human_required", run=args.run),
        summary_lines(i18n.t("guard.confirm.acknowledge"), shown),
    )
    return orchestrator.acknowledge_guard(
        args.task, args.reason, confirmed.os_user, confirmed.label()
    )


def _signature(args: argparse.Namespace) -> dict[str, Any]:
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise ValidationError("missing_argv", i18n.t("guard.signature.argv"))
    cwd = os.path.abspath(args.cwd) if args.cwd else None
    return {"signature": command_signature(argv, cwd), "argv": argv, "cwd": cwd}


def register(subparsers: Subparsers) -> None:
    guard = subparsers.add_parser("guard", help=i18n.t("guard.help"))
    actions = guard.add_subparsers(dest="guard_command", metavar="<command>", required=True)

    evaluate_parser = actions.add_parser("evaluate", help=i18n.t("guard.evaluate.help"))
    evaluate_parser.add_argument(
        "--events-file", required=True, help=i18n.t("guard.evaluate.events")
    )
    evaluate_parser.add_argument(
        "--now", type=float, default=None, help=i18n.t("guard.evaluate.now")
    )
    evaluate_parser.add_argument(
        "--dep", action="append", default=[], help=i18n.t("guard.evaluate.deps")
    )
    evaluate_parser.set_defaults(handler=_evaluate)

    check = actions.add_parser("check", help=i18n.t("orch.guard.check.help"))
    check.add_argument("--run", default=None, help=i18n.t("orch.arg.run"))
    check.add_argument("--task", default=None, help=i18n.t("orch.arg.guard_task"))
    check.set_defaults(handler=_check)

    human_only = i18n.t("guard.acknowledge.help")
    acknowledge = actions.add_parser("acknowledge", help=human_only, description=human_only)
    acknowledge.add_argument("--run", required=True, help=i18n.t("guard.acknowledge.run"))
    acknowledge.add_argument("--task", default=None, help=i18n.t("guard.acknowledge.task"))
    acknowledge.add_argument("--reason", required=True, help=i18n.t("guard.acknowledge.reason"))
    acknowledge.set_defaults(handler=_acknowledge)

    signature = actions.add_parser("signature", help=i18n.t("guard.signature.help"))
    signature.add_argument("--cwd", default=None, help=i18n.t("guard.signature.cwd"))
    signature.add_argument("argv", nargs=argparse.REMAINDER, help=i18n.t("guard.signature.argv"))
    signature.set_defaults(handler=_signature)
