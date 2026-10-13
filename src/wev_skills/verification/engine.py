"""Verification engine: decide from evidence whether acceptance criteria were met (4.9)."""

from __future__ import annotations

import re
import shlex
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import (
    Evidence,
    EvidenceLabel,
    Mode,
    RunStatus,
    TaskContract,
    TaskResult,
    TaskStatus,
)
from wev_skills.core.errors import ApprovalRequired, PermissionDenied, ValidationError
from wev_skills.execution.executor import CommandExecutor, CommandRecord, to_evidence
from wev_skills.verification.trivial import is_trivial

DEFAULT_CHECK_COST = 30
SUPPORT_TIED, SUPPORT_UNTIED, SUPPORT_MANUAL, SUPPORT_NONE = "tied", "untied", "manual", "none"
"""What stands behind a criterion: a check the plan tied to it, a generic check that was
not written for it, evidence the agent supplied by hand, or nothing."""
# (cost, keywords): the first row with a matching token wins. Lower cost runs first.
_COST_TABLE: tuple[tuple[int, frozenset[str]], ...] = (
    (50, frozenset({"e2e", "playwright", "cypress", "selenium"})),
    (40, frozenset({"integration"})),
    (
        10,
        frozenset(
            {
                "lint",
                "ruff",
                "flake8",
                "eslint",
                "mypy",
                "pyright",
                "tsc",
                "typecheck",
                "format",
                "prettier",
                "black",
            }
        ),
    ),
    (20, frozenset({"unit", "unittest"})),
    (25, frozenset({"pytest", "jest", "vitest", "test", "tests"})),
)


class CriterionStatus(StrEnum):
    MET = "met"
    UNMET = "unmet"
    UNVERIFIED = "unverified"


class CheckState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"
    REFUSED = "refused"


@dataclass(frozen=True)
class Check(Serializable):
    id: str
    argv: tuple[str, ...]
    cost: int = DEFAULT_CHECK_COST
    criteria: tuple[str, ...] = ()
    timeout: float | None = None
    command: str = ""
    tied: bool = False
    """The plan names the criteria this check is evidence for."""
    required: bool = False
    """Demanded by the agent spec: it must pass, and it is not evidence of the work."""
    trivial: bool = False
    """A no-op that cannot fail; it carries no evidence."""


@dataclass(frozen=True)
class CheckRun(Serializable):
    check_id: str
    state: CheckState
    record: CommandRecord | None = None
    reason: str = ""


@dataclass(frozen=True)
class CriterionResult(Serializable):
    criterion: str
    status: CriterionStatus
    evidence_refs: tuple[str, ...] = ()
    support: str = SUPPORT_NONE
    reason: str = ""


@dataclass(frozen=True)
class VerificationReport(Serializable):
    task_id: str
    checks: tuple[CheckRun, ...]
    criteria: tuple[CriterionResult, ...]
    all_met: bool
    unexecuted_checks: tuple[str, ...]
    summary: str
    warnings: tuple[str, ...] = ()
    no_work: bool = False
    """Every passing check had already passed before the task's work, on an unchanged tree."""


def _state_of(record: CommandRecord) -> CheckState:
    return {
        RunStatus.PASSED: CheckState.PASSED,
        RunStatus.FAILED: CheckState.FAILED,
        RunStatus.BLOCKED: CheckState.BLOCKED,
    }.get(record.status, CheckState.INCONCLUSIVE)


def _cost_of(argv: Sequence[str]) -> int:
    text = " ".join(argv).lower().replace("end-to-end", "e2e")
    tokens = set(re.findall(r"[a-z0-9]+", text))
    return next((cost for cost, words in _COST_TABLE if tokens & words), DEFAULT_CHECK_COST)


def _argv_of(command: str) -> tuple[str, ...]:
    try:
        argv = tuple(shlex.split(command))
    except ValueError as exc:
        raise ValidationError(
            "invalid_check",
            i18n.t("verify.error.bad_check", command=command, error=str(exc)),
            {"command": command},
        ) from exc
    if not argv:
        raise ValidationError(
            "invalid_check", i18n.t("verify.error.bad_check", command=command, error="empty")
        )
    return argv


def checks_from_contract(contract: TaskContract) -> tuple[Check, ...]:
    """One check per command string.

    A check the plan tied to criteria supports only those. Any other check supports every
    criterion, which the report labels as generic evidence. A check the agent spec requires
    is a gate: it must pass, and by itself it does not show the work was done.
    """
    links = {link.command: link.criteria for link in contract.check_links}
    checks: list[Check] = []
    for index, command in enumerate(contract.checks, start=1):
        argv = _argv_of(command)
        required = command in contract.required_checks
        tied = command in links and not required
        criteria = links[command] if tied else contract.acceptance_criteria
        checks.append(
            Check(
                f"check-{index}",
                argv,
                _cost_of(argv),
                criteria,
                command=command,
                tied=tied,
                required=required,
                trivial=is_trivial(argv),
            )
        )
    return tuple(checks)


def _manual_refs(criterion: str, manual: Sequence[Evidence]) -> tuple[str, ...]:
    """Manual evidence names its criterion in ``kind``; it counts only if TESTED with a ref."""
    names = {criterion, f"criterion:{criterion}"}
    return tuple(
        e.ref for e in manual if e.kind in names and e.label is EvidenceLabel.TESTED and e.ref
    )


def _unverified(criterion: str, refs: tuple[str, ...], key: str) -> CriterionResult:
    reason = i18n.t(f"verify.reason.{key}")
    return CriterionResult(criterion, CriterionStatus.UNVERIFIED, refs, SUPPORT_NONE, reason)


def _judge(
    criterion: str,
    checks: Sequence[Check],
    runs: dict[str, CheckRun],
    manual: Sequence[Evidence],
    no_work: bool,
) -> CriterionResult:
    """One criterion from the checks that support it; a failed check beats everything."""
    supporting = [c for c in checks if criterion in c.criteria]
    states = [runs[c.id].state if c.id in runs else None for c in supporting]
    records = [runs[c.id].record for c in supporting if c.id in runs]
    refs = tuple(record.stdout_ref for record in records if record is not None)
    manual_refs = _manual_refs(criterion, manual)
    if CheckState.FAILED in states:
        reason = i18n.t("verify.reason.failed")
        return CriterionResult(criterion, CriterionStatus.UNMET, refs, SUPPORT_NONE, reason)
    if manual_refs:
        reason = i18n.t("verify.reason.manual")
        status = CriterionStatus.MET
        return CriterionResult(criterion, status, refs + manual_refs, SUPPORT_MANUAL, reason)
    own = [c for c in supporting if not c.required]
    if not own:
        return _unverified(criterion, refs, "no_check")
    if not all(state is CheckState.PASSED for state in states):
        return _unverified(criterion, refs, "not_passed")
    evidence = [c for c in own if not c.trivial]
    if not evidence:
        return _unverified(criterion, refs, "trivial")
    if no_work:
        return _unverified(criterion, refs, "baseline")
    tied = any(c.tied for c in evidence)
    support = SUPPORT_TIED if tied else SUPPORT_UNTIED
    reason = i18n.t(f"verify.reason.{support}")
    return CriterionResult(criterion, CriterionStatus.MET, refs, support, reason)


def _no_work(
    checks: Sequence[Check],
    runs: Sequence[CheckRun],
    baseline_passed: Collection[str] | None,
    tree_unchanged: bool,
) -> bool:
    """A baseline exists, nothing changed since, and every passing check passed then too."""
    if baseline_passed is None or not tree_unchanged:
        return False
    by_id = {check.id: check for check in checks}
    passed = [by_id[run.check_id] for run in runs if run.state is CheckState.PASSED]
    counted = [check for check in passed if not check.required]
    return bool(counted) and all(check.command in baseline_passed for check in counted)


def _warnings(contract: TaskContract, checks: Sequence[Check], no_work: bool) -> tuple[str, ...]:
    found = []
    own = [check for check in checks if not check.required]
    if len(contract.acceptance_criteria) > 1 and own and not any(c.tied for c in own):
        found.append(i18n.t("verify.warning.untied", count=len(contract.acceptance_criteria)))
    trivial = [" ".join(check.argv) for check in own if check.trivial]
    if trivial:
        found.append(i18n.t("verify.warning.trivial", commands="; ".join(trivial)))
    if no_work:
        found.append(i18n.t("verify.warning.baseline"))
    return tuple(found)


def _summarize(criteria: Sequence[CriterionResult], unexecuted: Sequence[str]) -> str:
    if not criteria:
        return i18n.t("verify.summary.no_criteria")
    count = {s: sum(1 for c in criteria if c.status is s) for s in CriterionStatus}
    return i18n.t(
        "verify.summary",
        met=count[CriterionStatus.MET],
        total=len(criteria),
        unmet=count[CriterionStatus.UNMET],
        unverified=count[CriterionStatus.UNVERIFIED],
        unexecuted=len(unexecuted),
    )


class VerificationEngine:
    def __init__(self, executor: CommandExecutor) -> None:
        self._executor = executor

    def verify(
        self,
        contract: TaskContract,
        checks: Sequence[Check],
        cwd: str,
        mode: Mode,
        stop_on_failure: bool = True,
        manual_evidence: Sequence[Evidence] = (),
        baseline_passed: Collection[str] | None = None,
        tree_unchanged: bool = False,
    ) -> VerificationReport:
        """Run the checks and judge every criterion.

        ``baseline_passed`` lists the check commands that already passed when the task
        started (``None`` when no baseline was taken); with ``tree_unchanged`` it lets the
        engine refuse checks that passed before any work as evidence of the work.
        """
        ordered = sorted(checks, key=lambda check: check.cost)  # stable: ties keep given order
        runs: list[CheckRun] = []
        unexecuted: list[str] = []
        for check in ordered:
            if stop_on_failure and any(r.state is CheckState.FAILED for r in runs):
                unexecuted.append(check.id)
                continue
            runs.append(self._run_check(contract, check, cwd, mode))
        by_id = {run.check_id: run for run in runs}
        no_work = _no_work(ordered, runs, baseline_passed, tree_unchanged)
        criteria = tuple(
            _judge(text, ordered, by_id, manual_evidence, no_work)
            for text in contract.acceptance_criteria
        )
        return VerificationReport(
            task_id=contract.task_id,
            checks=tuple(runs),
            criteria=criteria,
            all_met=bool(criteria) and all(c.status is CriterionStatus.MET for c in criteria),
            unexecuted_checks=tuple(unexecuted),
            summary=_summarize(criteria, unexecuted),
            warnings=_warnings(contract, ordered, no_work),
            no_work=no_work,
        )

    def _run_check(self, contract: TaskContract, check: Check, cwd: str, mode: Mode) -> CheckRun:
        try:
            record = self._executor.run(
                check.argv,
                cwd,
                mode,
                contract.risk,
                timeout=check.timeout,
                task_id=contract.task_id,
                track_changes=False,
            )
        except (PermissionDenied, ApprovalRequired) as exc:
            return CheckRun(check.id, CheckState.REFUSED, None, exc.message)
        return CheckRun(check.id, _state_of(record), record, "")


def _check_evidence(run: CheckRun) -> Evidence:
    if run.record is None:
        reason = i18n.t("verify.evidence.refused", id=run.check_id, reason=run.reason)
        return Evidence("check", reason, label=EvidenceLabel.BLOCKED)
    ran = run.state in (CheckState.PASSED, CheckState.FAILED)
    label = EvidenceLabel.TESTED if ran else EvidenceLabel.UNTESTED
    if run.state is CheckState.BLOCKED:
        label = EvidenceLabel.BLOCKED
    return to_evidence(run.record, label)


def _status_for(report: VerificationReport) -> TaskStatus:
    statuses = [c.status for c in report.criteria]
    if CriterionStatus.UNMET in statuses:
        return TaskStatus.FAILED
    if report.all_met:
        return TaskStatus.VERIFIED
    ran = any(run.state in (CheckState.PASSED, CheckState.FAILED) for run in report.checks)
    if ran and CriterionStatus.MET in statuses:
        return TaskStatus.PARTIAL
    return TaskStatus.BLOCKED


def build_result(
    contract: TaskContract,
    report: VerificationReport,
    changed_files: Sequence[str],
    manual_evidence: Sequence[Evidence] = (),
) -> TaskResult:
    status = _status_for(report)
    evidence = [_check_evidence(run) for run in report.checks]
    evidence += [
        Evidence(
            "check", i18n.t("verify.evidence.not_run", id=check_id), label=EvidenceLabel.UNTESTED
        )
        for check_id in report.unexecuted_checks
    ]
    evidence += [e for e in manual_evidence if e.ref and e.label is EvidenceLabel.TESTED]
    blockers = tuple(
        i18n.t("verify.blocker", status=c.status.value, criterion=c.criterion)
        for c in report.criteria
        if c.status is not CriterionStatus.MET
    )
    return TaskResult(
        task_id=contract.task_id,
        status=status,
        summary=report.summary,
        evidence=tuple(evidence),
        changed_files=tuple(changed_files),
        blockers=blockers,
    )
