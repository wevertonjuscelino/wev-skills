"""``wev plan set|show``: the plan of a run."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._orchestration import add_run_argument, orchestrator_for
from wev_skills.core.errors import ValidationError


def _set(args: argparse.Namespace) -> dict[str, Any]:
    if args.reason is not None and not args.amend:
        raise ValidationError("amend_flag_required", i18n.t("orch.error.amend_flag"))
    if args.amend and args.reason is None:
        raise ValidationError("amend_reason_required", i18n.t("orch.error.amend_reason"))
    return orchestrator_for(args).set_plan(args.file, args.reason if args.amend else None)


def _show(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args, reads=True).show_plan()


def register(subparsers: Subparsers) -> None:
    plan = subparsers.add_parser("plan", help=i18n.t("orch.plan.help"))
    actions = plan.add_subparsers(dest="plan_command", metavar="<command>", required=True)
    setter = actions.add_parser("set", help=i18n.t("orch.plan.set.help"))
    setter.add_argument("--file", required=True, help=i18n.t("orch.arg.plan_file"))
    setter.add_argument("--amend", action="store_true", help=i18n.t("orch.arg.amend"))
    setter.add_argument("--reason", default=None, help=i18n.t("orch.arg.amend_reason"))
    add_run_argument(setter)
    setter.set_defaults(handler=_set)
    show = actions.add_parser("show", help=i18n.t("orch.plan.show.help"))
    add_run_argument(show)
    show.set_defaults(handler=_show)
