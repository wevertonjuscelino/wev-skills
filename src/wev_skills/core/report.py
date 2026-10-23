"""DELIVER: the final report. Every claim carries an evidence label; nothing is called
done without evidence, and what did not run is listed as not run."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from wev_skills import i18n
from wev_skills.core import guard_ack, progress, report_tools, steps
from wev_skills.core.contracts import EvidenceLabel, Mode, PlanTask, TaskStatus
from wev_skills.core.engine import APPROVAL_SOURCE
from wev_skills.core.task_outcomes import SELF_DECLARED
from wev_skills.core.textsafe import clean_data
from wev_skills.guards.execution import GuardVerdict
from wev_skills.review.summary import summarize
from wev_skills.state.model import RunState
from wev_skills.state.records import VerificationRecord
from wev_skills.state.review_records import all_findings
from wev_skills.verification.engine import SUPPORT_MANUAL, SUPPORT_NONE

JSON_FIELD_MAX_CHARS = 2000
"""Cut for one text field of the JSON report; recorded text is data and stays bounded."""

COMPLETE, INCOMPLETE, BLOCKED = "complete", "incomplete", "blocked"
RAN_STATES = ("passed", "failed")
REFUSED_STATES = ("refused", "blocked")
CRITERION_PREFIX = "criterion:"
NOTICES = ("checks", "data", "reviewer", "fingerprint")
WEAK_LABELS = (EvidenceLabel.MOCKED, EvidenceLabel.DOCUMENTED_ONLY, EvidenceLabel.BLOCKED)


def task_table(state: RunState) -> list[dict[str, Any]]:
    """One row per task, in plan order, for ``run status`` and ``plan show``."""
    rows = []
    for task in state.plan.tasks if state.plan else ():
        record = state.tasks[task.id]
        rows.append(
            {
                "id": task.id,
                "title": task.title,
                "status": record.status.value,
                "agent_id": record.agent_id,
                "model": record.model,
                "risk": progress.task_risk(state, task).value,
                "attempts": record.starts or len(record.attempts),
                "blocked_because": record.block_reason,
                "depends_on": list(task.depends_on),
                "files": list(task.files),
            }
        )
    return rows


def _verification(state: RunState, task_id: str) -> VerificationRecord | None:
    """The verification that speaks for the task's current attempt, if any."""
    return progress.fresh_verification(state, task_id)


def _criterion_label(criterion: str, status: str, state: RunState, task_id: str) -> str:
    if status != "unverified":
        return EvidenceLabel.TESTED.value
    record = state.tasks[task_id]
    names = {criterion, f"{CRITERION_PREFIX}{criterion}"}
    manual = record.result.evidence if record.result else ()
    labels = [e.label for e in manual if e.kind in names]
    weak = next((label for label in WEAK_LABELS if label in labels), EvidenceLabel.UNTESTED)
    return weak.value


def _support(
    known: Mapping[str, Any], name: str, by_hand: bool, lang: str | None
) -> tuple[str, str]:
    """``(support, what it means)`` for one criterion, in the report's language."""
    support = SUPPORT_MANUAL if by_hand else (known[name].support if name in known else "")
    support = support or SUPPORT_NONE
    recorded = known[name].reason if name in known and not by_hand else ""
    key = f"verify.reason.{support}"
    text = i18n.t(key, lang)
    return support, (recorded if text == key or support == SUPPORT_NONE else text)


def _criteria(state: RunState, task: PlanTask, lang: str | None) -> list[dict[str, Any]]:
    verification = _verification(state, task.id)
    record = state.tasks[task.id]
    manual = record.result.evidence if record.result else ()
    known = {c.criterion: c for c in verification.criteria} if verification else {}
    default = i18n.t("orch.contract.default_criterion", lang, objective=task.title or task.id)
    names = list(known) if known else list(task.acceptance_criteria or (default,))
    rows = []
    for name in names:
        status = known[name].status if name in known else "unverified"
        refs = list(known[name].evidence_refs) if name in known else []
        tested = [
            e.ref
            for e in manual
            if e.kind in {name, f"{CRITERION_PREFIX}{name}"}
            and e.label is EvidenceLabel.TESTED
            and e.ref
        ]
        by_hand = status != "met" and bool(tested) and record.status is TaskStatus.VERIFIED
        if by_hand:
            status, label = "met", EvidenceLabel.TESTED.value
        else:
            label = _criterion_label(name, status, state, task.id)
        support, meaning = _support(known, name, by_hand, lang)
        rows.append(
            {
                "criterion": name,
                "status": status,
                "evidence": label,
                "support": support,
                "support_note": meaning,
                "evidence_refs": [*refs, *tested],
            }
        )
    return rows


def _checks(verification: VerificationRecord | None) -> tuple[list[dict[str, Any]], list[Any]]:
    """``(checks that ran, checks that did not run)`` of one verification."""
    if verification is None:
        return [], []
    ran, skipped = [], []
    for check in verification.checks:
        row = {
            "command": " ".join(check.argv),
            "state": check.state,
            "exit_code": check.exit_code,
            "log_ref": check.log_ref,
            "tied": check.tied,
            "trivial": check.trivial,
            "required": check.required,
            "passed_at_baseline": check.baseline_passed,
        }
        if check.state in REFUSED_STATES:
            skipped.append({**row, "reason": check.reason, "evidence": EvidenceLabel.BLOCKED.value})
        else:
            tested = check.state in RAN_STATES
            label = EvidenceLabel.TESTED if tested else EvidenceLabel.UNTESTED
            ran.append({**row, "evidence": label.value})
    skipped.extend(
        {
            "command": command,
            "state": "not_run",
            "reason": "",
            "evidence": EvidenceLabel.UNTESTED.value,
        }
        for command in verification.unexecuted_checks
    )
    return ran, skipped


def _task_label(state: RunState, task_id: str, criteria: Sequence[Mapping[str, Any]]) -> str:
    status = state.tasks[task_id].status
    if status is TaskStatus.BLOCKED:
        return EvidenceLabel.BLOCKED.value
    proven = bool(criteria) and all(c["status"] == "met" for c in criteria)
    if status is TaskStatus.VERIFIED and proven:
        return EvidenceLabel.TESTED.value
    return EvidenceLabel.UNTESTED.value


def _reviews(state: RunState, task_id: str) -> list[dict[str, Any]]:
    """Reviews of a task; who reviewed is whatever the caller said, and is labeled so."""
    found = [r.to_dict() for r in state.reviews if r.task_id == task_id]
    return [{**review, "reviewer_identity": SELF_DECLARED} for review in found]


def _work_note(state: RunState, task: PlanTask, lang: str | None, changed: bool = False) -> str:
    record = state.tasks[task.id]
    if record.status is not TaskStatus.VERIFIED:
        return ""
    if changed:
        return i18n.t("orch.report.note.changed", lang)
    if task.read_only:
        return i18n.t("orch.report.note.read_only", lang)
    if progress.lacks_work(state, task):
        return i18n.t("orch.report.note.no_change", lang)
    return ""


def _task(
    state: RunState, task: PlanTask, lang: str | None, changed: bool = False
) -> dict[str, Any]:
    record = state.tasks[task.id]
    verification = _verification(state, task.id)
    criteria = _criteria(state, task, lang)
    ran, skipped = _checks(verification)
    return {
        "id": task.id,
        "title": task.title,
        "status": record.status.value,
        "evidence": _task_label(state, task.id, criteria),
        "agent_id": record.agent_id,
        "model": record.model,
        "risk": progress.task_risk(state, task).value,
        "attempts": record.starts or len(record.attempts),
        "blocked_because": record.block_reason,
        "read_only": task.read_only,
        "tree_changed": record.tree_changed,
        "verified_then_changed": changed,
        "work_note": _work_note(state, task, lang, changed),
        "baseline": verification.baseline if verification else "",
        "warnings": list(verification.warnings) if verification else [],
        "summary": record.result.summary if record.result else "",
        "criteria": criteria,
        "checks_run": ran,
        "checks_not_run": skipped,
        "review": {
            "required": progress.review_required(state),
            "accepted": progress.review_accepted(state, task.id),
            "reviews": _reviews(state, task.id),
        },
        "changed_files": list(record.result.changed_files) if record.result else [],
        "blockers": list(record.result.blockers) if record.result else [],
        "tool_selection": report_tools.section(record, lang),
    }


def guard_history(state: RunState) -> list[dict[str, Any]]:
    """Every guard verdict recorded for the run, settled tasks and acknowledgements included."""
    return [trip.to_dict() for trip in state.guard_trips]


def _acknowledgements(state: RunState) -> list[dict[str, Any]]:
    found = [d for d in state.decisions if d.source == guard_ack.SOURCE]
    return [{"at": d.at, "decision": d.decision, "reasons": list(d.reasons)} for d in found]


def _reasons(
    state: RunState, verdict: GuardVerdict, lang: str | None, changed: Sequence[str] = ()
) -> list[str]:
    reasons = [i18n.t("orch.report.reason.changed", lang, task=task_id) for task_id in changed]
    tasks = state.plan.tasks if state.plan else ()
    if state.mode is Mode.PLAN:
        reasons.append(i18n.t("orch.report.reason.plan_mode", lang))
    if not tasks:
        reasons.append(i18n.t("orch.report.reason.no_tasks", lang))
    for task in tasks:
        status = state.tasks[task.id].status
        if status is not TaskStatus.VERIFIED:
            reasons.append(
                i18n.t("orch.report.reason.task", lang, task=task.id, status=status.value)
            )
        elif not progress.task_complete(state, task.id):
            reasons.append(i18n.t("orch.report.reason.review", lang, task=task.id))
        if progress.exhausted(state, task.id):
            reasons.append(i18n.t("orch.report.reason.exhausted", lang, task=task.id))
        if progress.lacks_work(state, task):
            reasons.append(i18n.t("orch.report.reason.no_change", lang, task=task.id))
    reasons.extend(i18n.t("orch.report.reason.blocker", lang, text=b) for b in state.blockers)
    reasons.extend(
        i18n.t("orch.report.reason.approval", lang, id=note.id)
        for note in progress.live_approvals(state)
    )
    if verdict.action in progress.BLOCKING_ACTIONS:
        reasons.append(
            i18n.t("orch.report.reason.guard", lang, action=verdict.action.value, rule=verdict.rule)
        )
    return reasons


def overall_status(state: RunState, verdict: GuardVerdict, changed: Sequence[str] = ()) -> str:
    """``changed``: tasks verified on a tree that changed afterwards; with any, the run is
    not complete until their checks pass again."""
    if progress.run_complete(state) and not changed:
        return COMPLETE
    blocked_task = any(r.status is TaskStatus.BLOCKED for r in state.tasks.values())
    held = bool(state.blockers or progress.live_approvals(state))
    if blocked_task or held or verdict.action in progress.BLOCKING_ACTIONS:
        return BLOCKED
    return INCOMPLETE


def _approvals(state: RunState, approvals: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every approval this run asked for, with how it ended: granted, denied or pending."""
    asked = {d.reasons[0] for d in state.decisions if d.source == APPROVAL_SOURCE and d.reasons}
    wanted = asked | set(state.pending_approvals) | {note.id for note in state.approval_notes}
    notes = {note.id: note for note in state.approval_notes}
    stale = {note.id for note in progress.stale_approvals(state)}
    fields = ("id", "action", "risk", "status", "requested_by", "decided_by", "uses")
    rows = []
    for item in approvals:
        if item.get("id") not in wanted:
            continue
        note = notes.get(str(item.get("id")))
        row = {key: item.get(key) for key in fields}
        rows.append({**row, "task_id": note.task_id if note else "", "stale": row["id"] in stale})
    return rows


def _review(state: RunState, lang: str | None) -> dict[str, Any]:
    """The review rounds in one block: the open and the dismissed findings, as lists."""
    found = all_findings(state.review_rounds)
    skipped = state.review_rounds[-1].skipped if state.review_rounds else 0
    keys = ("id", "tag", "file", "line", "title")
    live = [{k: getattr(f, k) for k in keys} for f in found if f.status == "open"]
    dismissed = [
        {"id": f.id, "tag": f.tag, "outcome": f.outcome, "reason": f.reason}
        for f in found
        if f.status == "dismissed"
    ]
    summary = summarize(found, skipped, i18n.resolve_language(lang))
    return {"summary": summary, "skipped": skipped, "open": live, "dismissed": dismissed}


def build_report(
    state: RunState,
    approvals: Sequence[Mapping[str, Any]],
    verdict: GuardVerdict,
    lang: str | None = None,
    changed: Sequence[str] = (),
) -> dict[str, Any]:
    """The delivery report. Recorded text is cleaned of control characters and escapes.

    ``changed`` lists the tasks that are "verified, then changed": the caller compares the
    tree with the last verified record when the report is asked for, not continuously.
    """
    plan_tasks = state.plan.tasks if state.plan else ()
    tasks = [_task(state, task, lang, task.id in changed) for task in plan_tasks]
    status = overall_status(state, verdict, changed)
    files = sorted({path for task in tasks for path in task["changed_files"]})
    built = {
        "run_id": state.run_id,
        "objective": state.objective,
        "mode": state.mode.value,
        "phase": state.phase.value,
        "status": status,
        "reasons": [] if status == COMPLETE else _reasons(state, verdict, lang, changed),
        "classification": state.classification.to_dict() if state.classification else None,
        "strategy": state.strategy.to_dict() if state.strategy else None,
        "config": {"source": state.config_source, "digest": state.config_digest},
        "tasks": tasks,
        "approvals": _approvals(state, approvals),
        "pending_approvals": [note.id for note in progress.live_approvals(state)],
        "stale_approvals": [note.id for note in progress.stale_approvals(state)],
        "blockers": list(state.blockers),
        "guard": {
            "verdict": verdict.to_dict(),
            "trips": guard_history(state),
            "acknowledgements": _acknowledgements(state),
        },
        "changed_files": files,
        "risk_notes": state.plan.risk_notes if state.plan else "",
        "revert": state.plan.revert if state.plan else "",
        "review": _review(state, lang),
        "plan_amendments": [item.to_dict() for item in state.plan_amendments],
        "notices": [i18n.t(f"orch.notice.{name}", lang) for name in NOTICES],
    }
    cleaned: dict[str, Any] = clean_data(built, JSON_FIELD_MAX_CHARS)
    return {**cleaned, "next_step": steps.next_step(state)}
