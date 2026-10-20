"""Project specialists: create, list, learn from engine records and export.

``accept`` and ``retire`` are the human operator's decisions on a proposed lesson: they need
a terminal and a typed word (``commands._human``), and an agent never runs them.
"""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.agents import project
from wev_skills.commands import Subparsers
from wev_skills.commands._human import confirm_human, summary_lines
from wev_skills.commands._scope import resolve_scope
from wev_skills.core import wiring
from wev_skills.core.textsafe import clean_text
from wev_skills.governance.audit import AuditLog

DECISIONS = {"accept": project.accept_lesson, "retire": project.retire_lesson}
SHOWN_TEXT_MAX = 200


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


def _decide(args: argparse.Namespace) -> dict[str, Any]:
    """Show the lesson, require the person at the terminal, then record the decision."""
    scope = resolve_scope(args.config)
    verb, subject = args.specialists_command, {"specialist": args.id, "lesson": args.lesson}
    lesson = project.find_lesson(scope.root, scope.config, args.id, args.lesson)
    audit = AuditLog(scope.state_dir / wiring.AUDIT_FILE)
    shown = {
        "specialist": args.id,
        "lesson": lesson.id,
        "status": lesson.status,
        "text": clean_text(lesson.text, SHOWN_TEXT_MAX),
        "evidence": f"{lesson.evidence.run_id} / {lesson.evidence.task_id}",
    }
    confirmed = confirm_human(
        audit,
        f"specialists.{verb}_refused",
        subject,
        i18n.t("agents.specialists.human_required", **subject),
        summary_lines(i18n.t(f"agents.specialists.confirm.{verb}"), shown),
    )
    spec = DECISIONS[verb](scope.root, scope.config, args.id, args.lesson, confirmed.os_user)
    audit.append(f"specialists.{verb}", {**subject, "operator": confirmed.os_user})
    return {
        "specialist": project.summary(spec),
        "operator": confirmed.os_user,
        "confirmation": confirmed.label(),
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
    for name in DECISIONS:
        action = actions.add_parser(name, help=i18n.t(f"agents.specialists.{name}"))
        action.set_defaults(handler=_decide)
        action.add_argument("id")
        action.add_argument("lesson")
