"""``rea.json``, the per-user choice of how rea runs. It is data: validated, never obeyed."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

from wev_skills import i18n
from wev_skills.config import user_config_home
from wev_skills.core.errors import ValidationError
from wev_skills.core.fsutil import atomic_write_text

Mode = Literal["isolated", "direct"]
MODES: tuple[str, ...] = get_args(Mode)
CONFIG_FILE = "rea.json"


@dataclass(frozen=True)
class ReaConfig:
    mode: Mode


def rea_config_path() -> Path:
    return user_config_home() / CONFIG_FILE


def _invalid(path: Path, why: str) -> ValidationError:
    message = i18n.t("rea.error.config_invalid", path=str(path), why=why)
    return ValidationError("rea_config_invalid", message)


def _parse(path: Path, data: object) -> ReaConfig:
    if not isinstance(data, dict) or set(data) != {"mode"}:
        raise _invalid(path, "root")
    mode = data["mode"]
    if not isinstance(mode, str) or mode not in MODES:
        raise _invalid(path, "mode")
    return ReaConfig("isolated" if mode == "isolated" else "direct")


def load_rea_config(path: Path, docker_found: bool) -> tuple[ReaConfig, str]:
    """The configuration and where it came from: ``"config"`` or ``"default"``."""
    if not path.is_file():
        return ReaConfig("isolated" if docker_found else "direct"), "default"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _invalid(path, type(exc).__name__) from exc
    return _parse(path, data), "config"


def save_rea_config(path: Path, cfg: ReaConfig) -> None:
    atomic_write_text(path, json.dumps({"mode": cfg.mode}, indent=2) + "\n")
