"""Shared frozen contracts (architecture section 3) plus the types they reference."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from wev_skills.core._codec import Serializable
from wev_skills.core.errors import ValidationError


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


RISK_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
"""The one risk order of the engine; every comparison goes through the helpers below."""


def risk_rank(level: RiskLevel) -> int:
    return RISK_RANK[level]


def higher_risk(first: RiskLevel, *others: RiskLevel) -> RiskLevel:
    """The most severe of the given risk levels."""
    return max((first, *others), key=risk_rank)


class Complexity(StrEnum):
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class Mode(StrEnum):
    PLAN = "plan"
    EXECUTE = "execute"
    AUTO = "auto"
    RESUME = "resume"


class Flow(StrEnum):
    DIRECT = "direct"
    PLANNED = "planned"
    GATED = "gated"


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    VERIFIED = "verified"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    NOT_EXECUTED = "not_executed"


class RunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class GuardAction(StrEnum):
    CONTINUE = "continue"
    CHANGE_STRATEGY = "change_strategy"
    REDUCE_SCOPE = "reduce_scope"
    ESCALATE = "escalate"
    ASK_HUMAN = "ask_human"
    STOP = "stop"


class EvidenceLabel(StrEnum):
    TESTED = "tested"
    UNTESTED = "untested"
    MOCKED = "mocked"
    DOCUMENTED_ONLY = "documented_only"
    BLOCKED = "blocked"


class PermissionOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    NEEDS_APPROVAL = "needs_approval"


@dataclass(frozen=True)
class TaskSignals(Serializable):
    objective: str
    files_touched_estimate: int = 0
    touches_remote: bool = False
    touches_production: bool = False
    destructive: bool = False
    external_side_effects: bool = False
    has_tests: bool = True
    reversible: bool = True
    unknowns: int = 0
    independent_subtasks: int = 1
    touches_credentials: bool = False
    changes_data_schema: bool = False


@dataclass(frozen=True)
class Classification(Serializable):
    complexity: Complexity
    risk: RiskLevel
    uncertainty: float
    parallelizable: bool
    reasons: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.uncertainty <= 1.0:
            raise ValidationError(
                "invalid_value",
                f"uncertainty must be within 0.0..1.0, got {self.uncertainty}",
                {"path": "/uncertainty"},
            )


@dataclass(frozen=True)
class Strategy(Serializable):
    flow: Flow
    needs_plan: bool
    needs_independent_review: bool
    needs_approval: bool
    max_parallel: int
    max_attempts: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CheckLink(Serializable):
    """A check tied to the acceptance criteria it is evidence for (exact criterion texts)."""

    command: str
    criteria: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskContract(Serializable):
    task_id: str
    objective: str
    context: str
    scope: tuple[str, ...]
    exclusions: tuple[str, ...]
    constraints: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    checks: tuple[str, ...]
    response_format: str
    permissions: tuple[str, ...]
    agent_id: str
    model: str
    risk: RiskLevel
    check_links: tuple[CheckLink, ...] = ()
    """Which criteria each tied check supports; a check without a link is tied to none."""
    required_checks: tuple[str, ...] = ()
    """Checks the agent spec demands; they are part of ``checks`` and must pass."""
    read_only: bool = False
    may_mutate: bool = True
    may_use_remote: bool = False
    max_attempts: int | None = None
    timeout_seconds: float | None = None
    budget_units: float | None = None
    success_criteria: tuple[str, ...] = ()
    stop_conditions: tuple[str, ...] = ()
    escalation: str = ""
    """Instructions for the agent, carried as text. The engine does not enforce these three."""


@dataclass(frozen=True)
class ToolSelection(Serializable):
    """The tools one task's agent gets, chosen per task (hypothesis H10).

    ``offered`` is the agent's allow list minus its deny list, and ``selected`` is always a
    subset of it. The token figures sum rough per-tool constants (``ToolSpec``): estimates
    for comparing the two sets, not measurements for any model or client.
    """

    offered: tuple[str, ...]
    selected: tuple[str, ...]
    dropped: tuple[str, ...]
    profile: str
    reasons: tuple[str, ...] = ()
    source: str = ""
    estimated_tokens_offered: int = 0
    estimated_tokens_selected: int = 0


@dataclass(frozen=True)
class Evidence(Serializable):
    kind: str
    summary: str
    ref: str = ""
    exit_code: int | None = None
    label: EvidenceLabel = EvidenceLabel.UNTESTED


@dataclass(frozen=True)
class TaskResult(Serializable):
    task_id: str
    status: TaskStatus
    summary: str
    evidence: tuple[Evidence, ...] = ()
    changed_files: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict(Serializable):
    accepted: bool
    score: float
    reasons: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class AttemptRecord(Serializable):
    task_id: str
    attempt: int
    status: TaskStatus
    model: str
    error_signature: str = ""


@dataclass(frozen=True)
class EscalationDecision(Serializable):
    escalate: bool
    action: GuardAction
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelChoice(Serializable):
    model: str
    tier: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PermissionDecision(Serializable):
    outcome: PermissionOutcome
    reason: str = ""


@dataclass(frozen=True)
class RawCommandResult(Serializable):
    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


@dataclass(frozen=True)
class AgentRunResult(Serializable):
    ok: bool
    output: str
    timed_out: bool = False


@dataclass(frozen=True)
class PlanTask(Serializable):
    id: str
    title: str
    objective: str
    depends_on: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.LOW
    acceptance_criteria: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    agent_hint: str = ""
    status: TaskStatus = TaskStatus.PENDING
    read_only: bool = False
    """The task changes no files (review, audit, research), so read-only agents may take it."""
    check_links: tuple[CheckLink, ...] = ()
    """Checks given as ``{"command", "criteria"}`` objects, with criteria as exact texts."""


_RUNNABLE = (TaskStatus.PENDING, TaskStatus.READY)


def _find_cycle_members(tasks: tuple[PlanTask, ...]) -> list[str]:
    """Kahn's algorithm over known dependencies; leftovers are on or behind a cycle."""
    ids = {task.id for task in tasks}
    remaining = {task.id: {d for d in task.depends_on if d in ids} for task in tasks}
    while True:
        free = [tid for tid, deps in remaining.items() if not deps]
        if not free:
            return sorted(remaining)
        for tid in free:
            del remaining[tid]
        for deps in remaining.values():
            deps.difference_update(free)
        if not remaining:
            return []


@dataclass(frozen=True)
class Plan(Serializable):
    objective: str
    tasks: tuple[PlanTask, ...] = ()

    def problems(self) -> list[str]:
        """Return every structural problem found (empty when the plan is valid)."""
        found: list[str] = []
        seen: set[str] = set()
        for task in self.tasks:
            if task.id in seen:
                found.append(f"duplicate task id: {task.id}")
            seen.add(task.id)
        for task in self.tasks:
            found.extend(
                f"task {task.id} depends on unknown task {dep}"
                for dep in task.depends_on
                if dep not in seen
            )
        cyclic = _find_cycle_members(self.tasks)
        if cyclic:
            found.append(f"dependency cycle involving: {', '.join(cyclic)}")
        return found

    def validate(self) -> None:
        found = self.problems()
        if found:
            raise ValidationError("invalid_plan", "; ".join(found), {"errors": found})

    def ready_tasks(self, completed: Iterable[str] = ()) -> tuple[PlanTask, ...]:
        """Runnable tasks (pending or ready) whose dependencies are all completed, in plan order."""
        self.validate()
        done = frozenset(completed)
        return tuple(
            task
            for task in self.tasks
            if task.id not in done
            and task.status in _RUNNABLE
            and all(dep in done for dep in task.depends_on)
        )
