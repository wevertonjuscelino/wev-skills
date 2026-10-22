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
from wev_skills.core.errors import (
    NotFound,
    PermissionDenied,
    RemoteError,
    StateConflict,
    ValidationError,
)
from wev_skills.core.ports import Runner, SubprocessRunner
from wev_skills.rea import image as image_mod
from wev_skills.rea import launch
from wev_skills.rea.config import MODES, load_rea_config, rea_config_path, save_rea_config
from wev_skills.third_party import state as state_mod


def _exec_path(args: argparse.Namespace) -> tuple[str, ...]:
    """The configured safe path (``permissions.exec_path``), never ``$PATH``."""
    root = find_repo_root(Path.cwd())
    return resolve_config(args.config, root).config.permissions.exec_path


def _which(name: str, args: argparse.Namespace) -> str | None:
    """``name`` on the safe path, as its resolved real path. A program that is, or resolves
    to, a file inside the repository is refused (an agent can write there, and a
    ``wev.config.json`` could point the path at it). That is all it checks: it does not vouch
    for other writable directories on ``permissions.exec_path``."""
    entries = [entry for entry in _exec_path(args) if os.path.isabs(entry)]
    found = shutil.which(name, path=os.pathsep.join(entries) or os.devnull)
    if found is None:
        return None
    root = find_repo_root(Path.cwd()).resolve()
    located, resolved = Path(found).absolute(), Path(found).resolve()
    if any(path == root or root in path.parents for path in (located, resolved)):
        raise PermissionDenied(
            "program_in_run_root", i18n.t("rea.error.program_in_run_root", program=name)
        )
    return str(resolved)


def _which_or_none(name: str, args: argparse.Namespace) -> str | None:
    """For ``status`` and ``mode``, which only report: a refused program counts as missing."""
    try:
        return _which(name, args)
    except PermissionDenied:
        return None


def _runner() -> Runner:
    return SubprocessRunner()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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
    cfg, _ = load_rea_config(rea_config_path(), _which_or_none("docker", args) is not None)
    version = _version()
    docker = npx = None
    if cfg.mode == "isolated":
        docker = _which("docker", args)
        if docker is None:
            raise ValidationError("rea_docker_missing", i18n.t("rea.error.docker_missing"))
    else:
        npx = _which("npx", args)
        if npx is None:
            raise NotFound("rea_npx_missing", i18n.t("rea.error.npx_missing"))
    home = _rea_home()
    argv = launch.serve_argv(cfg, version, Path.cwd(), home, docker or "docker", npx or "npx")
    if args.dry_run:
        return {"argv": list(argv)}
    if cfg.mode == "isolated":
        _require_image(docker or "docker", version)
        _ensure_rea_home(home)
    launch.serve(argv)


def _require_image(docker: str, version: str) -> None:
    """Isolated mode never falls back to direct: a missing daemon or image stops here."""
    runner = _runner()
    if not image_mod.docker_available(runner, docker):
        raise RemoteError("docker_unavailable", i18n.t("rea.error.docker_unavailable"))
    tag = image_mod.image_tag(version)
    if not image_mod.image_present(tag, runner, docker):
        raise StateConflict("rea_image_missing", i18n.t("rea.error.image_missing", tag=tag))


def _run_build_image(args: argparse.Namespace) -> dict[str, Any]:
    version = args.version or _version()
    docker = _which("docker", args)
    if docker is None:
        raise ValidationError("rea_docker_missing", i18n.t("rea.error.docker_missing"))
    tag = image_mod.build_image(version, _runner(), docker, _repo_root())
    return {"image": tag, "built": True}


def _image_present(tag: str | None, docker: str | None) -> bool | None:
    """Whether the image exists; ``None`` (unknown) without a version, Docker or its daemon."""
    if tag is None or docker is None:
        return None
    runner = _runner()
    return (
        image_mod.image_present(tag, runner, docker)
        if image_mod.docker_available(runner, docker)
        else None
    )


def _run_status(args: argparse.Namespace) -> dict[str, Any]:
    docker = _which_or_none("docker", args)
    cfg, source = load_rea_config(rea_config_path(), docker is not None)
    item = state_mod.load(state_mod.data_home() / "state.json").sources.get("rea")
    version = item.active if item else None
    image = f"{launch.IMAGE_PREFIX}:{version}" if version else None
    present = _image_present(image, docker)
    warnings = [i18n.t(f"rea.warning.{cfg.mode}")]
    if cfg.mode == "isolated" and docker is None:
        warnings.append(i18n.t("rea.warning.docker_missing"))
    return {
        "mode": cfg.mode,
        "mode_source": source,
        "version": version,
        "image": image,
        "docker": "found" if docker else "missing",
        "image_present": present,
        "warnings": warnings,
    }


def _run_mode(args: argparse.Namespace) -> dict[str, Any]:
    docker = _which_or_none("docker", args)
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
    building = commands.add_parser("build-image", help=i18n.t("rea.build.help"))
    building.add_argument("--version", help=i18n.t("rea.build.version"))
    building.set_defaults(handler=_run_build_image)
    moding = commands.add_parser("mode", help=i18n.t("rea.mode.help"))
    moding.add_argument("mode", choices=MODES, help=i18n.t("rea.mode.choice"))
    moding.set_defaults(handler=_run_mode)
