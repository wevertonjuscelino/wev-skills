"""Whole-run limits use raw engine records, including history before a guard reset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wev_skills.core.engine import Engine

from wev_skills import i18n
from wev_skills.config import LimitsConfig
from wev_skills.core.contracts import GuardAction
from wev_skills.core.errors import GuardTripped
from wev_skills.guards.events import GuardEventKind
from wev_skills.guards.execution import GuardVerdict
from wev_skills.state.model import RunState

WARNING_FRACTION = 0.8


@dataclass(frozen=True)
class Usage:
    units: float
    attempts: int


def usage(state: RunState) -> Usage:
    units = sum(
        float(item.get("units", 0))
        for item in state.guard_events
        if item.get("kind") == GuardEventKind.BUDGET.value
    )
    units += sum(1 for command in state.commands if command.baseline)
    attempts = sum(
        1
        for item in state.guard_events
        if item.get("kind") == GuardEventKind.AGENT_HANDOFF.value
        and item.get("from_agent") == "orchestrator"
    )
    return Usage(units, attempts)


def payload(state: RunState, limits: LimitsConfig) -> dict[str, Any]:
    spent = usage(state)
    fraction = max(
        spent.units / limits.run_budget_units, spent.attempts / limits.run_max_attempts_total
    )
    return {
        "units": spent.units,
        "limit_units": limits.run_budget_units,
        "attempts": spent.attempts,
        "limit_attempts": limits.run_max_attempts_total,
        "warning": fraction >= WARNING_FRACTION,
        "exhausted": spent.units >= limits.run_budget_units
        or spent.attempts > limits.run_max_attempts_total,
        "notice": i18n.t("orch.budget.warning") if fraction >= WARNING_FRACTION else "",
    }


def verdict(state: RunState, limits: LimitsConfig) -> GuardVerdict:
    data = payload(state, limits)
    if data["exhausted"]:
        return GuardVerdict(GuardAction.STOP, "run_budget", (i18n.t("orch.budget.stop"),), data)
    return GuardVerdict(GuardAction.CONTINUE, "none", (), data)


def require(engine: Engine, state: RunState, units: float = 0, attempts: int = 0) -> None:
    """Reject a batch before executing it if its maximum cost exceeds the remaining budget."""
    limits, spent = engine.services.config.limits, usage(state)
    exceeds = (
        spent.units + units > limits.run_budget_units
        or spent.attempts + attempts > limits.run_max_attempts_total
    )
    if spent.units >= limits.run_budget_units or exceeds:
        raise GuardTripped("run_budget", i18n.t("orch.budget.stop"), payload(state, limits))
