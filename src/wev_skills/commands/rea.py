"""``wev rea``: launch the rea MCP server in the mode the person chose."""

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.config import find_repo_root, resolve_config
from wev_skills.core.errors import NotFound, ValidationError
from wev_skills.rea import launch
from wev_skills.rea.config import MODES, load_rea_config, rea_config_path, save_rea_config
from wev_skills.third_party import state as state_mod


def _exec_path(args: argparse.Namespace) -> tuple[str, ...]:
    """The configured safe path (``permissions.exec_path``), never ``$PATH``."""
    root = find_repo_root(Path.cwd())
    return resolve_config(args.config, root).config.permissions.exec_path


def _which(name: str, args: argparse.Namespace) -> str | None:
    entries = [entry for entry in _exec_path(args) if os.path.isabs(entry)]
    return shutil.which(name, path=os.pathsep.join(entries) or os.devnull)


def _rea_home() -> Path:
    return state_mod.data_home().parent / "rea" / "home"


def _ensure_rea_home(home: Path) -> None:
    """Create ``rea/`` and ``rea/home`` private; a symlink in either place would redirect the
    writable mount, so it is refused."""
    for directory in (home.parent, home):
        if directory.is_symlink():
            raise ValidationError(
                "rea_home_refused", i18n.t("rea.error.home_refused", path=str(directory))
            )
    home.mkdir(parents=True, exist_ok=True)
    home.parent.chmod(0o700)
    home.chmod(0o700)


def _version() -> str:
    return launch.pinned_version(state_mod.load(state_mod.data_home() / "state.json"))


def _run_serve(args: argparse.Namespace) -> dict[str, Any]:
    docker, npx = _which("docker", args), _which("npx", args)
    cfg, _ = load_rea_config(rea_config_path(), docker is not None)
    version = _version()
    if cfg.mode == "isolated" and docker is None:
        raise ValidationError("rea_docker_missing", i18n.t("rea.error.docker_missing"))
    if cfg.mode == "direct" and npx is None:
        raise NotFound("rea_npx_missing", i18n.t("rea.error.npx_missing"))
    home = _rea_home()
    argv = launch.serve_argv(cfg, version, Path.cwd(), home, docker or "docker", npx or "npx")
    if args.dry_run:
        return {"argv": list(argv)}
    if cfg.mode == "isolated":
        _ensure_rea_home(home)
    launch.serve(argv)


def _run_status(args: argparse.Namespace) -> dict[str, Any]:
    docker = _which("docker", args)
    cfg, source = load_rea_config(rea_config_path(), docker is not None)
    item = state_mod.load(state_mod.data_home() / "state.json").sources.get("rea")
    version = item.active if item else None
    image = f"{launch.IMAGE_PREFIX}:{version}" if version else None
    return {
        "mode": cfg.mode,
        "mode_source": source,
        "version": version,
        "image": image,
        "docker": "found" if docker else "missing",
        "image_present": None,
        "warnings": [i18n.t(f"rea.warning.{cfg.mode}")],
    }


def _run_mode(args: argparse.Namespace) -> dict[str, Any]:
    docker = _which("docker", args)
    if args.mode == "isolated" and docker is None:
        raise ValidationError("rea_docker_missing", i18n.t("rea.error.docker_missing"))
    current, _ = load_rea_config(rea_config_path(), docker is not None)
    save_rea_config(rea_config_path(), replace(current, mode=args.mode))
    return {"mode": args.mode, "warnings": [i18n.t(f"rea.warning.{args.mode}")]}


def register(subparsers: Subparsers) -> None:
    group = subparsers.add_parser("rea", help=i18n.t("rea.group.help"))
    commands = group.add_subparsers(dest="rea_command", required=True)
    serving = commands.add_parser("serve", help=i18n.t("rea.serve.help"))
    serving.add_argument("--dry-run", action="store_true", help=i18n.t("rea.serve.dry_run"))
    serving.set_defaults(handler=_run_serve)
    commands.add_parser("status", help=i18n.t("rea.status.help")).set_defaults(handler=_run_status)
    moding = commands.add_parser("mode", help=i18n.t("rea.mode.help"))
    moding.add_argument("mode", choices=MODES, help=i18n.t("rea.mode.choice"))
    moding.set_defaults(handler=_run_mode)
