"""Reading configuration files and finding where they live (no knowledge of the schema)."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from wev_skills.core.errors import NotFound, ValidationError

GIT_MARKER = ".git"
USER_CONFIG_DIR = "wev-skills"


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict: nested mappings merge, everything else is replaced by ``override``."""
    merged: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def read_json_object(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise NotFound("file_not_found", f"file not found: {path}", {"path": path}) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(
            "file_unreadable", f"cannot read {path}: {exc}", {"path": path}
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "invalid_json", f"{path} is not valid JSON: {exc}", {"path": path}
        ) from exc
    if not isinstance(data, dict):
        raise ValidationError(
            "invalid_config", f"{path}: top level must be an object", {"path": path}
        )
    return data


def find_repo_root(cwd: str | os.PathLike[str]) -> Path:
    """The nearest ancestor of ``cwd`` holding a ``.git`` entry; ``cwd`` itself outside one.

    Read from the filesystem, without running git, so it also works where git is missing.
    """
    start = Path(cwd).resolve()
    for directory in (start, *start.parents):
        if (directory / GIT_MARKER).exists():
            return directory
    return start


def user_config_home() -> Path:
    """``$XDG_CONFIG_HOME/wev-skills``, or ``~/.config/wev-skills``."""
    configured = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(configured) if configured else Path.home() / ".config") / USER_CONFIG_DIR
