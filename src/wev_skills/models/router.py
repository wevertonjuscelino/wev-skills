"""Tier-based model selection with escalation on failure and fallback on unavailability."""

from __future__ import annotations

from collections.abc import Iterable

from wev_skills import i18n
from wev_skills.config import TIER_NAMES, ModelsConfig
from wev_skills.core.contracts import Classification, Complexity, ModelChoice, RiskLevel
from wev_skills.core.errors import ProviderError, ValidationError

FREE_ATTEMPTS = 1
"""Attempts that do not raise the tier: only failures beyond the first escalate."""


def _tier_index(name: str) -> int:
    if name not in TIER_NAMES:
        raise ValidationError(
            "unknown_tier",
            i18n.t("models.error.unknown_tier", tier=name),
            {"tier": name, "tiers": list(TIER_NAMES)},
        )
    return TIER_NAMES.index(name)


def executor_tier(configured: str, routed: ModelChoice) -> str:
    """The tier strategy selection assumes for whoever executes the task.

    ``harness.executor_tier`` names it outright; ``auto`` means the tier the router picked.
    A routed tier that is not a tier name (a pinned model outside the tiers) counts as standard.
    """
    if configured in TIER_NAMES:
        return configured
    return routed.tier if routed.tier in TIER_NAMES else TIER_NAMES[1]


def base_tier(classification: Classification) -> tuple[int, str]:
    """Index of the starting tier and the reason for it."""
    if classification.risk is RiskLevel.HIGH:
        return 2, i18n.t("models.base.high_risk")
    if classification.complexity is Complexity.COMPLEX:
        return 2, i18n.t("models.base.complex")
    if classification.risk is RiskLevel.LOW and classification.complexity is Complexity.TRIVIAL:
        return 0, i18n.t("models.base.economy")
    return 1, i18n.t("models.base.standard")


class ModelRouter:
    def __init__(self, models_config: ModelsConfig) -> None:
        self._config = models_config

    def _bounds(self, bounds: tuple[str, str] | None) -> tuple[int, int]:
        if bounds is None:
            return 0, len(TIER_NAMES) - 1
        low, high = _tier_index(bounds[0]), _tier_index(bounds[1])
        if low > high:
            raise ValidationError(
                "invalid_tier_bounds", i18n.t("models.error.bounds", low=bounds[0], high=bounds[1])
            )
        return low, high

    def _pinned(self, model: str, unavailable: frozenset[str]) -> ModelChoice | None:
        if model in unavailable:
            return None
        tier = next((n for n in TIER_NAMES if model in self._config.tier(n)), "pinned")
        return ModelChoice(model, tier, (i18n.t("models.pinned", model=model),))

    def _search_order(self, target: int, low: int, high: int) -> list[int]:
        up = list(range(target + 1, high + 1))
        down = list(range(target - 1, low - 1, -1))
        return [target, *up, *down]

    def select(
        self,
        classification: Classification,
        agent_model: str | None = None,
        agent_tier_bounds: tuple[str, str] | None = None,
        attempt: int = 0,
        unavailable: Iterable[str] = (),
    ) -> ModelChoice:
        blocked = frozenset(unavailable)
        reasons: list[str] = []
        if agent_model:
            pinned = self._pinned(agent_model, blocked)
            if pinned is not None:
                return pinned
            reasons.append(i18n.t("models.pinned_unavailable", model=agent_model))
        low, high = self._bounds(agent_tier_bounds)
        target, reasons = self._target_tier(classification, attempt, low, high, reasons)
        return self._pick(target, low, high, blocked, reasons)

    def _target_tier(
        self, classification: Classification, attempt: int, low: int, high: int, reasons: list[str]
    ) -> tuple[int, list[str]]:
        notes = list(reasons)
        index, why = base_tier(classification)
        notes.append(why)
        bump = max(0, attempt - FREE_ATTEMPTS)
        if bump:
            index = min(len(TIER_NAMES) - 1, index + bump)
            notes.append(i18n.t("models.escalated", attempt=attempt, tier=TIER_NAMES[index]))
        clamped = min(max(index, low), high)
        if clamped != index:
            notes.append(i18n.t("models.clamped", tier=TIER_NAMES[clamped]))
        return clamped, notes

    def _pick(
        self, target: int, low: int, high: int, blocked: frozenset[str], reasons: list[str]
    ) -> ModelChoice:
        notes = list(reasons)
        for index in self._search_order(target, low, high):
            name = TIER_NAMES[index]
            model = next((m for m in self._config.tier(name) if m not in blocked), None)
            if model is not None:
                if index != target:
                    notes.append(i18n.t("models.fallback", tier=name))
                notes.append(i18n.t("models.chosen", model=model, tier=name))
                return ModelChoice(model, name, tuple(notes))
            notes.append(i18n.t("models.tier_unavailable", tier=name))
        raise ProviderError(
            "no_model_available",
            i18n.t("models.error.none_available"),
            {"reasons": notes},
        )
