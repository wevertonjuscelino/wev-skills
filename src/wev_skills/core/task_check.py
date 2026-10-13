"""VERIFY: run a task's checks, judge its criteria and store the report."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from wev_skills import i18n
from wev_skills.core import progress
from wev_skills.core.baseline import log_entry
from wev_skills.core.contracts import Mode, PermissionOutcome, TaskContract
from wev_skills.core.engine import REQUESTER, Change, Engine
from wev_skills.core.errors import ValidationError
from wev_skills.core.task_exec import COMMAND_UNITS, progress_events
from wev_skills.guards.events import budget_event, command_signature, verification_event
from wev_skills.state.model import (
    Phase,
    RunState,
    iso_utc,
    with_command,
    with_evidence,
    with_guard_event,
    with_phase,
)
from wev_skills.state.records import (
    CheckOutcome,
    CriterionOutcome,
    TaskBaseline,
    VerificationRecord,
)
from wev_skills.verification.engine import (
    Check,
    VerificationEngine,
    VerificationReport,
    build_result,
    checks_from_contract,
)

BASELINE_TAKEN, BASELINE_NOT_TAKEN = "taken", "not_taken"


def _outcomes(
    report: VerificationReport, checks: Sequence[Check], baseline: TaskBaseline | None
) -> tuple[CheckOutcome, ...]:
    by_id = {check.id: check for check in checks}
    passed_before = set(baseline.passed) if baseline is not None and baseline.taken else set()
    return tuple(
        CheckOutcome(
            check_id=run.check_id,
            argv=run.record.argv if run.record else by_id[run.check_id].argv,
            state=run.state.value,
            exit_code=run.record.exit_code if run.record else None,
            log_ref=run.record.stdout_ref if run.record else "",
            reason=run.reason,
            tied=by_id[run.check_id].tied,
            trivial=by_id[run.check_id].trivial,
            required=by_id[run.check_id].required,
            baseline_passed=by_id[run.check_id].command in passed_before,
        )
        for run in report.checks
    )


def _record(
    report: VerificationReport,
    checks: Sequence[Check],
    at: str,
    fingerprint: str,
    baseline: TaskBaseline | None,
    tree_changed: bool | None,
) -> VerificationRecord:
    by_id = {check.id: check for check in checks}
    criteria = tuple(
        CriterionOutcome(c.criterion, c.status.value, c.evidence_refs, c.support, c.reason)
        for c in report.criteria
    )
    skipped = tuple(" ".join(by_id[check_id].argv) for check_id in report.unexecuted_checks)
    taken = baseline is not None and baseline.taken
    return VerificationRecord(
        report.task_id,
        at,
        report.all_met,
        report.summary,
        _outcomes(report, checks, baseline),
        criteria,
        skipped,
        fingerprint,
        BASELINE_TAKEN if taken else BASELINE_NOT_TAKEN,
        tree_changed,
        report.warnings,
    )


def _check_approvals(
    engine: Engine, state: RunState, contract: TaskContract, checks: Sequence[Check]
) -> list[str]:
    """Ask for approval of every check the policy will not run without one."""
    policy, cwd = engine.services.policy, engine.cwd(state)
    pending = []
    for check in checks:
        decision = policy.check_command(check.argv, cwd, state.mode, contract.risk, consume=False)
        if decision.outcome is PermissionOutcome.NEEDS_APPROVAL:
            request = engine.services.approvals.request(
                check.argv, contract.risk, engine.clean(decision.reason), REQUESTER
            )
            pending.append(request.id)
    return pending


def _refuse_unstarted(state: RunState, task_id: str) -> None:
    progress.plan_task(state, task_id)
    if state.mode is Mode.PLAN or state.tasks[task_id].status not in progress.STARTED:
        message = i18n.t("orch.error.not_started_task", task=task_id)
        raise ValidationError("task_not_started", message, {"task_id": task_id})


def _append_verification(state: RunState, record: VerificationRecord) -> RunState:
    return replace(state, verifications=(*state.verifications, record))


@dataclass(frozen=True)
class _Checked:
    """One verification as it happened: the report, the trees around it, what was asked."""

    task_id: str
    contract: TaskContract
    checks: tuple[Check, ...]
    report: VerificationReport
    record: VerificationRecord
    before: str
    at: float
    pending: tuple[str, ...]


def _verify(engine: Engine, state: RunState, task_id: str, stop_on_failure: bool) -> _Checked:
    """Run the checks and judge them against the task's baseline; nothing is stored yet."""
    contract = engine.contract(state, task_id)
    checks = checks_from_contract(contract)
    pending = _check_approvals(engine, state, contract, checks)
    baseline = state.tasks[task_id].baseline
    before = engine.fingerprint(state)
    unchanged = baseline is not None and before == baseline.fingerprint
    judged = baseline is not None and baseline.taken and not contract.read_only
    verifier = VerificationEngine(engine.services.executor(engine.log_dir()))
    report = verifier.verify(
        contract,
        checks,
        engine.cwd(state),
        state.mode,
        stop_on_failure,
        baseline_passed=baseline.passed if judged and baseline else None,
        tree_unchanged=unchanged,
    )
    fingerprint = engine.fingerprint(state)
    now = engine.now()
    changed = None if baseline is None else not unchanged
    record = _record(report, checks, iso_utc(now), fingerprint, baseline, changed)
    return _Checked(task_id, contract, checks, report, record, before, now, tuple(pending))


def _store(engine: Engine, state: RunState, done: _Checked) -> Change:
    """The append-only change that records a verification, its commands and its events."""
    task_id, report, now = done.task_id, done.report, done.at
    commands = [" ".join(check.argv) for check in done.checks]
    signature = command_signature(commands, engine.cwd(state))
    fingerprint = done.record.fingerprint
    verified = verification_event(task_id, now, signature, report.all_met, fingerprint)
    evidence = build_result(done.contract, report, ()).evidence
    ran = [run.record for run in report.checks if run.record is not None]

    def change(current: RunState) -> RunState:
        ahead, behind = progress_events(current, task_id, now, done.before, fingerprint)
        spent = [budget_event(task_id, now, COMMAND_UNITS) for _ in ran]
        moved = current
        for event in (*ahead, verified, *spent, *behind):
            moved = with_guard_event(moved, event.to_dict())
        for command in ran:
            moved = with_command(moved, log_entry(command, task_id))
        for item in evidence:
            moved = with_evidence(moved, task_id, item)
        for pending_id in done.pending:
            moved = engine.note_approval(moved, pending_id, task_id, progress.KIND_COMMAND)
        moved = engine.reconciled(moved)
        return with_phase(_append_verification(moved, done.record), Phase.VERIFY)

    return change


def check_task(engine: Engine, task_id: str, stop_on_failure: bool) -> dict[str, Any]:
    """Run the contract's checks, store the report and its evidence, add guard events.

    Checks that already passed at the task's baseline, on a tree that has not changed since
    the task started, are not evidence of the work (a read-only task is exempt: it is not
    expected to change anything).
    """
    state = engine.load()
    _refuse_unstarted(state, task_id)
    engine.refuse_tripped(state, task_id)
    done = _verify(engine, state, task_id, stop_on_failure)
    report = done.report
    data = {"task_id": task_id, "all_met": report.all_met, "summary": report.summary}
    after = engine.commit(_store(engine, state, done), "task.checked", data)
    return {
        "run_id": after.run_id,
        "task_id": task_id,
        "all_met": report.all_met,
        "report": report.to_dict(),
        "baseline": done.record.baseline,
        "tree_changed": done.record.tree_changed,
        "warnings": list(report.warnings),
        "notice": i18n.t("orch.notice.checks"),
        "fingerprint_notice": i18n.t("orch.notice.fingerprint"),
        "pending_approvals": list(done.pending),
        **engine.step_fields(after),
    }
