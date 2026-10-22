"""The ``mcp.rea`` entry wev writes into OpenCode's ``opencode.json``.

The key is wev's only when it is absent, or when its value is the same JSON as the one the
manifest recorded. Anything else is a person's entry: install refuses, uninstall leaves it.
Rewriting re-indents the file (2 spaces) but keeps every other key and value and the file mode.
A symlinked ``opencode.json``, or an ``opencode.jsonc`` with no ``opencode.json``, is refused.
Shortcut: ``opencode.jsonc`` is not edited; a file that is not plain JSON is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.core.fsutil import atomic_write_text

SERVER = "rea"


def dump(entry: dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        message = i18n.t("harness.error.opencode_config_invalid", path=str(path))
        raise ValidationError("harness_opencode_config_invalid", message) from exc
    if not isinstance(data, dict) or not isinstance(data.get("mcp", {}), dict):
        message = i18n.t("harness.error.opencode_config_invalid", path=str(path))
        raise ValidationError("harness_opencode_config_invalid", message)
    return data


def _write(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else None
    atomic_write_text(path, text)
    if mode is not None:
        path.chmod(mode)


def _save(path: Path, data: dict[str, Any]) -> None:
    _write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _refuse_symlink(path: Path) -> None:
    if path.is_symlink():
        message = i18n.t("harness.error.opencode_config_symlink", path=str(path))
        raise StateConflict("harness_opencode_config_symlink", message, {"path": str(path)})


def check(path: Path, recorded: str) -> None:
    """Refuse when ``mcp.rea`` exists and is not the entry the manifest recorded."""
    _refuse_symlink(path)
    jsonc = path.with_suffix(".jsonc")
    if not path.exists() and jsonc.exists():
        message = i18n.t("harness.error.opencode_config_invalid", path=str(jsonc))
        raise ValidationError("harness_opencode_config_invalid", message)
    existing = _load(path).get("mcp", {}).get(SERVER)
    if existing is not None and dump(existing) != recorded:
        message = i18n.t("harness.error.opencode_mcp_foreign", path=str(path), name=SERVER)
        raise StateConflict("harness_opencode_mcp_foreign", message, {"path": str(path)})


def apply(path: Path, entry: dict[str, Any]) -> None:
    data = _load(path)
    _save(path, {**data, "mcp": {**data.get("mcp", {}), SERVER: entry}})


def snapshot(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def restore(path: Path, text: str | None) -> None:
    if text is None:
        path.unlink(missing_ok=True)
    else:
        _write(path, text)


def remove(path: Path, recorded: str) -> None:
    """Drop ``mcp.rea`` when it is still the recorded entry; delete a file left empty."""
    if not recorded or not path.exists():
        return
    _refuse_symlink(path)
    data = _load(path)
    servers = dict(data.get("mcp", {}))
    if SERVER not in servers or dump(servers[SERVER]) != recorded:
        return
    del servers[SERVER]
    rest = {k: v for k, v in data.items() if k != "mcp"}
    result = {**rest, "mcp": servers} if servers else rest
    if result:
        _save(path, result)
    else:
        path.unlink()
