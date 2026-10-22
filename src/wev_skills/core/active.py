"""Which run is active for a directory, for hooks and every other entry point.

``find_active_run`` only reads. It never creates a file and never raises: when a state
directory holds a run that cannot be read, the answer is a run with ``state_error`` set and
the most restrictive values (plan mode, high risk), so the caller can fail safe instead of
acting as if there were no run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.config import (
    CONFIG_FILE_NAME,
    Config,
    explicit_language,
    find_repo_root,
    parse_config,
    user_config_path,
)
from wev_skills.core import run_registry
from wev_skills.core.contracts import Mode, RiskLevel, TaskStatus, higher_risk
from wev_skills.core.errors import StateConflict, WevError
from wev_skills.core.run_registry import RegistryEntry
from wev_skills.security.paths import place_within, same_place
from wev_skills.state.model import Phase, RunState
from wev_skills.state.store import StateStore, active_run, run_dir, runs_by_recency, runs_dir

UNREADABLE = "state_unreadable"
UNREGISTERED = "unregistered_run"
REGISTRY_UNREADABLE = "registry_unreadable"
UNTRUSTED = (UNREGISTERED, REGISTRY_UNREADABLE)
ADOPT_STEP = "wev run adopt --run {run}"


@dataclass(frozen=True)
class ActiveRun:
    """The active run of a repository. ``phase`` is ``None`` when the state is unreadable."""

    root: Path
    state_dir: Path
    run_id: str
    mode: Mode
    risk: RiskLevel
    config: Config
    phase: Phase | None
    state_error: str | None = None
    language: str | None = None
    """The ``language`` the run's configuration set explicitly, if it did."""


def pinned_config(state: RunState) -> Config:
    """The configuration the run was started with (defaults for a state without a snapshot)."""
    return Config.from_dict(dict(state.config)) if state.config else Config()


def run_risk(state: RunState) -> RiskLevel:
    """The highest risk among the run classification and every RUNNING task."""
    base = state.classification.risk if state.classification else RiskLevel.LOW
    tasks = state.plan.tasks if state.plan else ()
    running = (
        task.risk
        for task in tasks
        if task.id in state.tasks and state.tasks[task.id].status is TaskStatus.RUNNING
    )
    return higher_risk(base, *running)


def _resolved(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError, RuntimeError:
        return Path(path).absolute()


def _restricted(root: Path, state_dir: Path, run_id: str, error: str) -> ActiveRun:
    return ActiveRun(root, state_dir, run_id, Mode.PLAN, RiskLevel.HIGH, Config(), None, error)


def _load(root: Path, state_dir: Path, run_id: str) -> ActiveRun:
    """One run as an ``ActiveRun``; an unreadable state gives the restricted form."""
    try:
        state = StateStore(run_dir(state_dir, run_id)).load()
        config = pinned_config(state)
    except WevError as exc:
        return _restricted(root, state_dir, run_id, exc.code)
    except Exception as exc:  # noqa: BLE001 - a lookup must fail safe, whatever the file holds
        return _restricted(root, state_dir, run_id, f"{UNREADABLE}: {type(exc).__name__}")
    language = state.config.get("language")
    return ActiveRun(
        root,
        state_dir,
        run_id,
        state.mode,
        run_risk(state),
        config,
        state.phase,
        language=language if isinstance(language, str) else None,
    )


def inspect_state_dir(root: Path, state_dir: Path) -> ActiveRun | None:
    """The active run under ``state_dir``: the latest readable run that is not finished,
    else the latest unreadable one (restricted), else ``None``."""
    try:
        names = runs_by_recency(state_dir)
    except OSError:
        return None
    unreadable: ActiveRun | None = None
    for name in names:
        found = _load(root, state_dir, name)
        if found.state_error is not None:
            unreadable = unreadable or found
        elif found.phase is not Phase.DONE:
            return found
    return unreadable


def _configured_state_dir(directory: Path) -> str | None:
    candidate = directory / CONFIG_FILE_NAME
    try:
        return parse_config(str(candidate)).state_dir if candidate.is_file() else None
    except WevError, OSError:
        return None


def _candidates(directory: Path, entries: Sequence[RegistryEntry]) -> tuple[Path, ...]:
    """State directories ``directory`` may hold: the default, its config file's, registered."""
    found = [directory / name for name in _tree_names(directory)]
    found += [Path(entry.state_dir) for entry in entries if _same(Path(entry.root), directory)]
    unique = dict.fromkeys(_resolved(path) for path in found)
    return tuple(path for path in unique if _is_dir(runs_dir(path)))


def _tree_names(directory: Path) -> tuple[str, ...]:
    """The state directory names found in the tree: the default and its config file's."""
    names = (Config().state_dir, _configured_state_dir(directory))
    return tuple(name for name in names if name)


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _in_directory(directory: Path, entries: Sequence[RegistryEntry]) -> ActiveRun | None:
    for state_dir in _candidates(directory, entries):
        found = inspect_state_dir(directory, state_dir)
        if found is not None:
            return found
    return None


def _same(left: Path, right: Path) -> bool:
    return same_place(str(left), str(right))


def _contains(root: Path, path: Path) -> bool:
    return place_within(str(path), str(root))


def _through_registry(
    start: Path,
    paths: Sequence[Path],
    targets: Sequence[Path],
    entries: Sequence[RegistryEntry],
    look: Callable[[RegistryEntry], ActiveRun | None],
) -> ActiveRun | None:
    """The run of an entry whose root contains ``start`` or a path, or lies in a target."""
    inside = (start, *(_resolved(Path(path)) for path in paths))
    around = tuple(_resolved(Path(path)) for path in targets)
    for entry in entries:
        root = _resolved(Path(entry.root))
        hit = any(_contains(root, path) for path in inside)
        if hit or any(_contains(path, root) for path in around):
            found = look(entry)
            if found is not None:
                return found
    return None


def _inspect_entry(entry: RegistryEntry) -> ActiveRun | None:
    return inspect_state_dir(_resolved(Path(entry.root)), _resolved(Path(entry.state_dir)))


def find_active_run(
    cwd: Path, paths: Sequence[Path] = (), targets: Sequence[Path] = ()
) -> ActiveRun | None:
    """The active run that governs ``cwd`` or any of ``paths``; ``None`` when there is none.

    Every ancestor of ``cwd`` is checked and the outermost one with an active run wins, so
    a nested ``git init`` cannot hide the run of the repository around it. Failing that, the
    per-user registry is consulted for a run whose root contains ``cwd`` or one of ``paths``,
    or whose root lies inside one of ``targets`` (a command aimed at a parent directory).
    This is the engine commands' lookup; the hooks use ``find_hook_run``.
    """
    start = _resolved(Path(cwd))
    entries = run_registry.read_entries()
    outermost: ActiveRun | None = None
    for directory in (start, *start.parents):
        outermost = _in_directory(directory, entries) or outermost
    if outermost is not None:
        return outermost
    return _through_registry(start, paths, targets, entries, _inspect_entry)


def _registered(entry: RegistryEntry) -> ActiveRun | None:
    """The run an entry vouches for; an active run under another id is ``UNREGISTERED``."""
    root, state_dir = _resolved(Path(entry.root)), _resolved(Path(entry.state_dir))
    found = inspect_state_dir(root, state_dir) if _is_dir(runs_dir(state_dir)) else None
    if found is None or found.run_id == entry.run_id:
        return found
    return _restricted(root, state_dir, found.run_id, UNREGISTERED)


def _has_open_run(state_dir: Path) -> bool:
    """Whether ``state_dir`` holds a run whose recorded phase is not ``done``. Only the phase
    is read; a state that cannot be read counts as open."""
    try:
        return active_run(state_dir) is not None
    except WevError, OSError:
        return True


def _trusted_in(directory: Path, entries: Sequence[RegistryEntry]) -> ActiveRun | None:
    """The registered run of ``directory``, else ``UNREGISTERED`` when its tree holds an
    open run the registry does not list, else ``None``."""
    mine = [entry for entry in entries if _same(Path(entry.root), directory)]
    for entry in mine:
        found = _registered(entry)
        if found is not None:
            return found
    claimed = [_resolved(Path(entry.state_dir)) for entry in mine]
    for name in _tree_names(directory):
        state_dir = _resolved(directory / name)
        unclaimed = not any(_same(state_dir, place) for place in claimed)
        if unclaimed and _is_dir(runs_dir(state_dir)) and _has_open_run(state_dir):
            return _restricted(directory, state_dir, "", UNREGISTERED)
    return None


def find_hook_run(
    cwd: Path, paths: Sequence[Path] = (), targets: Sequence[Path] = ()
) -> ActiveRun | None:
    """``find_active_run`` for the Claude Code hooks, trusting only the per-user registry.

    A run counts only when the registry lists it by root, state directory and run id. An
    open run in the tree that the registry does not list (a ``.wev/`` shipped inside a
    repository, a lost registry) gives a restricted run with ``state_error`` set to
    ``UNREGISTERED``; its state is read only for its phase. A registry that exists but
    cannot be read gives ``REGISTRY_UNREADABLE``. The tree's ``wev.config.json`` is read
    only to find state directories to report, never for a policy. Paths are compared with
    the registry's roots without case only where the file system confirms the same place
    (``paths.same_place``).
    """
    start = _resolved(Path(cwd))
    entries = run_registry.read_registry()
    if entries is None:
        return _restricted(start, start, "", REGISTRY_UNREADABLE)
    outermost: ActiveRun | None = None
    for directory in (start, *start.parents):
        outermost = _trusted_in(directory, entries) or outermost
    if outermost is not None:
        return outermost
    return _through_registry(start, paths, targets, entries, _registered)


def is_registered(state_dir: Path, run_id: str) -> bool:
    """Whether the per-user registry lists ``run_id`` under ``state_dir``. A registry that
    cannot be read lists nothing."""
    entries = run_registry.read_registry()
    target = _resolved(Path(state_dir))
    return entries is not None and any(
        entry.run_id == run_id and _same(_resolved(Path(entry.state_dir)), target)
        for entry in entries
    )


def require_registered(state_dir: Path, run_id: str) -> None:
    """Refuse (``UNREGISTERED``, exit 5) a run the registry does not list: its pinned
    configuration came from the tree, not from a ``run start`` of this user. The details
    name ``wev run adopt``, the human-operator command that registers it."""
    if is_registered(state_dir, run_id):
        return
    message = i18n.t("orch.error.unregistered_run", run=run_id, state_dir=str(state_dir))
    details = {
        "run_id": run_id,
        "state_dir": str(state_dir),
        "next_step": ADOPT_STEP.format(run=run_id),
    }
    raise StateConflict(UNREGISTERED, message, details)


def registered_run() -> ActiveRun | None:
    """Any run the per-user registry lists that is still active (the first one found)."""
    for entry in run_registry.read_entries():
        found = _registered(entry)
        if found is not None:
            return found
    return None


def ambient_language(cwd: Path, config_path: str | None = None) -> str | None:
    """The language a command run from ``cwd`` takes from its configuration, if one is set.

    The active run's pinned configuration when there is one, else ``config_path`` (the
    global ``--config``), else ``<repository root>/wev.config.json``, else the user file
    (``user_config_path()``, skipped when a symlink). Only a ``language`` written in a file
    counts; the built-in default does not. A lookup that fails gives
    ``None``: the command itself reports the real error.
    """
    found = find_active_run(cwd)
    if found is not None:
        return found.language
    if config_path is not None:
        return explicit_language(config_path)
    repo = explicit_language(str(find_repo_root(cwd) / CONFIG_FILE_NAME))
    user = user_config_path()
    return repo or (None if user.is_symlink() else explicit_language(str(user)))


def _still_active(entry: RegistryEntry) -> bool:
    return inspect_state_dir(Path(entry.root), Path(entry.state_dir)) is not None


def register_run(root: Path, state_dir: Path, run_id: str) -> None:
    """Record ``root`` as holding an active run; entries that are no longer active go."""
    entry = RegistryEntry(str(_resolved(root)), str(_resolved(state_dir)), run_id)
    same_place = (entry.root, entry.state_dir)
    run_registry.update(
        lambda old: (old.root, old.state_dir) != same_place and _still_active(old), entry
    )


def unregister_run(state_dir: Path, run_id: str) -> None:
    """Drop the entry of a finished run (and every other entry that is no longer active)."""
    target = str(_resolved(state_dir))
    run_registry.update(
        lambda old: (old.state_dir, old.run_id) != (target, run_id) and _still_active(old)
    )
