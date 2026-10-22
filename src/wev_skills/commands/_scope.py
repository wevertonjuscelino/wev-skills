"""Where a command that is not bound to a run operates, and which configuration it obeys.

``check-command``, ``classify``, ``agent ...``, ``approval ...`` and ``remote ...`` work with
or without a run. With an active run for the working directory, the run's pinned
configuration and state directory win and a different ``--config`` is refused, so the caller
cannot swap the policy by naming another file. Without one: ``--config`` when given, else
``<repository root>/wev.config.json``, else defaults. ``source`` says which, and every such
command prints it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.config import (
    Config,
    config_digest,
    find_repo_root,
    parse_config,
    protect_state_dir,
    resolve_config,
)
from wev_skills.core import wiring
from wev_skills.core.active import ActiveRun, find_active_run, require_registered
from wev_skills.core.errors import ValidationError

RUN_SOURCE_PREFIX = "run:"


@dataclass(frozen=True)
class Scope:
    """The root, configuration (state directory protected) and state directory of a command."""

    root: Path
    config: Config
    source: str
    state_dir: Path
    active: ActiveRun | None = None
    sources: tuple[str, ...] = ()
    """The configuration files merged, lowest precedence first; empty for a pinned run."""


def _refuse_other_config(config_path: str, active: ActiveRun) -> None:
    """A ``--config`` equal to the pinned one is harmless; anything else is refused."""
    same = active.state_error is None and config_digest(parse_config(config_path)) == (
        config_digest(active.config)
    )
    if same:
        return
    source = f"{RUN_SOURCE_PREFIX}{active.run_id}"
    message = i18n.t("orch.error.config_pinned", run=active.run_id, source=source)
    raise ValidationError("config_pinned", message, {"run_id": active.run_id})


def resolve_scope(
    config_path: str | None,
    cwd: Path | None = None,
    paths: Sequence[Path] = (),
    reads: bool = False,
) -> Scope:
    """The scope of a command run from ``cwd`` (default: the working directory). Unless the
    command only ``reads``, an active run the per-user registry does not list is refused."""
    here = cwd if cwd is not None else Path.cwd()
    active = find_active_run(here, paths)
    if active is not None and active.state_error is None and not reads:
        require_registered(active.state_dir, active.run_id)
    if active is None:
        root = find_repo_root(here)
        resolved = resolve_config(config_path, root)
        config = protect_state_dir(resolved.config, root)
        return Scope(
            root, config, resolved.source, wiring.state_dir(config, root), sources=resolved.sources
        )
    if config_path is not None:
        _refuse_other_config(config_path, active)
    config = protect_state_dir(active.config, active.root)
    source = f"{RUN_SOURCE_PREFIX}{active.run_id}"
    return Scope(active.root, config, source, active.state_dir, active)
