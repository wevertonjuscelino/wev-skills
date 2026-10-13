"""Decision providers: the vendor-neutral interface and its implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from wev_skills.core.contracts import (
    AttemptRecord,
    Classification,
    EscalationDecision,
    Mode,
    PlanTask,
    Strategy,
    TaskContract,
    TaskResult,
    TaskSignals,
    ToolSelection,
    Verdict,
)
from wev_skills.core.ports import AgentLike
from wev_skills.decisions.tool_selection import ToolAgent
from wev_skills.tools.registry import ToolSpec


class DecisionProvider(Protocol):
    """Seven decisions the orchestrator needs.

    A provider may raise risk and complexity above what the local policy computes from the
    signals and the objective text; it can never lower either, so it can never remove a
    review or an approval."""

    provider_id: str

    def classify_task(self, signals: TaskSignals) -> Classification: ...

    def select_strategy(
        self, classification: Classification, mode: Mode, executor_tier: str = "standard"
    ) -> Strategy: ...

    def route_agent(
        self, task: PlanTask, agents: Sequence[AgentLike], default_agent: str = ""
    ) -> str: ...

    def evaluate_result(self, contract: TaskContract, result: TaskResult) -> Verdict: ...

    def resolve_conflict(self, verdicts: Sequence[Verdict]) -> Verdict: ...

    def should_escalate(
        self, history: Sequence[AttemptRecord], max_attempts: int | None = None
    ) -> EscalationDecision: ...

    def select_tools(
        self, task: PlanTask, agent: ToolAgent, available: Sequence[ToolSpec], tier: str
    ) -> ToolSelection:
        """The smallest tool set ``agent`` needs for ``task``: always a subset of its allow
        list minus its deny list, with the floor kept (``decisions.tool_selection``)."""
        ...


__all__ = ["DecisionProvider"]
