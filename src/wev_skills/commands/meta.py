"""``wev version`` and ``wev config show|validate``."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from wev_skills import __version__, i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._orchestration import project_root
from wev_skills.commands._scope import RUN_SOURCE_PREFIX, resolve_scope
from wev_skills.config import protect_state_dir, resolve_config
from wev_skills.decisions.jev_program import jev_warnings


def _version(args: argparse.Namespace) -> dict[str, Any]:
    return {"version": __version__}


def _config_show(args: argparse.Namespace) -> dict[str, Any]:
    """The configuration every other command would use here, and where it came from."""
    scope = resolve_scope(args.config, reads=True)
    shown: dict[str, Any] = {**scope.config.to_dict(), "config_source": scope.source}
    shown["config_sources"] = list(scope.sources)
    if scope.active is not None:
        shown["pinned_by_run"] = scope.source.removeprefix(RUN_SOURCE_PREFIX)
    shown["warnings"] = jev_warnings(scope.config, str(scope.root))
    return shown


def _config_validate(args: argparse.Namespace) -> dict[str, Any]:
    """Check ``PATH`` with the rules a run applies to the configuration it starts with."""
    root = project_root(Path.cwd())
    resolved = resolve_config(args.path, root)
    config = protect_state_dir(resolved.config, root)
    warnings = jev_warnings(config, str(root))
    return {
        "valid": True,
        "path": args.path,
        "config_source": resolved.source,
        "warnings": warnings,
    }


def register(subparsers: Subparsers) -> None:
    version = subparsers.add_parser("version", help=i18n.t("meta.version.help"))
    version.set_defaults(handler=_version)

    config = subparsers.add_parser("config", help=i18n.t("meta.config.help"))
    actions = config.add_subparsers(dest="config_command", metavar="<command>", required=True)
    show = actions.add_parser("show", help=i18n.t("meta.config.show.help"))
    show.set_defaults(handler=_config_show)
    validate = actions.add_parser("validate", help=i18n.t("meta.config.validate.help"))
    validate.add_argument("path", help=i18n.t("meta.config.validate.path"))
    validate.set_defaults(handler=_config_validate)
