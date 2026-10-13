"""Harness configurations compared by the scripted evaluation, and their simulated constants."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.agents.spec import Permissions, Tools
from wev_skills.config import (
    AUTO,
    EXECUTOR_TIERS,
    TIER_NAMES,
    TOOL_PROFILES,
    LimitsConfig,
    deep_merge,
)
from wev_skills.context import ContextManager
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import ValidationError
from wev_skills.evaluation.tasks import read_json
from wev_skills.guards import GuardLimits

SIMULATED_PRICE_PER_TOKEN: dict[str, int] = {"economy": 1, "standard": 3, "premium": 15}
"""Simulated cost units charged per token in context per step, by tier. Not real prices."""
PLAN_TOKENS = 120
"""Simulated size of the plan excerpt pinned in each subtask context when a plan is made."""
PLAN_DURATION_UNITS = 1
"""Simulated duration of producing a plan."""
STEP_DURATION_UNITS = 1
"""Simulated duration of one scripted step."""
DEFAULT_SIMULATED_BUDGET = 5_000_000.0
"""Default guard budget, in simulated cost units, high enough not to bind on shipped tasks."""
STUB_SUMMARY_CHARS_PER_ITEM = 60

REFERENCE_TOOLS = Tools(allow=("Read", "Grep", "Glob", "Edit", "Write", "Bash"))
REFERENCE_PERMISSIONS = Permissions(may_mutate=True)
"""The tool surface of a reference agent that edits files. The scripted agent calls no tool,
so a tool profile only decides which of these names a run lists; it changes no outcome."""

PLANNING_MODES = ("on", "off", "auto")
CONTEXT_POLICIES = ("none", "elide", "elide_and_summarize")
ROUTING_MODES = ("policy", "fixed")
SELECTION_OFF, SELECTION_LOCAL = "off", "local"
TOOL_SELECTION_MODES = (SELECTION_OFF, SELECTION_LOCAL)
"""The scripted harness runs offline, so the ``provider`` mode of the engine is not offered."""
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class StubSummarizer:
    """STUB, not a model: keeps the first characters of each text. It understands nothing."""

    def summarize(self, texts: Sequence[str]) -> str:
        head = f"[stub summary of {len(texts)} items, truncated] "
        return head + " | ".join(text[:STUB_SUMMARY_CHARS_PER_ITEM] for text in texts)


def _eval_guard_limits() -> GuardLimits:
    return GuardLimits(budget_units=DEFAULT_SIMULATED_BUDGET)


def _invalid(config_id: str, key: str, **params: object) -> ValidationError:
    message = i18n.t(key, id=config_id, **params)
    return ValidationError("invalid_eval_config", message, {"id": config_id})


@dataclass(frozen=True)
class HarnessConfig(Serializable):
    id: str
    description: str = ""
    planning: str = "on"
    context_policy: str = "elide"
    elide_at: float = 0.6
    summarize_at: float = 0.85
    min_elide_tokens: int = 200
    keep_recent: int = 3
    max_attempts: int = 3
    max_parallel: int = 1
    routing: str = "policy"
    fixed_tier: str = ""
    guard_enabled: bool = True
    guard: GuardLimits = field(default_factory=_eval_guard_limits)
    executor_tier: str = AUTO
    tool_profile: str = "structured"
    tool_selection: str = SELECTION_OFF

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.id):
            raise _invalid(self.id, "evaluation.config.bad_id")
        choices = (
            ("planning", self.planning, PLANNING_MODES),
            ("context_policy", self.context_policy, CONTEXT_POLICIES),
            ("routing", self.routing, ROUTING_MODES),
            ("executor_tier", self.executor_tier, EXECUTOR_TIERS),
            ("tool_profile", self.tool_profile, TOOL_PROFILES),
            ("tool_selection", self.tool_selection, TOOL_SELECTION_MODES),
        )
        for name, value, allowed in choices:
            if value not in allowed:
                raise _invalid(
                    self.id,
                    "evaluation.config.bad_choice",
                    field=name,
                    value=value,
                    allowed=", ".join(allowed),
                )
        if not 0 < self.elide_at < self.summarize_at <= 1:
            raise _invalid(self.id, "evaluation.config.bad_thresholds")
        counts = (self.max_attempts, self.max_parallel)
        if min(counts) < 1 or min(self.min_elide_tokens, self.keep_recent) < 0:
            raise _invalid(self.id, "evaluation.config.bad_counts")
        fixed = self.routing == "fixed"
        if fixed != (self.fixed_tier in TIER_NAMES) or (not fixed and self.fixed_tier):
            raise _invalid(self.id, "evaluation.config.bad_tier", tiers=", ".join(TIER_NAMES))

    def guard_limits(self) -> GuardLimits:
        """Guard limits with the attempt limit tied to ``max_attempts``.

        ``guard_enabled`` is honoured by the agent, which does not consult a disabled guard.
        """
        return replace(self.guard, max_attempts=self.max_attempts)

    def limits(self) -> LimitsConfig:
        return LimitsConfig(max_attempts=self.max_attempts, max_parallel=self.max_parallel)

    def tier_bounds(self) -> tuple[str, str] | None:
        return (self.fixed_tier, self.fixed_tier) if self.routing == "fixed" else None

    def new_context(self, window_tokens: int) -> ContextManager:
        """A real, empty ``ContextManager`` sized to the task window. Nothing is archived."""
        summarize = self.context_policy == "elide_and_summarize"
        return ContextManager(
            budget_tokens=window_tokens,
            elide_at=self.elide_at,
            summarize_at=self.summarize_at,
            summarizer=StubSummarizer() if summarize else None,
            min_elide_tokens=self.min_elide_tokens,
            keep_recent=self.keep_recent,
        )


def _defaults() -> dict[str, Any]:
    data = HarnessConfig(id="defaults").to_dict()
    return {key: value for key, value in data.items() if key != "id"}


def parse_configs(data: Any, source: str = "<memory>") -> tuple[HarnessConfig, ...]:
    """Build configs from ``{"defaults": {...}, "configs": [{...}]}``; ids must be unique."""
    entries = data.get("configs") if isinstance(data, dict) else None
    shared = data.get("defaults", {}) if isinstance(data, dict) else None
    extra = sorted(set(data) - {"defaults", "configs"}) if isinstance(data, dict) else []
    if not isinstance(entries, list) or not entries or not isinstance(shared, dict) or extra:
        raise ValidationError(
            "invalid_eval_configs",
            i18n.t("evaluation.error.configs_shape", source=source),
            {"path": source},
        )
    base = deep_merge(_defaults(), shared)
    configs: list[HarnessConfig] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValidationError(
                "invalid_eval_configs",
                i18n.t("evaluation.error.configs_shape", source=source),
                {"path": f"/configs/{index}"},
            )
        configs.append(HarnessConfig.from_dict(deep_merge(base, entry), _path=f"/configs/{index}"))
    ids = [config.id for config in configs]
    dups = sorted({item for item in ids if ids.count(item) > 1})
    if dups:
        raise ValidationError(
            "duplicate_eval_config",
            i18n.t("evaluation.task.duplicate", what="config", ids=", ".join(dups)),
            {"ids": dups},
        )
    return tuple(configs)


def load_configs(path: str | Path) -> tuple[HarnessConfig, ...]:
    file = Path(path)
    return parse_configs(read_json(file), source=str(file))
