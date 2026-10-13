"""``wev eval list|run|validate``: the scripted evaluation harness. No model is called."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.core.errors import NotFound, ValidationError
from wev_skills.evaluation import harness, report, tasks
from wev_skills.evaluation.configs import HarnessConfig, load_configs

FORMAT_JSON = "json"
FORMAT_MARKDOWN = "md"


def _sources(args: argparse.Namespace) -> tuple[Path, Path]:
    """Task directory and config file; the repository ``evals/`` is needed only for defaults."""
    if args.tasks_dir and args.configs:
        return Path(args.tasks_dir), Path(args.configs)
    root = tasks.resolve_evals_dir()
    tasks_dir = Path(args.tasks_dir) if args.tasks_dir else root / tasks.TASKS_SUBDIR
    configs_file = Path(args.configs) if args.configs else root / tasks.CONFIGS_FILE
    return tasks_dir, configs_file


def _select[Item: (tasks.EvalTask, HarnessConfig)](
    items: Sequence[Item], wanted: Sequence[str], what: str
) -> tuple[Item, ...]:
    """Keep the requested ids, in file order; every requested id must exist."""
    if not wanted:
        return tuple(items)
    known = {item.id for item in items}
    missing = sorted(set(wanted) - known)
    if missing:
        raise NotFound(
            "eval_id_not_found",
            i18n.t("eval.error.unknown_id", what=what, ids=", ".join(missing)),
            {"what": what, "missing": missing, "known": sorted(known)},
        )
    return tuple(item for item in items if item.id in wanted)


def _list(args: argparse.Namespace) -> dict[str, Any]:
    tasks_dir, configs_file = _sources(args)
    return {
        "tasks_dir": str(tasks_dir),
        "configs_file": str(configs_file),
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "category": task.category,
                "window_tokens": task.window_tokens,
                "subtasks": len(task.subtasks),
                "steps": len(task.script),
            }
            for task in tasks.load_tasks(tasks_dir)
        ],
        "configs": [
            {"id": config.id, "description": config.description}
            for config in load_configs(configs_file)
        ],
    }


def _write(path: str, text: str) -> None:
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ValidationError(
            "output_unwritable",
            i18n.t("eval.error.unwritable", path=path, error=str(exc)),
            {"path": path},
        ) from exc


def _run(args: argparse.Namespace) -> dict[str, Any]:
    tasks_dir, configs_file = _sources(args)
    chosen_tasks = _select(tasks.load_tasks(tasks_dir), args.task_ids, "task")
    chosen_configs = _select(load_configs(configs_file), args.config_ids, "config")
    result = harness.run(chosen_tasks, chosen_configs)
    lang = i18n.resolve_language(args.report_lang)
    markdown = args.format == FORMAT_MARKDOWN
    if not args.out:
        if not markdown:
            return report.to_document(result, lang)
        content = report.render_markdown(result, lang)
        note = report.notice(lang)
        return {"notice": note, "format": FORMAT_MARKDOWN, "language": lang, "content": content}
    text = report.render_markdown(result, lang) if markdown else report.render_json(result, lang)
    _write(args.out, text)
    return {
        "notice": report.notice(lang),
        "written": args.out,
        "format": args.format,
        "language": lang,
        "runs": len(result.runs),
        "tasks": list(result.task_ids),
        "configs": [config.id for config in result.configs],
    }


def _validate(args: argparse.Namespace) -> dict[str, Any]:
    task = tasks.load_task(args.task_file)
    return {
        "valid": True,
        "path": args.task_file,
        "id": task.id,
        "subtasks": len(task.subtasks),
        "steps": len(task.script),
    }


def _add_sources(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tasks-dir", default=None, help=i18n.t("eval.arg.tasks_dir"))
    parser.add_argument("--configs", default=None, help=i18n.t("eval.arg.configs"))


def register(subparsers: Subparsers) -> None:
    group = subparsers.add_parser("eval", help=i18n.t("eval.help"))
    actions = group.add_subparsers(dest="eval_command", metavar="<command>", required=True)

    listing = actions.add_parser("list", help=i18n.t("eval.list.help"))
    _add_sources(listing)
    listing.set_defaults(handler=_list)

    run = actions.add_parser("run", help=i18n.t("eval.run.help"))
    _add_sources(run)
    run.add_argument(
        "--task", dest="task_ids", action="append", default=[], help=i18n.t("eval.arg.task")
    )
    run.add_argument(
        "--config",
        dest="config_ids",
        action="append",
        default=[],
        help=i18n.t("eval.arg.config"),
    )
    run.add_argument("--out", default=None, help=i18n.t("eval.arg.out"))
    run.add_argument(
        "--format",
        choices=(FORMAT_JSON, FORMAT_MARKDOWN),
        default=FORMAT_JSON,
        help=i18n.t("eval.arg.format"),
    )
    run.add_argument("--lang", dest="report_lang", default=None, help=i18n.t("eval.arg.lang"))
    run.set_defaults(handler=_run)

    validate = actions.add_parser("validate", help=i18n.t("eval.validate.help"))
    validate.add_argument("task_file", help=i18n.t("eval.arg.task_file"))
    validate.set_defaults(handler=_validate)
