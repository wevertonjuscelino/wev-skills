"""Baseline at task start: which checks already pass before any work is done.

A check that passed before the task's work, on a tree that has not changed since, shows
nothing about the work. The engine runs the task's checks once when the task starts, through
the same executor and policy, without spending any approval. The commands are marked as
baseline in the command log and are not guard events, so they never count as a loop or
against the task budget. Their command records count against the whole-run budget.
With ``harness.baseline_checks`` off only the starting tree is recorded.
"""

from __future__ import annotations

from dataclasses import replace

from wev_skills.core import run_budget
from wev_skills.core.contracts import RunStatus
from wev_skills.core.engine import Engine
from wev_skills.core.errors import ApprovalRequired, PermissionDenied
from wev_skills.execution.executor import CommandRecord
from wev_skills.guards.events import progress_event
from wev_skills.state.model import (
    CommandLogEntry,
    RunState,
    iso_utc,
    with_command,
    with_guard_event,
)
from wev_skills.state.records import TaskBaseline
from wev_skills.verification.engine import checks_from_contract


def log_entry(record: CommandRecord, task_id: str, baseline: bool = False) -> CommandLogEntry:
    return CommandLogEntry(
        at=iso_utc(record.started_at),
        task_id=task_id,
        argv=record.argv,
        cwd=record.cwd,
        exit_code=record.exit_code,
        duration_ms=max(0, record.duration_ms),
        status=record.status,
        stdout_ref=record.stdout_ref,
        stderr_ref=record.stderr_ref,
        baseline=baseline,
    )


def with_baseline(state: RunState, task_id: str, baseline: TaskBaseline) -> RunState:
    record = replace(state.tasks[task_id], baseline=baseline)
    return replace(state, tasks={**state.tasks, task_id: record})


def _run_checks(
    engine: Engine, state: RunState, task_id: str
) -> tuple[list[str], list[str], list[str], list[CommandLogEntry]]:
    """``(passed, failed, skipped, log entries)`` of the task's checks, run once."""
    contract = engine.contract(state, task_id)
    run_budget.require(engine, state, units=len(checks_from_contract(contract)))
    executor = engine.services.grantless_executor(engine.log_dir())
    passed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    entries: list[CommandLogEntry] = []
    for check in checks_from_contract(contract):
        try:
            record = executor.run(
                check.argv,
                engine.cwd(state),
                state.mode,
                contract.risk,
                timeout=check.timeout,
                task_id=task_id,
                track_changes=False,
            )
        except PermissionDenied, ApprovalRequired:
            skipped.append(check.command)
            continue
        entries.append(log_entry(record, task_id, baseline=True))
        (passed if record.status is RunStatus.PASSED else failed).append(check.command)
    return passed, failed, skipped, entries


def take(engine: Engine, state: RunState, task_id: str) -> RunState:
    """Record the baseline of a task that just started; returns the new state.

    The fingerprint is taken after the checks ran, so files a check leaves behind are not
    later mistaken for the task's work.
    """
    enabled = engine.services.config.harness.baseline_checks
    passed, failed, skipped, entries = (
        _run_checks(engine, state, task_id) if enabled else ([], [], [], [])
    )
    fingerprint = engine.fingerprint(state)
    now = engine.now()
    baseline = TaskBaseline(
        iso_utc(now), fingerprint, enabled, tuple(passed), tuple(failed), tuple(skipped)
    )

    def change(current: RunState) -> RunState:
        moved = with_baseline(current, task_id, baseline)
        for entry in entries:
            moved = with_command(moved, entry)
        return with_guard_event(moved, progress_event(task_id, now, fingerprint).to_dict())

    data = {"task_id": task_id, "taken": enabled, "passed": passed, "failed": failed}
    return engine.commit(change, "task.baseline", data)
