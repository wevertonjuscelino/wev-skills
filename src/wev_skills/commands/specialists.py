"""Project specialists: create, list, learn from engine records and export."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.agents import project
from wev_skills.commands import Subparsers
from wev_skills.commands._scope import resolve_scope


def _handle(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    root, config = scope.root, scope.config
    if args.specialists_command == "create":
        spec = project.create(root, config, args.id, args.template, tuple(args.specialty))
        return {"specialist": project.summary(spec), "config_source": scope.source}
    if args.specialists_command == "learn":
        spec = project.learn(root, config, args.id)
        return {"specialist": project.summary(spec), "config_source": scope.source}
    if args.specialists_command == "export":
        paths = project.export(root, config, args.export_lang)
        return {"exported": [str(path) for path in paths], "config_source": scope.source}
    return {
        "specialists": [project.summary(spec) for spec in project.list_specs(root, config)],
        "config_source": scope.source,
    }


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("specialists", help=i18n.t("agents.specialists.help"))
    actions = parser.add_subparsers(dest="specialists_command", required=True)
    for name in ("list", "create", "learn", "export"):
        action = actions.add_parser(name, help=i18n.t(f"agents.specialists.{name}"))
        action.set_defaults(handler=_handle)
        if name in ("create", "learn"):
            action.add_argument("id")
        if name == "create":
            action.add_argument("--template", default="senior-engineer")
            action.add_argument("--specialty", action="append", default=[])
        if name == "export":
            action.add_argument("--lang", dest="export_lang", default=None)
