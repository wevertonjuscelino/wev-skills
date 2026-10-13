"""``wev claude-md init|update|check|show``: manage the guidelines block of a CLAUDE.md."""

from __future__ import annotations

import argparse
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.claude_code import claude_md as cm
from wev_skills.cli import EXIT_USAGE, CommandResult
from wev_skills.commands import Subparsers
from wev_skills.core.discovery import discover_checks


def _target(args: argparse.Namespace) -> Path:
    cwd = Path.cwd()
    directory = cwd / args.dir if args.dir else cwd
    return cm.resolve_target(cm.find_repo_root(cwd), directory)


def _render(plan: cm.ClaudeMdPlan, status: str) -> CommandResult:
    parts = [*plan.notes, plan.diff.rstrip("\n"), status]
    return CommandResult("\n".join(part for part in parts if part), raw=True)


def _finish(plan: cm.ClaudeMdPlan, target: Path, dry_run: bool) -> CommandResult:
    if dry_run:
        return _render(plan, i18n.t("claudemd.status.dry_run"))
    if not cm.apply(plan, target):
        return _render(plan, i18n.t("claudemd.status.unchanged", None, path=str(target)))
    return _render(plan, i18n.t("claudemd.status.written", None, path=str(target)))


def _init(args: argparse.Namespace) -> CommandResult:
    target = _target(args)
    existing = cm.read_existing(target)
    discovered = discover_checks(target.parent) if existing is None else ()
    lang = i18n.resolve_language(args.block_lang)
    plan = cm.plan_init(existing, lang, discovered, path=str(target))
    return _finish(plan, target, args.dry_run)


def _update(args: argparse.Namespace) -> CommandResult:
    target = _target(args)
    lang = i18n.resolve_language(args.block_lang)
    plan = cm.plan_update(cm.read_existing(target), lang, path=str(target))
    return _finish(plan, target, args.dry_run)


def _check(args: argparse.Namespace) -> CommandResult:
    target = _target(args)
    report = cm.check(cm.read_existing(target), discover_checks(target.parent))
    return CommandResult(report.to_dict(), exit_code=0 if report.ok else EXIT_USAGE)


def _show(args: argparse.Namespace) -> CommandResult:
    return CommandResult(cm.render_block(i18n.resolve_language(args.block_lang)), raw=True)


def _add_lang(parser: argparse.ArgumentParser) -> None:
    # dest differs from the global --lang so the subparser default cannot overwrite it.
    parser.add_argument("--lang", dest="block_lang", default=None, help=i18n.t("claudemd.arg.lang"))


def _add_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir", default=None, help=i18n.t("claudemd.arg.dir"))


def register(subparsers: Subparsers) -> None:
    group = subparsers.add_parser("claude-md", help=i18n.t("claudemd.help"))
    actions = group.add_subparsers(dest="claude_md_command", metavar="<command>", required=True)
    for name, handler in (("init", _init), ("update", _update)):
        sub = actions.add_parser(name, help=i18n.t(f"claudemd.{name}.help"))
        _add_dir(sub)
        _add_lang(sub)
        sub.add_argument("--dry-run", action="store_true", help=i18n.t("claudemd.arg.dry_run"))
        sub.set_defaults(handler=handler)
    check = actions.add_parser("check", help=i18n.t("claudemd.check.help"))
    _add_dir(check)
    check.set_defaults(handler=_check)
    show = actions.add_parser("show", help=i18n.t("claudemd.show.help"))
    _add_lang(show)
    show.set_defaults(handler=_show)
