"""Project specialists: create, list, learn from engine records and export.

``accept`` and ``retire`` are the human operator's decisions on a proposed lesson: they need
a terminal and a typed word (``commands._human``), and an agent never runs them.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from wev_skills import i18n
from wev_skills.agents import project
from wev_skills.agents.experience import AUTHORED_MAX, LESSON_TEXT_MAX, Lesson
from wev_skills.commands import Subparsers
from wev_skills.commands._human import confirm_human, summary_lines
from wev_skills.commands._scope import resolve_scope
from wev_skills.commands._scoring import score
from wev_skills.core import wiring
from wev_skills.core.textsafe import clean_text
from wev_skills.evaluation.scoring import SCORES_FILE
from wev_skills.governance.audit import AuditLog

DECISIONS = {"accept": project.accept_lesson, "retire": project.retire_lesson}


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


def _shown(specialist: str, lesson: Lesson) -> dict[str, str]:
    """Everything the decision covers: the full text, each authored excerpt and the note, each
    cut exactly as ``experience.render_lesson`` cuts it, so the operator sees what is shown."""
    fields = {
        "specialist": specialist,
        "lesson": lesson.id,
        "status": lesson.status,
        "text": clean_text(lesson.text, LESSON_TEXT_MAX),
        "evidence": f"{lesson.evidence.run_id} / {lesson.evidence.task_id}",
    }
    for index, item in enumerate(lesson.authored, 1):
        label, text = clean_text(item.label, AUTHORED_MAX), clean_text(item.text, AUTHORED_MAX)
        fields[f"authored {index}"] = f"{label}: {text}"
    if lesson.note:
        fields["note"] = clean_text(lesson.note, AUTHORED_MAX)
    return fields


def _decide(args: argparse.Namespace) -> dict[str, Any]:
    """Show the lesson, require the person at the terminal, then record the decision."""
    scope = resolve_scope(args.config)
    verb, subject = args.specialists_command, {"specialist": args.id, "lesson": args.lesson}
    lesson = project.find_lesson(scope.root, scope.config, args.id, args.lesson)
    audit = AuditLog(scope.state_dir / wiring.AUDIT_FILE)
    shown = _shown(args.id, lesson)
    confirmed = confirm_human(
        audit,
        f"specialists.{verb}_refused",
        subject,
        i18n.t("agents.specialists.human_required", **subject),
        summary_lines(i18n.t(f"agents.specialists.confirm.{verb}"), shown),
    )
    event = {**subject, "operator": confirmed.os_user, "terminal": confirmed.terminal}
    spec = DECISIONS[verb](
        scope.root,
        scope.config,
        (args.id, args.lesson),
        confirmed.os_user,
        lesson,
        lambda: audit.append(f"specialists.{verb}", event),
    )
    return {
        "specialist": project.summary(spec),
        "operator": confirmed.os_user,
        "confirmation": confirmed.label(),
        "config_source": scope.source,
    }


def _score(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    return {"score": score(scope, args.id).to_dict(), "config_source": scope.source}


def _scores(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    path = scope.state_dir / SCORES_FILE
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    found = [json.loads(line) for line in lines if line.strip()]
    kept = [item for item in found if args.id is None or item.get("agent") == args.id]
    return {"scores": kept, "config_source": scope.source}


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
    action = actions.add_parser("score", help=i18n.t("agents.specialists.score"))
    action.set_defaults(handler=_score)
    action.add_argument("id")
    action = actions.add_parser("scores", help=i18n.t("agents.specialists.scores"))
    action.set_defaults(handler=_scores)
    action.add_argument("id", nargs="?", default=None)
