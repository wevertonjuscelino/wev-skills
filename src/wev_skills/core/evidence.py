"""What ``verified`` requires: evidence for every criterion, real files, an unchanged tree.

The engine does not take an agent's word for success. ``verified`` needs a passing
verification made after the task last started, on the tree as it still is, or evidence the
agent supplies by hand. A manual reference must be a real file in one of three places: the
run's log directory (what ``wev exec`` and the checks wrote), the run's evidence directory,
or the files the task lists in the plan. Any other existing file (a Makefile, another
task's source) says nothing about the task and is refused. Manual evidence is the agent's
claim and the report labels it so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from wev_skills import i18n
from wev_skills.core import progress
from wev_skills.core.contracts import Evidence, EvidenceLabel, TaskContract
from wev_skills.core.engine import Engine
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.security.paths import resolve_within
from wev_skills.state.model import RunState

CRITERION_PREFIX = "criterion:"
EVIDENCE_DIR = "evidence"
"""A directory of the run, next to its logs, for files a person puts there as evidence."""
MET = "met"


def manual_refs(criterion: str, evidence: Sequence[Evidence]) -> tuple[str, ...]:
    """Refs of manual evidence for ``criterion``: it must be labeled TESTED and carry a ref."""
    names = {criterion, f"{CRITERION_PREFIX}{criterion}"}
    return tuple(
        e.ref for e in evidence if e.kind in names and e.label is EvidenceLabel.TESTED and e.ref
    )


def _existing_file(root: Path, ref: str) -> bool:
    """``ref`` names a regular file inside ``root``, symlinks and ``..`` resolved."""
    try:
        return resolve_within(root, ref).is_file()
    except PermissionDenied, OSError, ValueError:
        return False


def _inside(directory: Path, root: Path, ref: str) -> bool:
    """``ref`` (relative to ``root``) resolves into ``directory``: the engine's own records."""
    try:
        resolve_within(directory, (root / ref).resolve())
    except PermissionDenied, OSError, ValueError:
        return False
    return True


def _listed(repository: Path, files: Sequence[str], ref: str) -> bool:
    """``ref`` is an existing file that is, or lies inside, one of the task's ``files``."""
    if not _existing_file(repository, ref):
        return False
    target = resolve_within(repository, ref)
    for listed in files:
        try:
            base = resolve_within(repository, listed)
        except PermissionDenied:
            continue
        if target == base or base in target.parents:
            return True
    return False


def checked_evidence(
    engine: Engine, state: RunState, evidence: Sequence[Evidence], task_id: str = ""
) -> tuple[Evidence, ...]:
    """Redacted manual evidence; a ref outside the run's log or evidence directory and the
    task's own files is refused. The rest of the state directory (approvals, audit log,
    other runs) is not evidence of anything and is refused too."""
    repository, logs = Path(engine.cwd(state)), engine.log_dir()
    records = engine.store.run_dir / EVIDENCE_DIR
    state_dir = engine.services.state_dir
    files = progress.plan_task(state, task_id).files if task_id else ()
    cleaned = []
    for item in evidence:
        ref = item.ref
        ours = bool(ref) and (_existing_file(logs, ref) or _existing_file(records, ref))
        listed = (
            bool(ref)
            and _listed(repository, files, ref)
            and not _inside(state_dir, repository, ref)
        )
        if ref and not (ours or listed):
            shown = engine.clean(", ".join(files)) or i18n.t("orch.error.evidence_no_files")
            message = i18n.t(
                "orch.error.evidence_ref",
                ref=engine.clean(ref),
                logs=str(logs),
                evidence=str(records),
                files=shown,
            )
            raise ValidationError("invalid_evidence_ref", message, {"ref": engine.clean(ref)})
        cleaned.append(replace(item, summary=engine.clean(item.summary), ref=engine.clean(ref)))
    return tuple(cleaned)


def open_criteria(state: RunState, contract: TaskContract) -> tuple[str, ...]:
    """Criteria the latest fresh verification did not show as met (all, when there is none)."""
    fresh = progress.fresh_verification(state, contract.task_id)
    if fresh is not None and fresh.all_met:
        return ()
    statuses = {c.criterion: c.status for c in fresh.criteria} if fresh else {}
    return tuple(c for c in contract.acceptance_criteria if statuses.get(c) != MET)


def require_evidence(state: RunState, contract: TaskContract, manual: Sequence[Evidence]) -> None:
    """Every criterion is met by a fresh verification or by manual evidence, or it is refused."""
    missing = [c for c in open_criteria(state, contract) if not manual_refs(c, manual)]
    if not missing:
        return
    step = f"wev task check {contract.task_id} --run {state.run_id}"
    message = i18n.t("orch.error.unverified", task=contract.task_id, count=len(missing))
    raise ValidationError("verification_required", message, {"missing": missing, "next_step": step})


def require_same_tree(state: RunState, task_id: str, fingerprint: str) -> None:
    """The tree must be what the passing verification saw; otherwise check again."""
    fresh = progress.fresh_verification(state, task_id)
    if fresh is None or not fresh.fingerprint or fresh.fingerprint == fingerprint:
        return
    step = f"wev task check {task_id} --run {state.run_id}"
    message = i18n.t("orch.error.tree_changed", task=task_id, step=step)
    raise ValidationError("tree_changed", message, {"task_id": task_id, "next_step": step})
