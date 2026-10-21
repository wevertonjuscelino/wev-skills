"""Per-user registry of repositories that have an active run.

A hook may be asked about a file outside the directory it runs in. The registry lets it find
the run that owns that file. It is a small JSON file under the user's state home, written
atomically at ``run start`` and ``run finish``. Reading never creates anything and never
raises: for most readers an unreadable registry is an empty one, while the hooks tell the
two apart (``read_registry``). Entries are hints, not facts; a reader checks the run state
itself, and stale entries are dropped on the next write.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from wev_skills.core import fsutil
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import WevError

STATE_HOME_VARIABLE = "XDG_STATE_HOME"
DEFAULT_STATE_HOME = (".local", "state")
REGISTRY_DIR = "wev-skills"
REGISTRY_FILE = "active-runs.json"
REGISTRY_VERSION = 1
MAX_ENTRIES = 500


@dataclass(frozen=True)
class RegistryEntry(Serializable):
    root: str
    state_dir: str
    run_id: str


def registry_path(environ: Mapping[str, str] | None = None) -> Path:
    """``$XDG_STATE_HOME/wev-skills/active-runs.json``, or under ``~/.local/state``."""
    env = os.environ if environ is None else environ
    configured = env.get(STATE_HOME_VARIABLE, "").strip()
    home = Path(configured) if configured else Path.home().joinpath(*DEFAULT_STATE_HOME)
    return home / REGISTRY_DIR / REGISTRY_FILE


def read_entries(path: Path | None = None) -> tuple[RegistryEntry, ...]:
    """Every well-formed entry; an absent, unreadable or malformed registry is empty."""
    return read_registry(path) or ()


def read_registry(path: Path | None = None) -> tuple[RegistryEntry, ...] | None:
    """Every well-formed entry: ``()`` when the file is absent, ``None`` when it exists but
    cannot be read or does not have the registry's shape. Malformed entries are skipped."""
    target = path if path is not None else registry_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except OSError, ValueError:
        return None
    items = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    found: list[RegistryEntry] = []
    for item in items[:MAX_ENTRIES]:
        try:
            found.append(RegistryEntry.from_dict(item))
        except WevError:
            continue
    return tuple(found)


def _write(target: Path, entries: tuple[RegistryEntry, ...]) -> None:
    document = {"version": REGISTRY_VERSION, "runs": [entry.to_dict() for entry in entries]}
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
    fsutil.atomic_write_text(target, text + "\n")


def update(
    keep: Callable[[RegistryEntry], bool],
    add: RegistryEntry | None = None,
    path: Path | None = None,
) -> tuple[RegistryEntry, ...]:
    """Rewrite the registry under a lock: entries ``keep`` accepts, then ``add`` (once)."""
    target = path if path is not None else registry_path()
    with fsutil.locked(target):
        kept = tuple(entry for entry in read_entries(target) if entry != add and keep(entry))
        entries = (*kept, add) if add is not None else kept
        _write(target, entries)
    return entries
