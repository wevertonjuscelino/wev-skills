"""The argv for the rea server and the exec that replaces this process with it. No shell.

Only the validated version, the mode, the checked working directory and the wev-owned home
directory reach the argv; nothing else from the environment or from repository content does.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn

from wev_skills import i18n
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.rea.config import ReaConfig
from wev_skills.third_party.fetch import mcp_argv
from wev_skills.third_party.state import State

REA_HOME_MOUNT = "/opt/rea-home"
IMAGE_PREFIX = "wev-rea"
SEMVER_RE = re.compile(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?")
"""npm also takes dist-tags (``latest``) and ranges; only an exact version is pinned."""
MOUNT_SYNTAX = (":", ",")


def pinned_version(state: State) -> str:
    item = state.sources.get("rea")
    if item is None or item.active is None:
        raise StateConflict("rea_not_installed", i18n.t("rea.error.not_installed"))
    return item.active


def checked_version(version: str) -> str:
    if not SEMVER_RE.fullmatch(version):
        raise ValidationError("rea_version_invalid", i18n.t("rea.error.version_invalid"))
    return version


def _plain_path(path: Path) -> str:
    """``path`` as text, refused when ``--volume`` would read it as mount syntax or when it
    holds a control character."""
    text = str(path)
    if any(c in text for c in MOUNT_SYNTAX) or any(ch < " " for ch in text):
        raise ValidationError("rea_path_refused", i18n.t("rea.error.path_refused"))
    return text


def _checked_cwd(cwd: Path) -> Path:
    """The resolved working directory; ``/``, the account home and its parents are refused,
    because mounting them would expose the whole account to the container."""
    resolved, account = cwd.resolve(), Path.home().resolve()
    if resolved == account or resolved in account.parents:
        raise ValidationError("rea_cwd_refused", i18n.t("rea.error.cwd_refused", cwd=str(resolved)))
    return resolved


def serve_argv(
    cfg: ReaConfig,
    version: str,
    cwd: Path,
    home: Path,
    docker: str = "docker",
    npx: str = "npx",
) -> tuple[str, ...]:
    checked_version(version)
    if cfg.mode == "direct":
        return (npx, *mcp_argv(version)[1:])
    work = _checked_cwd(cwd)
    if not home.is_absolute():
        raise ValidationError("rea_path_refused", i18n.t("rea.error.path_refused"))
    work_text, home_text = _plain_path(work), _plain_path(home)
    return (
        docker, "run", "--rm", "-i", "--init",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--network", "bridge",
        "--volume", f"{work_text}:{work_text}:ro",
        "--workdir", work_text,
        "--volume", f"{home_text}:{REA_HOME_MOUNT}",
        f"{IMAGE_PREFIX}:{version}",
    )  # fmt: skip


def serve(
    argv: Sequence[str], execvp: Callable[[str, list[str]], NoReturn] = os.execvp
) -> NoReturn:
    execvp(argv[0], list(argv))
