"""Shared by the ``run``, ``plan``, ``task``, ``exec``, ``guard`` and ``state`` commands.

Where a command looks: the repository root (the nearest ``.git`` ancestor, else the working
directory), unless an ancestor already holds an active run, which then wins. A relative
``state_dir`` is taken from that root, never from the directory the command runs in.

Which configuration it uses: for a new run, ``--config`` when given, else
``<root>/wev.config.json`` when it exists, else defaults. For an existing run, the snapshot
the run pinned when it started; a ``--config`` that differs from it is refused.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.config import Config, ResolvedConfig, find_repo_root, resolve_config
from wev_skills.core import active, wiring
from wev_skills.core.engine import NEW_RUN_STEP
from wev_skills.core.errors import NotFound, StateConflict, ValidationError
from wev_skills.core.orchestrator import Orchestrator
from wev_skills.state.model import Phase, RunState
from wev_skills.state.store import StateStore, active_run, new_run_id, run_dir


@dataclass(frozen=True)
class Location:
    """Where a command operates and the configuration resolved for it (not yet pinned)."""

    root: Path
    resolved: ResolvedConfig
    state_dir: Path


def project_root(cwd: Path) -> Path:
    """The root of the active run that governs ``cwd``, else the repository root."""
    found = active.find_active_run(cwd)
    return found.root if found is not None else find_repo_root(cwd)


def locate(args: argparse.Namespace) -> Location:
    root = project_root(Path.cwd())
    resolved = resolve_config(args.config, root)
    return Location(root, resolved, wiring.state_dir(resolved.config, root))


def config_for(args: argparse.Namespace) -> Config:
    """The configuration of a command that works without a run."""
    return locate(args).resolved.config


def add_run_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run", default=None, help=i18n.t("orch.arg.run"))


def resolve_run_id(args: argparse.Namespace, location: Location) -> str:
    """``--run``, or the active run; with neither, a ``NotFound`` naming ``wev run start``."""
    run_id: str | None = args.run if args.run is not None else active_run(location.state_dir)
    if run_id is None:
        message = i18n.t("orch.error.no_active_run", state_dir=str(location.state_dir))
        raise NotFound("no_active_run", message, {"next_step": NEW_RUN_STEP})
    return run_id


def _pinned(args: argparse.Namespace, location: Location, state: RunState) -> tuple[Config, str]:
    """The run's own configuration; a different one given on the command line is refused."""
    if not state.config:
        return location.resolved.config, location.resolved.source
    if args.config is not None and location.resolved.digest != state.config_digest:
        message = i18n.t("orch.error.config_pinned", run=state.run_id, source=state.config_source)
        details = {"pinned": state.config_digest, "given": location.resolved.digest}
        raise ValidationError("config_pinned", message, details)
    return active.pinned_config(state), state.config_source


def orchestrator_for(args: argparse.Namespace, reads: bool = False) -> Orchestrator:
    """The orchestrator of ``--run`` or of the active run, wired from its pinned configuration.

    Unless the command only ``reads``, a run that is not finished must be in the per-user
    registry (``active.require_registered``): its pinned configuration is the policy.
    """
    location = locate(args)
    run_id = resolve_run_id(args, location)
    state = StateStore(run_dir(location.state_dir, run_id)).load()
    if not reads and state.phase is not Phase.DONE:
        active.require_registered(location.state_dir, run_id)
    config, source = _pinned(args, location, state)
    services = wiring.build_services(config, location.root, source=source)
    timeout = config.limits.lock_timeout_seconds
    store = StateStore(run_dir(services.state_dir, run_id), services.clock, timeout)
    return Orchestrator(store, services)


active_orchestrator = orchestrator_for
"""Kept under its older name: every command now defaults to the active run."""


def new_orchestrator(args: argparse.Namespace, run_id: str | None) -> tuple[Orchestrator, str]:
    """An orchestrator for a run about to start; refused while another run is active here."""
    cwd = Path.cwd()
    existing = active.find_active_run(cwd)
    if existing is not None:
        step = f"wev run finish --run {existing.run_id}"
        message = i18n.t("orch.error.run_active", run=existing.run_id)
        details = {"run_id": existing.run_id, "root": str(existing.root), "next_step": step}
        raise StateConflict("run_active", message, details)
    root = find_repo_root(cwd)
    resolved = resolve_config(args.config, root)
    services = wiring.build_services(resolved.config, root, source=resolved.source)
    chosen = run_id if run_id is not None else new_run_id(services.clock)
    timeout = resolved.config.limits.lock_timeout_seconds
    store = StateStore(run_dir(services.state_dir, chosen), services.clock, timeout)
    return Orchestrator(store, services), chosen


def remainder(tokens: list[str]) -> list[str]:
    """The command after an optional leading ``--`` separator."""
    return tokens[1:] if tokens[:1] == ["--"] else list(tokens)
