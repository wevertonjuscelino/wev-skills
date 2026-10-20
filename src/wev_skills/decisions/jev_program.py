"""Find the JEV program the way the executor finds any program, never on ``$PATH``.

A bare name is looked up only in the absolute ``permissions.exec_path`` directories; an
absolute path is accepted as long as it is not inside the run root, where the agent can
write, and it must be an existing regular executable file. When neither works the caller
falls back to the local policy and shows the reason, which names the two fixes: the program's
absolute path in ``decision.jev.command``, or its directory in ``permissions.exec_path``.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from pathlib import Path

from wev_skills import i18n
from wev_skills.config import BUILTIN, Config
from wev_skills.decisions.jev_key import env_file_path, macos_keychain, resolve_api_key
from wev_skills.decisions.jev_wire import JevUnavailable


def _inside(base: Path, path: Path) -> bool:
    return path == base or base in path.parents


def resolve_jev_program(command: str, exec_path: Sequence[str], root: str | None) -> str:
    """The absolute path ``command`` names; ``JevUnavailable`` when it cannot be trusted."""
    safe = os.pathsep.join(entry for entry in exec_path if os.path.isabs(entry))
    absolute = os.path.isabs(command)
    if absolute:
        usable = os.path.isfile(command) and os.access(command, os.X_OK)
        found: str | None = command if usable else None
    else:
        found = shutil.which(command, path=safe or os.devnull)
    if found is None:
        key = "decisions.jev.why.not_a_file" if absolute else "decisions.jev.why.not_on_path"
        raise JevUnavailable("binary_missing", i18n.t(key, program=command))
    base = Path(root or os.getcwd()).resolve()
    if _inside(base, Path(found).resolve()):
        raise JevUnavailable(
            "program_in_run_root", i18n.t("decisions.jev.why.in_run_root", program=command)
        )
    return found


def _key_warnings() -> list[str]:
    try:
        key = resolve_api_key(os.environ, env_file_path(), macos_keychain)
    except JevUnavailable as exc:
        return [i18n.t("decisions.jev.warning_key", why=exc.message or exc.code)]
    if key is not None:
        return []
    why = i18n.t("decisions.jev.why.key_missing")
    return [i18n.t("decisions.jev.warning_key", why=why)]


def jev_warnings(config: Config, root: str | None) -> list[str]:
    """Warnings for a configuration that selects JEV but names a program that cannot be used."""
    if config.decision.provider != "jev":
        return []
    if config.decision.jev.command == BUILTIN:
        return _key_warnings()
    try:
        resolve_jev_program(config.decision.jev.command, config.permissions.exec_path, root)
    except JevUnavailable as exc:
        return [i18n.t("decisions.jev.warning", why=exc.message or exc.code)]
    return []
