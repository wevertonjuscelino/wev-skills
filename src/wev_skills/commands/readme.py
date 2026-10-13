"""``wev readme check``: check README.md and README.pt-BR.md against the README standard."""

from __future__ import annotations

import argparse
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.claude_code import claude_md, readme_check
from wev_skills.cli import EXIT_USAGE, CommandResult
from wev_skills.commands import Subparsers


def _check(args: argparse.Namespace) -> CommandResult:
    cwd = Path.cwd()
    root = claude_md.find_repo_root(cwd)
    directory = readme_check.resolve_directory(root, cwd / args.dir if args.dir else cwd)
    report = readme_check.check_directory(
        directory,
        root,
        twin=False if args.no_twin else None,
        credits_last=args.credits_last,
    )
    return CommandResult(report.to_dict(), exit_code=0 if report.ok else EXIT_USAGE)


def register(subparsers: Subparsers) -> None:
    group = subparsers.add_parser("readme", help=i18n.t("readme.help"))
    actions = group.add_subparsers(dest="readme_command", metavar="<command>", required=True)
    check = actions.add_parser("check", help=i18n.t("readme.check.help"))
    check.add_argument("--dir", default=None, help=i18n.t("readme.arg.dir"))
    check.add_argument("--no-twin", action="store_true", help=i18n.t("readme.arg.no_twin"))
    check.add_argument(
        "--credits-last",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=i18n.t("readme.arg.credits_last"),
    )
    check.set_defaults(handler=_check)
