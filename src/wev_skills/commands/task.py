"""``wev task next|start|check|record|review|reopen|tools`` and ``wev exec``."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.cli import CommandResult
from wev_skills.commands import Handler, Subparsers
from wev_skills.commands._human import confirm_human, summary_lines
from wev_skills.commands._orchestration import add_run_argument, orchestrator_for, remainder
from wev_skills.config import read_json_object
from wev_skills.core.contracts import Evidence, TaskStatus
from wev_skills.core.errors import ValidationError
from wev_skills.execution import untrusted_output

OUTCOMES = ("verified", "partial", "blocked", "failed", "not_executed")
VERDICTS = ("accept", "reject")
EVIDENCE_KEY = "evidence"


def _next(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args).next_tasks()


def _start(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args).start_task(args.task)


def _check(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args).check_task(args.task, args.stop_on_failure)


def read_evidence(path: str | None) -> tuple[Evidence, ...]:
    """Manual evidence from ``{"evidence": [...]}``; each item names its criterion in ``kind``."""
    if path is None:
        return ()
    items = read_json_object(path).get(EVIDENCE_KEY)
    if not isinstance(items, list):
        message = i18n.t("orch.error.evidence_file", path=path)
        raise ValidationError("invalid_evidence_file", message, {"path": path})
    return tuple(Evidence.from_dict(item, f"/{EVIDENCE_KEY}/{i}") for i, item in enumerate(items))


def _record(args: argparse.Namespace) -> dict[str, Any]:
    return orchestrator_for(args).record_task(
        args.task,
        TaskStatus(args.status),
        args.summary,
        tuple(args.changed_file),
        tuple(args.blocker),
        read_evidence(args.evidence_file),
    )


def _review(args: argparse.Namespace) -> dict[str, Any]:
    accepted = args.verdict == VERDICTS[0]
    return orchestrator_for(args).review_task(args.task, args.reviewer, accepted, args.summary)


def _tools(args: argparse.Namespace) -> dict[str, Any]:
    """Restore one tool that selection dropped for a running task (counted as a miss)."""
    return orchestrator_for(args).restore_tool(args.task, args.add, args.reason)


def _reopen(args: argparse.Namespace) -> dict[str, Any]:
    """Human-operator command, with the same friction as approving or acknowledging."""
    orchestrator = orchestrator_for(args)
    run_id = orchestrator.store.run_dir.name
    shown = {"run": run_id, "task": args.task, "reason": args.reason}
    confirmed = confirm_human(
        orchestrator.services.audit,
        "task.reopen_refused",
        {"run_id": run_id, "task_id": args.task},
        i18n.t("orch.error.reopen_human", run=run_id),
        summary_lines(i18n.t("orch.confirm.reopen"), shown),
    )
    return orchestrator.reopen_task(args.task, args.reason, confirmed.os_user, confirmed.label())


def _exec(args: argparse.Namespace) -> CommandResult:
    argv = remainder(args.argv)
    if not argv:
        raise ValidationError("missing_command", i18n.t("orch.error.missing_command"))
    payload, exit_code = orchestrator_for(args).exec_command(
        argv, args.task, args.timeout, args.polling, args.flaky
    )
    return CommandResult({**payload, "record": untrusted_output(payload["record"])}, exit_code)


def _task_parser(
    actions: Subparsers, name: str, handler: Handler, task: bool = True
) -> argparse.ArgumentParser:
    parser = actions.add_parser(name, help=i18n.t(f"orch.task.{name}.help"))
    if task:
        parser.add_argument("task", help=i18n.t("orch.arg.task"))
    add_run_argument(parser)
    parser.set_defaults(handler=handler)
    return parser


def _register_exec(subparsers: Subparsers) -> None:
    run = subparsers.add_parser("exec", help=i18n.t("orch.exec.help"))
    add_run_argument(run)
    run.add_argument("--task", default=None, help=i18n.t("orch.arg.exec_task"))
    run.add_argument("--timeout", type=float, default=None, help=i18n.t("orch.arg.timeout"))
    run.add_argument("--polling", action="store_true", help=i18n.t("orch.arg.polling"))
    run.add_argument("--flaky", action="store_true", help=i18n.t("orch.arg.flaky"))
    run.add_argument("argv", nargs=argparse.REMAINDER, help=i18n.t("orch.arg.argv"))
    run.set_defaults(handler=_exec)


def register(subparsers: Subparsers) -> None:
    task = subparsers.add_parser("task", help=i18n.t("orch.task.help"))
    actions = task.add_subparsers(dest="task_command", metavar="<command>", required=True)
    _task_parser(actions, "next", _next, task=False)
    _task_parser(actions, "start", _start)
    check = _task_parser(actions, "check", _check)
    check.add_argument(
        "--stop-on-failure",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=i18n.t("orch.arg.stop_on_failure"),
    )
    record = _task_parser(actions, "record", _record)
    record.add_argument("--status", required=True, choices=OUTCOMES, help=i18n.t("orch.arg.status"))
    record.add_argument("--summary", required=True, help=i18n.t("orch.arg.summary"))
    record.add_argument(
        "--changed-file", action="append", default=[], help=i18n.t("orch.arg.changed_file")
    )
    record.add_argument("--blocker", action="append", default=[], help=i18n.t("orch.arg.blocker"))
    record.add_argument("--evidence-file", default=None, help=i18n.t("orch.arg.evidence_file"))
    review = _task_parser(actions, "review", _review)
    review.add_argument("--reviewer", required=True, help=i18n.t("orch.arg.reviewer"))
    review.add_argument(
        "--verdict", required=True, choices=VERDICTS, help=i18n.t("orch.arg.verdict")
    )
    review.add_argument("--summary", required=True, help=i18n.t("orch.arg.summary"))
    reopen = _task_parser(actions, "reopen", _reopen)
    reopen.add_argument("--reason", required=True, help=i18n.t("orch.arg.reopen_reason"))
    tools = _task_parser(actions, "tools", _tools)
    tools.add_argument("--add", required=True, metavar="TOOL", help=i18n.t("orch.arg.tool_add"))
    tools.add_argument("--reason", required=True, help=i18n.t("orch.arg.tool_reason"))
    _register_exec(subparsers)
