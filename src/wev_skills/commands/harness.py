"""``wev harness export|install|uninstall``: build the package files of one harness into a
directory, install them into the harness (recorded in a manifest), or undo that install."""

from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters import harness_install, harness_opencode
from wev_skills.adapters.harness_package import TARGETS, build_package, skipped_notes
from wev_skills.commands import Subparsers
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.core.wiring import REPO_ROOT

INSTALL_TARGETS = (*harness_install.INSTALLABLE, "opencode")


def _launcher(args: argparse.Namespace) -> Path:
    wev = Path(args.wev).resolve() if args.wev else REPO_ROOT / "bin" / "wev"
    if not wev.is_file():
        raise ValidationError(
            "wev_missing", i18n.t("harness.error.wev_missing", path=str(wev)), {"path": str(wev)}
        )
    return wev


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "opencode"


def _next_steps(target: str, link: tuple[str, ...]) -> list[str]:
    if target == "gemini":  # the person runs the link: it shows a security warning to accept
        return [
            i18n.t("harness.next.gemini_link", command=shlex.join(link)),
            i18n.t("harness.next.gemini_check"),
            i18n.t("harness.next.gemini_restart"),
        ]
    if target == "opencode":
        return [i18n.t("harness.next.opencode_restart"), i18n.t("harness.next.opencode_check")]
    return [i18n.t(key) for key in ("harness.next.codex_trust", "harness.next.codex_check")]


def _install_opencode(args: argparse.Namespace) -> dict[str, Any]:
    manifest = harness_opencode.install(_data_home(), _config_home(), _launcher(args))
    return {
        "target": manifest.target,
        "files": list(manifest.files),
        "registrations": [],
        "next_steps": _next_steps("opencode", ()),
        "skipped": skipped_notes("opencode"),
    }


def _install(args: argparse.Namespace) -> dict[str, Any]:
    if args.target == "opencode":
        return _install_opencode(args)
    manifest = harness_install.install(
        args.target, SubprocessRunner(), _data_home(), _launcher(args)
    )
    return {
        "target": manifest.target,
        "files": list(manifest.files),
        "registrations": [list(r) for r in manifest.registrations[0::2]],
        "next_steps": _next_steps(args.target, manifest.registrations[0]),
    }


def _uninstall(args: argparse.Namespace) -> dict[str, Any]:
    if args.target == "opencode":
        manifest = harness_opencode.uninstall(_data_home(), _config_home())
    else:
        manifest = harness_install.uninstall(args.target, SubprocessRunner(), _data_home())
    return {"target": manifest.target, "removed": list(manifest.files)}


def _export(args: argparse.Namespace) -> dict[str, Any]:
    wev = _launcher(args)
    out = Path(args.out).resolve()
    files = build_package(args.target, out, wev)
    return {
        "target": args.target,
        "out": str(out),
        "files": [str(p) for p in files],
        "skipped": skipped_notes(args.target),
    }


def register(subparsers: Subparsers) -> None:
    harness = subparsers.add_parser("harness", help=i18n.t("harness.help"))
    actions = harness.add_subparsers(dest="harness_command", metavar="<command>", required=True)
    export = actions.add_parser("export", help=i18n.t("harness.export.help"))
    export.add_argument("--target", required=True, choices=TARGETS,
                        help=i18n.t("harness.export.target"))  # fmt: skip
    export.add_argument("--out", required=True, help=i18n.t("harness.export.out"))
    export.add_argument("--wev", default=None, help=i18n.t("harness.export.wev"))
    export.set_defaults(handler=_export)
    for name, handler in (("install", _install), ("uninstall", _uninstall)):
        action = actions.add_parser(name, help=i18n.t(f"harness.{name}.help"))
        action.add_argument("--target", required=True, choices=INSTALL_TARGETS,
                            help=i18n.t(f"harness.{name}.target"))  # fmt: skip
        if name == "install":
            action.add_argument("--wev", default=None, help=i18n.t("harness.install.wev"))
        action.set_defaults(handler=handler)
