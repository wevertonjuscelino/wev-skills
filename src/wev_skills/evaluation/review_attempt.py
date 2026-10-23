"""One sample of a review case: the finders and verifiers of a review round on a stored diff."""

from __future__ import annotations

from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import LimitsConfig
from wev_skills.core.errors import ProviderError
from wev_skills.core.textsafe import clean_text
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.evaluation.cases import CASES_DIR, Case
from wev_skills.evaluation.review_cases import DIFF_NAME, review_case_passed
from wev_skills.evaluation.score_runs import CONTEXT_CHARS, Failure, Setup, case_runs
from wev_skills.evaluation.workspace import case_workspace, skip_git_cleanup
from wev_skills.review.trees import touched_lines
from wev_skills.review.vote import VoteInputs, find_and_vote
from wev_skills.state.review_records import FindingRecord

INCOMPLETE_CODES = frozenset({"review_incomplete", "review_agent_failed"})
FIRST_ROUND = 1


def _summary(kept: tuple[FindingRecord, ...], lang: str) -> str:
    if not kept:
        return i18n.t("evaluation.scoring.review_no_findings", lang)
    lines = (f"[{f.tag}] {f.file}:{f.line} {clean_text(f.title, 120)}" for f in kept)
    return "\n".join(lines)[:CONTEXT_CHARS]


def review_sample(setup: Setup, spec: AgentSpec, case: Case) -> tuple[bool, Failure | None, int]:
    """Run one review of ``case`` at its ``head_commit``; a review that cannot finish is a fail
    that still costs the runs it used."""
    diff = (setup.root / CASES_DIR / case.id / DIFF_NAME).read_text(encoding="utf-8")
    decide = LocalPolicyProvider(
        LimitsConfig()
    ).resolve_conflict  # only the vote rule is used: limits do not matter
    with case_workspace(setup.runner, setup.root, case, setup.scratch, case.head_commit) as path:
        try:
            inputs = VoteInputs(
                path, setup.agent, spec, diff, touched_lines(diff), case.objective, setup.guide,
                "", (), (), setup.shape, setup.timeout, FIRST_ROUND, decide, setup.lang,
            )  # fmt: skip
            try:
                result = find_and_vote(inputs)
            except ProviderError as exc:
                if exc.code not in INCOMPLETE_CODES:
                    raise
                used = int(exc.details.get("runs_used", case_runs(setup, case)))
                return False, Failure(case, str(exc), diff[:CONTEXT_CHARS]), used
            finally:
                setup.guard()  # the agents ran in the workspace
            if review_case_passed(case, result.kept):
                return True, None, result.runs_used
            failure = Failure(case, _summary(result.kept, setup.lang), diff[:CONTEXT_CHARS])
            return False, failure, result.runs_used
        except BaseException as exc:  # the agent may have planted git state: no git call
            skip_git_cleanup(exc)
            raise
