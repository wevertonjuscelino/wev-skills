"""Compare the reviewer as committed at a revision with the one in the working tree."""

from __future__ import annotations

import json
import posixpath
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec, validate_data
from wev_skills.config import Config
from wev_skills.core import fsutil, wiring
from wev_skills.core._codec import Serializable
from wev_skills.core.engine import excluded_paths
from wev_skills.core.errors import GuardTripped, NotFound, StateConflict, ValidationError
from wev_skills.core.fingerprint import tree_fingerprint
from wev_skills.core.fsutil import append_line
from wev_skills.core.ports import AgentRunner, Runner
from wev_skills.evaluation import cases as case_store
from wev_skills.evaluation.cases import REVIEW_KIND
from wev_skills.evaluation.gitguard import tamper_guard
from wev_skills.evaluation.ratchet import improves, not_lower
from wev_skills.evaluation.score_runs import run_configuration
from wev_skills.evaluation.scoring import SCORES_FILE, load_spec, review_parts, scratch_setup
from wev_skills.evaluation.workspace import run_git
from wev_skills.governance.audit import AuditLog
from wev_skills.review.guide import FILE_NAME, MAX_CHARS, ReviewGuide, parse_guide
from wev_skills.review.trees import write_tree
from wev_skills.state.model import iso_utc

COMMIT_ID = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


@dataclass(frozen=True)
class CompareReport(Serializable):
    compare: str
    fingerprint: str
    tree: str
    depth: str
    baseline: dict[str, int]
    current: dict[str, int]
    improves: bool
    not_lower: bool
    runs_used: int


def _git_text(runner: Runner, root: Path, *args: str) -> str | None:
    """Standard output of a git call, None when git says no; a timeout refuses."""
    done = run_git(runner, root, *args)
    if done.timed_out:
        raise StateConflict("compare_git_timeout", i18n.t("evaluation.compare.git_timeout"))
    return done.stdout if done.exit_code == 0 else None


def resolve_rev(runner: Runner, root: Path, rev: str) -> str:
    """The commit id ``rev`` names; anything that is not a commit is refused."""
    found = _git_text(
        runner, root, "rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"
    )
    sha = (found or "").strip()
    if not COMMIT_ID.fullmatch(sha):
        raise ValidationError("compare_bad_rev", i18n.t("evaluation.compare.bad_rev", rev=rev))
    return sha


def _spec_at(runner: Runner, root: Path, config: Config, sha: str, agent_id: str) -> AgentSpec:
    path = posixpath.normpath(f"{config.agents.project_dir}/{agent_id}.json")
    text = _git_text(runner, root, "show", "--end-of-options", f"{sha}:{path}")
    if text is None:
        raise NotFound("compare_spec_missing", i18n.t("evaluation.compare.spec_missing", path=path))
    try:
        data = json.loads(text)
        errors = validate_data(data)
    except ValueError as exc:
        raise ValidationError("compare_bad_spec", str(exc)) from exc
    if errors:
        raise ValidationError("compare_bad_spec", "; ".join(errors))
    return AgentSpec.from_dict(data)


def _guide_at(runner: Runner, root: Path, sha: str) -> ReviewGuide:
    """``REVIEW.md`` at ``sha``; none there means the default guide."""
    text = _git_text(runner, root, "show", "--end-of-options", f"{sha}:{FILE_NAME}")
    return ReviewGuide() if text is None else parse_guide(text[:MAX_CHARS])


def compare_reviewer(
    root: Path,
    config: Config,
    runner: Runner,
    agent: AgentRunner,
    agent_id: str,
    rev: str,
    audit: AuditLog,
) -> CompareReport:
    """Score the reviewer spec and ``REVIEW.md`` of ``rev`` and of the working tree on the same
    review cases, then record the comparison. No lesson is decided."""
    if agent_id != config.review.agent:
        message = i18n.t("evaluation.compare.not_reviewer", agent=agent_id)
        raise ValidationError("compare_not_reviewer", message)
    case_store.ensure_committed(runner, root)
    digest = case_store.case_set_digest(root)
    cases = tuple(
        c for c in case_store.cases_for(case_store.load_cases(root), agent_id)
        if c.kind == REVIEW_KIND
    )  # fmt: skip
    if not cases:
        raise ValidationError("compare_no_cases", i18n.t("evaluation.compare.no_cases"))
    shape, current_guide = review_parts(root, config, cases)
    sha = resolve_rev(runner, root, rev)
    old_spec, old_guide = (
        _spec_at(runner, root, config, sha, agent_id),
        _guide_at(runner, root, sha),
    )
    needed = 2 * config.specialists.score_samples * len(cases) * (shape.finders + shape.verifiers)
    if needed > config.specialists.score_max_runs:
        cap = config.specialists.score_max_runs
        message = i18n.t("evaluation.scoring.over_cap", planned=needed, cap=cap)
        raise GuardTripped("score_over_cap", message, {"planned": needed, "cap": cap})
    factory = wiring.build_agents(config, root).factory
    new_spec = load_spec(root, config, agent_id)
    guard = tamper_guard(runner, root)
    with scratch_setup(root, config, runner, agent, guard, (shape, old_guide)) as setup:
        before = run_configuration(setup, factory.resolve(old_spec), cases)
        after = run_configuration(
            replace(setup, guide=current_guide), factory.resolve(new_spec), cases
        )
    guard()
    if case_store.case_set_digest(root) != digest:
        raise StateConflict("cases_changed", i18n.t("evaluation.scoring.cases_changed"))
    # ignored before the tree is written, so the scores line appended below leaves it unchanged
    state = fsutil.ensure_ignored_dir(wiring.state_dir(config, root))
    fingerprint = tree_fingerprint(runner, str(root), excluded_paths(str(root), state))
    report = CompareReport(
        sha, fingerprint, write_tree(runner, root), config.review.depth, before.passes,
        after.passes, improves(before.passes, after.passes),
        not_lower(before.passes, after.passes), before.runs + after.runs,
    )  # fmt: skip
    audit.append("specialists.compare", {"specialist": agent_id, "rev": rev, "sha": sha})
    line = {**report.to_dict(), "agent": agent_id, "at": iso_utc(time.time())}
    append_line(state / SCORES_FILE, json.dumps(line, ensure_ascii=False))
    return report
