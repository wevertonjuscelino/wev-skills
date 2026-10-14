"""What every orchestrator operation shares: load, redact, commit with an audit event."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeVar

from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.agents.tool_profile import resolve_profile, tier_of
from wev_skills.core import agent_rules, planning, progress, run_budget, steps
from wev_skills.core.contracts import TaskContract, TaskStatus
from wev_skills.core.errors import GuardTripped, NotFound, StateConflict, ValidationError, WevError
from wev_skills.core.fingerprint import tree_fingerprint
from wev_skills.core.wiring import LOGS_DIR, Services
from wev_skills.governance.approvals import ApprovalRequest, ApprovalStatus, approval_id
from wev_skills.guards.execution import GuardLimits, GuardVerdict
from wev_skills.state.model import (
    DecisionRecord,
    Phase,
    RepoSnapshot,
    RunState,
    iso_utc,
    with_decision,
    with_next_step,
    with_pending_approval,
    without_pending_approval,
)
from wev_skills.state.records import ApprovalNote, GuardTrip
from wev_skills.state.resume import snapshot_repo
from wev_skills.state.store import StateStore

SOURCE = "orchestrator"
APPROVAL_SOURCE = "approval"
REQUESTER = "wev-orchestrator"
TASK_ACTION_PREFIX = ("wev", "task")
REVIEW_WORD = "review"
NEW_RUN_STEP = "wev run start --objective <text>"
REVISION_MISMATCH = "revision_mismatch"
MAX_COMMIT_ATTEMPTS = 5
"""How many times a read-validate-write is tried when another process wrote in between."""

Change = Callable[[RunState], RunState]
T = TypeVar("T")


def task_action(run_id: str, task_id: str) -> tuple[str, ...]:
    """The exact action a human approves before a gated task may start."""
    return (*TASK_ACTION_PREFIX, run_id, task_id)


def excluded_paths(root: str, state_dir: Path) -> tuple[str, ...]:
    """The state directory relative to ``root`` (nothing when it lives elsewhere)."""
    relative = os.path.relpath(os.path.realpath(state_dir), os.path.realpath(root))
    return () if relative.startswith(os.pardir) or relative == os.curdir else (relative,)


class Engine:
    """A store plus the wired services. It keeps nothing between calls."""

    def __init__(self, store: StateStore, services: Services) -> None:
        self.store = store
        self.services = services

    def now(self) -> float:
        return float(self.services.clock.now())

    def stamp(self) -> str:
        return iso_utc(self.now())

    def load(self) -> RunState:
        return self.store.load()

    def clean(self, text: str) -> str:
        return self.services.redact(text)

    def limits(self) -> GuardLimits:
        """Run-level guard limits, from the configuration the run pinned at its start."""
        return GuardLimits.from_config(self.services.config.limits)

    def spec_of(self, state: RunState, task_id: str) -> AgentSpec | None:
        """The resolved agent assigned to a task; ``None`` when there is none (yet)."""
        record = state.tasks.get(task_id)
        if record is None or not record.agent_id:
            return None
        try:
            return self.services.agents.resolved(record.agent_id)
        except WevError:
            return None

    def task_limits(self, state: RunState, task_id: str) -> GuardLimits:
        return agent_rules.task_limits(self.limits(), self.spec_of(state, task_id))

    def attempt_limit(self, state: RunState, task_id: str) -> int:
        return agent_rules.attempt_limit(state, self.spec_of(state, task_id))

    def log_dir(self) -> Path:
        return self.store.run_dir / LOGS_DIR

    def cwd(self, state: RunState) -> str:
        return state.repo.root if state.repo is not None else str(self.services.root)

    def excluded(self, root: str) -> tuple[str, ...]:
        return excluded_paths(root, self.services.state_dir)

    def fingerprint(self, state: RunState) -> str:
        """Hash of the working tree, the state directory left out."""
        root = self.cwd(state)
        return tree_fingerprint(self.services.runner, root, self.excluded(root))

    def snapshot(self, root: str) -> RepoSnapshot | None:
        """The real git state at ``root``, with branch and file names redacted for storage.

        Files of the state directory are left out: the engine's records are not work.
        """
        found = snapshot_repo(root, self.services.runner, self.excluded(root))
        if found is None:
            return None
        files = tuple(self.clean(path) for path in found.dirty_files)
        return replace(found, branch=self.clean(found.branch), dirty_files=files)

    def decision(
        self, phase: Phase, text: str, reasons: Sequence[str] = (), source: str = SOURCE
    ) -> DecisionRecord:
        cleaned = tuple(self.clean(reason) for reason in reasons)
        return DecisionRecord(self.stamp(), phase, self.clean(text), cleaned, source)

    def commit(
        self,
        change: Change,
        event: str,
        data: Mapping[str, Any] | None = None,
        step: str | None = None,
        base: RunState | None = None,
    ) -> RunState:
        """Apply ``change`` through ``StateStore.update`` and append one audit event.

        ``base`` is the state the caller validated against. With it the write is refused
        (``StateConflict``) when another process changed the run in between, and the
        caller repeats its read-validate-write through ``retry``. Without it ``change``
        must be safe on any newer state: it only appends records and decides nothing.
        """

        def mutator(state: RunState) -> RunState:
            refuse_finished(state)
            changed = self._with_trips(change(state))
            denied = self.denied_gates(changed)
            chosen = step or steps.next_step(changed, self.suggest_reviewer, denied)
            return with_next_step(changed, chosen)

        expected = base.revision if base is not None else None
        state = self.store.update(mutator, expected)
        self.services.audit.append(event, {"run_id": state.run_id, **dict(data or {})})
        return state

    def retry(self, operation: Callable[[], T]) -> T:
        """Run a read-validate-write; repeat it from the read when the state moved on."""
        for _ in range(MAX_COMMIT_ATTEMPTS - 1):
            try:
                return operation()
            except StateConflict as exc:
                if exc.code != REVISION_MISMATCH:
                    raise
        try:
            return operation()
        except StateConflict as exc:
            if exc.code != REVISION_MISMATCH:
                raise
            message = i18n.t("orch.error.busy", attempts=MAX_COMMIT_ATTEMPTS)
            raise StateConflict("state_busy", message, dict(exc.details)) from exc

    def suggest_reviewer(self, executor: str) -> str:
        """An agent other than ``executor``, preferring one whose role is reviewing."""
        others = [spec for spec in self.services.agents.routable() if spec.id != executor]
        reviewers = [
            spec
            for spec in others
            if REVIEW_WORD in spec.id or any(REVIEW_WORD in word for word in spec.specialties)
        ]
        chosen = (reviewers or others)[:1]
        return chosen[0].id if chosen else ""

    def step_fields(self, state: RunState, first: str | None = None) -> dict[str, Any]:
        """``next_step`` and the full ``next_steps`` list for a payload."""
        found = list(steps.next_steps(state, self.suggest_reviewer, self.denied_gates(state)))
        ordered = [first, *(s for s in found if s != first)] if first else found
        return {
            "next_step": ordered[0],
            "next_steps": ordered,
            "budget": run_budget.payload(state, self.services.config.limits),
        }

    def contract(self, state: RunState, task_id: str) -> TaskContract:
        task = progress.plan_task(state, task_id)
        record = state.tasks[task_id]
        spec = self.services.agents.resolved(record.agent_id)
        config = self.services.config
        tier = tier_of(record.model, config.models)
        profile = resolve_profile(config.harness.tool_profile, tier)
        protected = config.permissions.protected_paths
        chosen = record.tool_selection
        return planning.build_contract(state, task, spec, protected, profile, chosen)

    def run_verdict(self, state: RunState) -> GuardVerdict:
        budget = run_budget.verdict(state, self.services.config.limits)
        if budget.action.value == "stop":
            return budget
        return progress.run_verdict(
            state,
            replace(self.limits(), budget_units=self.services.config.limits.run_budget_units),
            self.now(),
            lambda task_id: self.task_limits(state, task_id),
        )

    def task_verdict(self, state: RunState, task_id: str, now: float | None = None) -> GuardVerdict:
        """The verdict over one task's events (or over the events recorded without a task)."""
        events = progress.guard_events(state, task_id)
        if task_id not in state.tasks:
            limits = replace(self.limits(), task_timeout_seconds=None, budget_units=None)
            return progress.task_verdict(events, limits, now=now)
        return progress.task_verdict(events, self.task_limits(state, task_id), now=now)

    def refuse_tripped(self, state: RunState, task_id: str | None = None) -> None:
        """Raise ``GuardTripped`` while the run's or the task's verdict is STOP or ASK_HUMAN.

        The verdict is recorded first, so it stays in the report whatever happens next.
        """
        verdicts = [self.run_verdict(state)]
        if task_id and task_id in state.tasks:
            verdicts.append(self.task_verdict(state, task_id, self.now()))
        blocking = [v for v in verdicts if v.action in progress.BLOCKING_ACTIONS]
        if not blocking:
            return
        verdict = blocking[0]
        scope = str(verdict.details.get("task_id") or task_id or "")
        trip = GuardTrip(self.stamp(), scope, verdict.action.value, verdict.rule, verdict.reasons)
        self.commit(lambda current: with_trip(current, trip), "guard.tripped", trip.to_dict())
        details = {
            "verdict": verdict.to_dict(),
            "next_step": f"wev guard check --run {state.run_id}",
        }
        raise GuardTripped("guard_tripped", self.blocked_message(verdict), details)

    def _with_trips(self, state: RunState) -> RunState:
        """``state`` with every rule that is tripped now recorded once (timeouts aside)."""
        current = state
        task_ids = dict.fromkeys(str(event.get("task_id", "")) for event in state.guard_events)
        for task_id in task_ids:
            events = progress.guard_events(current, task_id)
            if task_id in current.tasks:
                limits = self.task_limits(current, task_id)
            else:
                limits = replace(self.limits(), budget_units=None)
            verdict = progress.task_verdict(events, replace(limits, task_timeout_seconds=None))
            if verdict.rule != progress.RULE_NONE:
                trip = GuardTrip("", task_id, verdict.action.value, verdict.rule, verdict.reasons)
                current = with_trip(current, trip, self.stamp)
        return current

    def approval(self, approval_id_: str) -> ApprovalRequest | None:
        try:
            return self.services.approvals.get(approval_id_)
        except NotFound:
            return None

    def approval_status(self, action: Sequence[str]) -> ApprovalStatus | None:
        record = self.approval(approval_id(action))
        return record.status if record is not None else None

    def denied_gates(self, state: RunState) -> dict[str, str]:
        """Task id -> approval id for unsettled tasks whose start a person denied."""
        found: dict[str, str] = {}
        for task in state.plan.tasks if state.plan else ():
            idle = state.tasks[task.id].status not in (*progress.SETTLED, TaskStatus.RUNNING)
            if not idle or not progress.needs_approval(state, task):
                continue
            record = self.approval(approval_id(task_action(state.run_id, task.id)))
            if record is not None and record.status is ApprovalStatus.DENIED:
                found[task.id] = record.id
        return found

    def reconciled(self, state: RunState) -> RunState:
        """``state`` without the pending approvals that the store no longer lists as pending."""
        current = state
        for pending_id in state.pending_approvals:
            record = self.approval(pending_id)
            if record is None or record.status is not ApprovalStatus.PENDING:
                current = without_pending_approval(current, pending_id)
        return current

    def note_approval(
        self, state: RunState, approval_id_: str, task_id: str = "", kind: str = "command"
    ) -> RunState:
        """Record a requested approval as pending, with what it is for and a decision (once)."""
        if approval_id_ in state.pending_approvals:
            return state
        text = i18n.t("orch.decision.approval", id=approval_id_)
        stamp = self.stamp()
        record = DecisionRecord(stamp, state.phase, text, (approval_id_,), APPROVAL_SOURCE)
        note = ApprovalNote(approval_id_, task_id, kind, stamp)
        kept = tuple(n for n in state.approval_notes if n.id != approval_id_)
        noted = replace(state, approval_notes=(*kept, note))
        return with_decision(with_pending_approval(noted, approval_id_), record)

    def blocked_message(self, verdict: GuardVerdict) -> str:
        return i18n.t("orch.error.guard", action=verdict.action.value, rule=verdict.rule)


def with_trip(state: RunState, trip: GuardTrip, stamp: Callable[[], str] | None = None) -> RunState:
    """Append ``trip`` unless the latest trip of the same task already says the same."""
    previous = [old for old in state.guard_trips if old.task_id == trip.task_id]
    if previous and (previous[-1].action, previous[-1].rule) == (trip.action, trip.rule):
        return state
    dated = replace(trip, at=stamp()) if stamp is not None and not trip.at else trip
    return replace(state, guard_trips=(*state.guard_trips, dated))


def refuse_finished(state: RunState) -> None:
    """A finished run is a closed record: it can be read, never changed."""
    if state.phase is Phase.DONE:
        message = i18n.t("orch.error.run_finished", run=state.run_id)
        raise ValidationError("run_finished", message, {"next_step": NEW_RUN_STEP})


def set_assignment(state: RunState, task_id: str, agent_id: str, model: str) -> RunState:
    record = replace(state.tasks[task_id], agent_id=agent_id, model=model)
    return replace(state, tasks={**state.tasks, task_id: record})


def restamp_started(state: RunState, task_id: str, at: str) -> RunState:
    """Mark ``at`` as the task's last start, so only later verifications count as fresh."""
    record = replace(state.tasks[task_id], started_at=at)
    return replace(state, tasks={**state.tasks, task_id: record})
