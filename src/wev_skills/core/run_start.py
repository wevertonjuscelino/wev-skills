"""REQUEST to DECIDE: create the run, pin its configuration, discover, classify, decide."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from wev_skills import i18n
from wev_skills.config import pinned_snapshot
from wev_skills.core import active, fsutil, planning, steps
from wev_skills.core.contracts import Classification, Mode, Strategy, TaskSignals
from wev_skills.core.discovery import CheckSuggestion, discover_checks
from wev_skills.core.engine import Change, Engine
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.models.router import executor_tier
from wev_skills.state.model import (
    Phase,
    RepoSnapshot,
    RunState,
    validate_run_id,
    with_classification,
    with_decision,
    with_discovery,
    with_phase,
    with_repo,
    with_strategy,
)
from wev_skills.state.store import active_run

START_MODES = (Mode.AUTO, Mode.PLAN, Mode.EXECUTE)
RUNS_LOCK = "runs"


@dataclass(frozen=True)
class _Opening:
    """Everything decided before the run exists."""

    objective: str
    mode: Mode
    repo: RepoSnapshot | None
    checks: tuple[CheckSuggestion, ...]
    classification: Classification
    strategy: Strategy


def strategy_for(engine: Engine, classification: Classification, mode: Mode) -> Strategy:
    """The strategy for the tier that will execute: configured, or the one the router picks."""
    services = engine.services
    routed = services.router.select(classification)
    tier = executor_tier(services.config.harness.executor_tier, routed)
    return services.provider.select_strategy(classification, mode, tier)


def _open(engine: Engine, objective: str, mode: Mode, signals: TaskSignals) -> _Opening:
    if mode not in START_MODES:
        raise ValidationError("invalid_mode", i18n.t("orch.error.start_mode", mode=mode.value))
    text = engine.clean(objective)
    repo = engine.snapshot(str(engine.services.root))
    checks = discover_checks(repo.root if repo is not None else engine.services.root)
    classification = engine.services.provider.classify_task(replace(signals, objective=text))
    strategy = strategy_for(engine, classification, mode)
    return _Opening(text, mode, repo, checks, classification, strategy)


def refuse_second_run(engine: Engine) -> None:
    """One active run per repository: a second one would make "the active run" ambiguous."""
    current = active_run(engine.services.state_dir)
    if current is None:
        return
    step = f"wev run finish --run {current}"
    message = i18n.t("orch.error.run_active", run=current)
    raise StateConflict("run_active", message, {"run_id": current, "next_step": step})


def _create(engine: Engine, opening: _Opening, run_id: str | None) -> None:
    """Register the run, then create its state with the configuration pinned; refused
    while another run is active. The registry is written first, so a run the hooks
    cannot see is never created."""
    services = engine.services
    fsutil.ensure_ignored_dir(services.state_dir)
    pinned = services.pinned
    chosen = validate_run_id(run_id if run_id is not None else engine.store.run_dir.name)
    with fsutil.locked(services.state_dir / RUNS_LOCK, services.config.limits.lock_timeout_seconds):
        refuse_second_run(engine)
        register(engine, chosen)
        engine.store.create(
            opening.objective,
            opening.mode,
            chosen,
            pinned_snapshot(pinned),
            pinned.digest,
            pinned.source,
        )


def _decisions(engine: Engine, opening: _Opening) -> Change:
    classification, strategy = opening.classification, opening.strategy
    checks = opening.checks
    found = [f"{c.command} ({c.source})" for c in checks] or [i18n.t("orch.discovery.none")]
    planned = strategy.needs_plan or opening.mode is Mode.PLAN
    pinned = engine.services.pinned
    classified = i18n.t(
        "orch.decision.classified",
        risk=classification.risk.value,
        complexity=classification.complexity.value,
    )

    def change(state: RunState) -> RunState:
        current = with_discovery(
            with_repo(state, opening.repo),
            planning.DISCOVERY_CHECKS_KEY,
            [c.to_dict() for c in checks],
        )
        current = with_strategy(with_classification(current, classification), strategy)
        records = (
            engine.decision(
                Phase.REQUEST,
                i18n.t("orch.decision.config", source=pinned.source),
                (pinned.digest,),
            ),
            engine.decision(Phase.DISCOVER, i18n.t("orch.decision.discovery"), found),
            engine.decision(
                Phase.CLASSIFY, classified, classification.reasons, classification.source
            ),
            engine.decision(
                Phase.DECIDE,
                i18n.t("orch.decision.strategy", flow=strategy.flow.value),
                strategy.reasons,
                engine.services.provider.provider_id,
            ),
        )
        for record in records:
            current = with_decision(current, record)
        return with_phase(current, Phase.PLAN if planned else Phase.EXECUTE)

    return change


def register(engine: Engine, run_id: str) -> None:
    """Add the run to the per-user registry; a registry that cannot be written stops the
    start (``registry_unwritable``), since the hooks would not trust the run."""
    services = engine.services
    try:
        active.register_run(services.root, services.state_dir, run_id)
    except (OSError, StateConflict) as exc:
        why = exc.code if isinstance(exc, StateConflict) else type(exc).__name__
        services.audit.append("registry.unavailable", {"run_id": run_id, "why": why})
        message = i18n.t("orch.error.registry_unwritable", error=why)
        raise StateConflict("registry_unwritable", message, {"run_id": run_id}) from exc


def start(
    engine: Engine, objective: str, mode: Mode, signals: TaskSignals, run_id: str | None
) -> dict[str, Any]:
    """Create the run, snapshot, discover, classify, pick a strategy and pin the config."""
    opening = _open(engine, objective, mode, signals)
    _create(engine, opening, run_id)
    data = {"mode": mode.value, "objective": opening.objective}
    state = engine.commit(_decisions(engine, opening), "run.started", data)
    payload = {
        "run_id": state.run_id,
        "mode": state.mode.value,
        "classification": opening.classification.to_dict(),
        "strategy": opening.strategy.to_dict(),
        "discovery": {"checks": [c.to_dict() for c in opening.checks]},
        "config": {"source": state.config_source, "digest": state.config_digest},
        **engine.step_fields(state),
    }
    if steps.needs_checks(state):
        payload["hint"] = i18n.t("orch.hint.supply_checks")
    return payload
