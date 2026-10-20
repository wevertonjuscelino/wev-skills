"""Run state model: frozen records plus pure helpers that each return a new ``RunState``.

State never holds secrets. Callers pass text that is already redacted (objectives, summaries,
argv, blockers, refs); this module cannot recognize a secret inside free text. What it can
enforce, it does: free-form JSON (``discovery``, ``guard_events``) is rejected when it carries
an environment mapping, and ``CommandLogEntry`` has no field for one.
Timestamps are ISO-8601 UTC strings (see ``iso_utc``); an unset timestamp is ``""``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import (
    AttemptRecord,
    Classification,
    Evidence,
    Mode,
    Plan,
    RunStatus,
    Strategy,
    TaskResult,
    TaskStatus,
    ToolSelection,
)
from wev_skills.core.errors import ValidationError
from wev_skills.state._values import RUN_ID_RE, iso_utc, plain_json, validate_run_id
from wev_skills.state._values import invalid as _invalid
from wev_skills.state.records import (
    ApprovalNote,
    GuardTrip,
    PlanAmendment,
    RemoteRunRecord,
    ReviewRecord,
    TaskBaseline,
    ToolMiss,
    VerificationRecord,
)

__all__ = ["RUN_ID_RE", "iso_utc", "plain_json", "validate_run_id"]

SCHEMA_VERSION = 1
_S = TaskStatus
_ALLOWED: Mapping[TaskStatus, frozenset[TaskStatus]] = MappingProxyType(
    {
        _S.PENDING: frozenset({_S.READY, _S.RUNNING, _S.BLOCKED, _S.NOT_EXECUTED}),
        _S.READY: frozenset({_S.PENDING, _S.RUNNING, _S.BLOCKED, _S.NOT_EXECUTED}),
        _S.RUNNING: frozenset({_S.VERIFIED, _S.PARTIAL, _S.BLOCKED, _S.FAILED, _S.NOT_EXECUTED}),
        _S.PARTIAL: frozenset({_S.RUNNING, _S.BLOCKED, _S.FAILED, _S.NOT_EXECUTED}),
        _S.BLOCKED: frozenset({_S.PENDING, _S.READY, _S.RUNNING, _S.FAILED, _S.NOT_EXECUTED}),
        _S.FAILED: frozenset({_S.RUNNING, _S.BLOCKED, _S.NOT_EXECUTED}),
        _S.VERIFIED: frozenset(),
        _S.NOT_EXECUTED: frozenset(),
    }
)
_OUTCOMES = frozenset({_S.VERIFIED, _S.PARTIAL, _S.BLOCKED, _S.FAILED, _S.NOT_EXECUTED})
_FINISHED = _OUTCOMES - {_S.BLOCKED}


class Phase(StrEnum):
    REQUEST = "request"
    DISCOVER = "discover"
    CLASSIFY = "classify"
    PLAN = "plan"
    DECIDE = "decide"
    EXECUTE = "execute"
    VERIFY = "verify"
    REVIEW = "review"
    DELIVER = "deliver"
    DONE = "done"


@dataclass(frozen=True)
class TaskRecord(Serializable):
    status: TaskStatus = TaskStatus.PENDING
    agent_id: str = ""
    model: str = ""
    attempts: tuple[AttemptRecord, ...] = ()
    result: TaskResult | None = None
    started_at: str = ""
    finished_at: str = ""
    starts: int = 0
    """Every start of the task since it was created or last reopened by a person."""
    baseline: TaskBaseline | None = None
    tree_changed: bool | None = None
    """Whether the working tree differed from the start of the task when it was recorded."""
    block_reason: str = ""
    tool_selection: ToolSelection | None = None
    """The tools chosen for this task; ``None`` when selection is off (and in older states)."""
    tool_misses: tuple[ToolMiss, ...] = ()
    lessons_shown: tuple[str, ...] = ()
    """Lessons shown to the task, as release 3.0.0 recorded them; read so its runs still load
    and count. Starts now record a ``lessons.shown`` event instead (``core.shown_lessons``)."""

    def to_dict(self) -> dict[str, Any]:
        """Leave ``lessons_shown`` out when empty, so a new run stays readable by 2.0.0."""
        data = super().to_dict()
        if not self.lessons_shown:
            del data["lessons_shown"]
        return data


@dataclass(frozen=True)
class DecisionRecord(Serializable):
    at: str
    phase: Phase
    decision: str
    reasons: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class CommandLogEntry(Serializable):
    """One executed command. ``argv`` must already be redacted; there is no environment field."""

    at: str
    task_id: str
    argv: tuple[str, ...]
    cwd: str
    exit_code: int | None
    duration_ms: int
    status: RunStatus
    stdout_ref: str = ""
    stderr_ref: str = ""
    baseline: bool = False
    """Run by the engine before the task's work, to know which checks already passed."""


@dataclass(frozen=True)
class TaskEvidence(Serializable):
    task_id: str
    evidence: Evidence


@dataclass(frozen=True)
class RepoSnapshot(Serializable):
    root: str
    branch: str
    head: str
    dirty_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunState(Serializable):
    run_id: str
    objective: str
    mode: Mode
    created_at: str
    updated_at: str
    phase: Phase = Phase.REQUEST
    schema_version: int = SCHEMA_VERSION
    revision: int = 1
    classification: Classification | None = None
    strategy: Strategy | None = None
    plan: Plan | None = None
    tasks: Mapping[str, TaskRecord] = field(default_factory=dict)
    decisions: tuple[DecisionRecord, ...] = ()
    commands: tuple[CommandLogEntry, ...] = ()
    evidence: tuple[TaskEvidence, ...] = ()
    blockers: tuple[str, ...] = ()
    pending_approvals: tuple[str, ...] = ()
    next_step: str = ""
    repo: RepoSnapshot | None = None
    discovery: Mapping[str, Any] = field(default_factory=dict)
    guard_events: tuple[Mapping[str, Any], ...] = ()
    verifications: tuple[VerificationRecord, ...] = ()
    reviews: tuple[ReviewRecord, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)
    """The configuration resolved at ``run start``; every later command uses this snapshot."""
    config_digest: str = ""
    config_source: str = ""
    approval_notes: tuple[ApprovalNote, ...] = ()
    guard_trips: tuple[GuardTrip, ...] = ()
    remote_runs: tuple[RemoteRunRecord, ...] = ()
    """Remote commands this run started, one per task and host; absent in older states."""
    plan_amendments: tuple[PlanAmendment, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise _invalid(
                "state_version_unsupported",
                f"state schema_version {self.schema_version!r} is not supported "
                f"(this engine reads version {SCHEMA_VERSION})",
                "/schema_version",
            )
        if self.revision < 1:
            raise _invalid("invalid_value", "/revision: must be at least 1", "/revision")
        validate_run_id(self.run_id)
        tasks, events = self.tasks, self.guard_events
        if not isinstance(tasks, Mapping) or not all(
            isinstance(key, str) and isinstance(item, TaskRecord) for key, item in tasks.items()
        ):
            raise _invalid("invalid_value", "/tasks: expected task id -> TaskRecord", "/tasks")
        if not isinstance(self.discovery, Mapping):
            raise _invalid("invalid_value", "/discovery: expected an object", "/discovery")
        if not all(isinstance(event, Mapping) for event in events):
            raise _invalid("invalid_value", "/guard_events: expected objects", "/guard_events")
        frozen_events = tuple(
            MappingProxyType(plain_json(event, f"/guard_events/{i}"))
            for i, event in enumerate(events)
        )
        object.__setattr__(self, "tasks", MappingProxyType(dict(tasks)))
        object.__setattr__(
            self, "discovery", MappingProxyType(plain_json(self.discovery, "/discovery"))
        )
        object.__setattr__(self, "guard_events", frozen_events)
        object.__setattr__(self, "config", MappingProxyType(plain_json(self.config, "/config")))

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        return {
            **data,
            "tasks": {key: record.to_dict() for key, record in self.tasks.items()},
            "discovery": plain_json(self.discovery),
            "config": plain_json(self.config),
            "guard_events": [plain_json(event) for event in self.guard_events],
        }

    @classmethod
    def from_dict(cls, data: Any, _path: str = "") -> RunState:
        if isinstance(data, dict) and isinstance(data.get("tasks"), dict):
            tasks = {
                key: TaskRecord.from_dict(item, f"{_path}/tasks/{key}")
                for key, item in data["tasks"].items()
            }
            data = {**data, "tasks": tasks}
        return super().from_dict(data, _path)


def _task(state: RunState, task_id: str) -> TaskRecord:
    record = state.tasks.get(task_id)
    if record is None:
        raise _invalid("unknown_task", f"unknown task: {task_id!r}", f"/tasks/{task_id}")
    return record


def _put(state: RunState, task_id: str, record: TaskRecord) -> RunState:
    return replace(state, tasks={**state.tasks, task_id: record})


def _unique(items: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    return items + tuple(dict.fromkeys(item for item in extra if item not in items))


def _check_transition(state: RunState, task_id: str, target: TaskStatus) -> None:
    current = _task(state, task_id).status
    if target not in _ALLOWED[current]:
        raise ValidationError(
            "illegal_transition",
            f"task {task_id}: {current.value} -> {target.value} is not allowed "
            "(use reopen to run a finished task again)",
            {"task_id": task_id, "from": current.value, "to": target.value},
        )
    if target not in (_S.READY, _S.RUNNING) or state.plan is None:
        return
    depends_on = next((t.depends_on for t in state.plan.tasks if t.id == task_id), ())
    unmet = [d for d in depends_on if d not in state.tasks or state.tasks[d].status != _S.VERIFIED]
    if unmet:
        raise ValidationError(
            "dependency_not_verified",
            f"task {task_id} cannot be {target.value}: dependencies not verified: {unmet}",
            {"task_id": task_id, "unmet": unmet},
        )


def with_phase(state: RunState, phase: Phase | str) -> RunState:
    try:
        return replace(state, phase=Phase(phase))
    except ValueError as exc:
        raise _invalid("invalid_enum", f"unknown phase: {phase!r}", "/phase") from exc


def with_classification(state: RunState, classification: Classification | None) -> RunState:
    return replace(state, classification=classification)


def with_strategy(state: RunState, strategy: Strategy | None) -> RunState:
    return replace(state, strategy=strategy)


def with_plan(state: RunState, plan: Plan) -> RunState:
    """Store a valid plan; new task ids start PENDING, existing records are kept untouched."""
    plan.validate()
    added = {task.id: TaskRecord() for task in plan.tasks if task.id not in state.tasks}
    return replace(state, plan=plan, tasks={**state.tasks, **added})


def with_task(state: RunState, task_id: str) -> RunState:
    """Register a PENDING task that is not part of a plan (direct flow)."""
    if not task_id or task_id in state.tasks:
        raise _invalid("invalid_task", f"empty or duplicate task id: {task_id!r}", "/tasks")
    return _put(state, task_id, TaskRecord())


def with_task_status(
    state: RunState,
    task_id: str,
    status: TaskStatus,
    at: str = "",
    agent_id: str | None = None,
    model: str | None = None,
) -> RunState:
    """Move a task to ``status`` when the transition is legal and its dependencies allow it."""
    _check_transition(state, task_id, status)
    record = replace(_task(state, task_id), status=status)
    if status == _S.RUNNING:
        record = replace(record, started_at=at, finished_at="")
    if status in _FINISHED:
        record = replace(record, finished_at=at)
    if agent_id is not None:
        record = replace(record, agent_id=agent_id)
    if model is not None:
        record = replace(record, model=model)
    return _put(state, task_id, record)


def reopen(state: RunState, task_id: str, at: str, reason: str) -> RunState:
    """Explicitly send a task back to PENDING (keeps attempts, clears the result), with a reason."""
    record = _task(state, task_id)
    if not reason.strip():
        raise _invalid("reason_required", f"reopening task {task_id} requires a reason")
    fresh = replace(record, status=_S.PENDING, result=None, started_at="", finished_at="")
    decision = DecisionRecord(at, state.phase, f"reopen task {task_id}", (reason,), "reopen")
    return with_decision(_put(state, task_id, fresh), decision)


def with_attempt(state: RunState, attempt: AttemptRecord) -> RunState:
    record = _task(state, attempt.task_id)
    last = record.attempts[-1].attempt if record.attempts else 0
    if attempt.attempt <= last:
        raise _invalid("invalid_attempt", f"attempt {attempt.attempt} is not after {last}")
    return _put(state, attempt.task_id, replace(record, attempts=(*record.attempts, attempt)))


def with_evidence(state: RunState, task_id: str, evidence: Evidence) -> RunState:
    _task(state, task_id)
    return replace(state, evidence=(*state.evidence, TaskEvidence(task_id, evidence)))


def with_result(state: RunState, result: TaskResult, at: str = "") -> RunState:
    """Attach an outcome: legal status change, result, its evidence and its blockers."""
    task_id = result.task_id
    if result.status not in _OUTCOMES:
        raise _invalid("invalid_result", f"{result.status.value} is not a task outcome")
    moved = state
    if _task(state, task_id).status != result.status:
        moved = with_task_status(state, task_id, result.status, at)
    entries = tuple(TaskEvidence(task_id, item) for item in result.evidence)
    return replace(
        _put(moved, task_id, replace(_task(moved, task_id), result=result)),
        evidence=state.evidence + entries,
        blockers=_unique(state.blockers, result.blockers),
    )


def with_decision(state: RunState, decision: DecisionRecord) -> RunState:
    return replace(state, decisions=(*state.decisions, decision))


def with_command(state: RunState, entry: CommandLogEntry) -> RunState:
    return replace(state, commands=(*state.commands, entry))


def with_blocker(state: RunState, blocker: str) -> RunState:
    return replace(state, blockers=_unique(state.blockers, (blocker,)))


def without_blocker(state: RunState, blocker: str) -> RunState:
    return replace(state, blockers=tuple(b for b in state.blockers if b != blocker))


def with_pending_approval(state: RunState, approval_id: str) -> RunState:
    return replace(state, pending_approvals=_unique(state.pending_approvals, (approval_id,)))


def without_pending_approval(state: RunState, approval_id: str) -> RunState:
    kept = tuple(a for a in state.pending_approvals if a != approval_id)
    return replace(state, pending_approvals=kept)


def with_next_step(state: RunState, next_step: str) -> RunState:
    return replace(state, next_step=next_step)


def with_repo(state: RunState, repo: RepoSnapshot | None) -> RunState:
    return replace(state, repo=repo)


def with_discovery(state: RunState, key: str, value: Any) -> RunState:
    """Set one discovered fact (plain JSON). Environment mappings are refused."""
    return replace(state, discovery={**state.discovery, key: value})


def with_remote_run(state: RunState, record: RemoteRunRecord) -> RunState:
    """Store a remote start, replacing an earlier one of the same task on the same host."""
    same = (record.task_id, record.alias)
    kept = tuple(old for old in state.remote_runs if (old.task_id, old.alias) != same)
    return replace(state, remote_runs=(*kept, record))


def with_guard_event(state: RunState, event: Mapping[str, Any]) -> RunState:
    """Append one execution-guard event, stored as an uninterpreted JSON object."""
    return replace(state, guard_events=(*state.guard_events, event))
