import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.fixtures.fake_agent import FakeAgent
from tests.unit.test_review_vote import found, item, vote, votes
from tests.unit.test_scoring import git, lesson
from wev_skills.agents import project
from wev_skills.config import Config
from wev_skills.config_review import ReviewConfig
from wev_skills.core import wiring
from wev_skills.core.contracts import AgentRunResult, Mode
from wev_skills.core.errors import GuardTripped, StateConflict, ValidationError
from wev_skills.core.ports import READ_ONLY_TOOLS, SubprocessRunner
from wev_skills.evaluation.compare import compare_reviewer
from wev_skills.evaluation.scoring import SCORES_FILE, planned_runs, score_specialist
from wev_skills.governance.audit import AuditLog
from wev_skills.review.gate import finish_refusal, read_comparisons
from wev_skills.state.model import RunState
from wev_skills.state.review_records import ReviewRoundRecord

AGENT = "spec1"
REVIEWER_PATH = f"wev-specialists/{AGENT}.json"
SHARP = "SHARP"


class SpecAgent(FakeAgent):
    """Finds one bug on line 21; a verifier confirms it only for a spec whose text says SHARP."""

    def run_agent(self, workspace, spec, objective, timeout, tools=()):  # type: ignore[no-untyped-def]
        self.runs += 1
        if '"votes"' in objective:
            return AgentRunResult(True, votes(vote(0, real=SHARP in str(spec.instructions))))
        return AgentRunResult(True, found(item(21)))


class ReviewScoreCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.root = tmp / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")
        lines = [f"line {n}\n" for n in range(1, 21)]
        (self.root / "a.py").write_text("".join(lines))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")
        base = git(self.root, "rev-parse", "HEAD")
        lines.append("line 21 is broken\n")  # past the end of the file at base
        (self.root / "a.py").write_text("".join(lines))
        git(self.root, "commit", "-qam", "head")
        head = git(self.root, "rev-parse", "HEAD")
        diff = git(self.root, "diff", "--unified=0", "--no-renames", base, head) + "\n"
        folder = self.root / "evals" / "cases"
        (folder / "r1").mkdir(parents=True)
        (folder / "r1" / "change.diff").write_text(diff)
        data = {
            "id": "r1", "title": "r1", "source": "review", "ref": "r", "agents": [],
            "base_commit": base, "objective": "find the bug", "kind": "review",
            "head_commit": head, "expect": [{"file": "a.py", "first": 21, "last": 21}],
        }  # fmt: skip
        (folder / "r1.json").write_text(json.dumps(data))
        base_config = Config()
        self.config = replace(
            base_config,
            specialists=replace(base_config.specialists, score_samples=1),
            review=ReviewConfig(agent=AGENT, depth="quick"),
        )
        project.create(self.root, self.config, AGENT, "senior-engineer", ())
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "cases and reviewer")
        self.rev = git(self.root, "rev-parse", "HEAD")
        self.audit = AuditLog(tmp / "audit.jsonl")

    def score(self, agent: FakeAgent):  # type: ignore[no-untyped-def]
        return score_specialist(
            self.root, self.config, SubprocessRunner(), agent, AGENT, self.audit
        )

    def compare(self, agent: FakeAgent, rev: str | None = None):  # type: ignore[no-untyped-def]
        return compare_reviewer(
            self.root, self.config, SubprocessRunner(), agent, AGENT, rev or self.rev, self.audit
        )

    def sharpen(self) -> None:
        path = self.root / REVIEWER_PATH
        data = json.loads(path.read_text())
        data["instructions"] = f"{data['instructions']} {SHARP}"
        path.write_text(json.dumps(data))

    def history(self) -> list[dict[str, object]]:
        return read_comparisons(wiring.state_dir(self.config, self.root) / SCORES_FILE)


class ScoreReviewCaseTest(ReviewScoreCase):
    def test_review_case_scored_with_fake_votes(self) -> None:
        self.sharpen()
        agent = SpecAgent()
        report = self.score(agent)
        self.assertEqual((report.baseline, report.runs_used, agent.runs), ({"r1": 1}, 2, 2))

    def test_review_case_fails_when_verifier_rejects(self) -> None:
        agent = SpecAgent()
        self.assertEqual(self.score(agent).baseline, {"r1": 0})

    def test_finders_get_read_only_tools(self) -> None:
        agent = FakeAgent(finder_replies=[found(item(21))], verifier_replies=[votes(vote(0))])
        self.assertEqual(self.score(agent).baseline, {"r1": 1})
        self.assertEqual(set(agent.tools), {tuple(READ_ONLY_TOOLS)})

    def test_incomplete_review_is_a_fail_that_charges_its_runs(self) -> None:
        dead = AgentRunResult(False, "boom")
        agent = FakeAgent(finder_replies=[dead])
        report = self.score(agent)
        # the one finder run, plus the lesson request the failed case then triggers
        self.assertEqual((report.baseline, report.runs_used), ({"r1": 0}, 2))

    def test_runs_per_sample_in_plan_and_cap(self) -> None:
        self.assertEqual(planned_runs(2, 0, 0, 3, 0, runs_per_sample=2), 12)
        self.assertEqual(planned_runs(2, 0, 0, 3, 0), 6)
        self.config = replace(
            self.config, specialists=replace(self.config.specialists, score_max_runs=1)
        )
        agent = SpecAgent()
        with self.assertRaises(GuardTripped) as caught:
            self.score(agent)
        self.assertEqual((caught.exception.details["planned"], agent.runs), (2, 0))

    def test_review_samples_count_against_the_budget_of_lesson_variants(self) -> None:
        item = lesson("do x")
        spec = project.list_specs(self.root, self.config)[0]
        project._write(self.root, self.config, replace(spec, experience=(item,)))
        self.config = replace(
            self.config, specialists=replace(self.config.specialists, score_max_runs=3)
        )
        report = self.score(SpecAgent())  # baseline 2 runs; a variant would need 2 more
        self.assertIn(item.id, report.deferred)

    def test_depth_recorded(self) -> None:
        report = self.score(SpecAgent())
        self.assertEqual(report.depth, "quick")
        stored = (wiring.state_dir(self.config, self.root) / SCORES_FILE).read_text()
        self.assertEqual(json.loads(stored.splitlines()[-1])["depth"], "quick")

    def test_depth_off_refuses_review_cases(self) -> None:
        self.config = replace(self.config, review=ReviewConfig(agent=AGENT, depth="off"))
        agent = SpecAgent()
        with self.assertRaises(ValidationError) as caught:
            self.score(agent)
        self.assertEqual((caught.exception.code, agent.runs), ("score_review_off", 0))


class CompareReviewerTest(ReviewScoreCase):
    def gate(self, report) -> object:  # type: ignore[no-untyped-def]
        """What ``run finish`` says about a changed reviewer, given the scores file."""
        record = ReviewRoundRecord(1, "now", "full", "t", report.fingerprint, "quick")
        state = RunState("run-1", "goal", Mode.EXECUTE, "now", "now", review_rounds=(record,))
        return finish_refusal(
            state, self.config, report.fingerprint, {REVIEWER_PATH}, self.history()
        )

    def test_compare_records_improves_true_and_gate_accepts(self) -> None:
        self.sharpen()
        report = self.compare(SpecAgent())
        self.assertEqual(
            (report.baseline, report.current, report.improves), ({"r1": 0}, {"r1": 1}, True)
        )
        self.assertEqual(self.history()[0]["compare"], self.rev)
        self.assertEqual(self.history()[0]["depth"], "quick")
        self.assertIsNone(self.gate(report))

    def test_compare_records_improves_false_and_gate_refuses(self) -> None:
        self.sharpen()
        git(self.root, "commit", "-qam", "sharp")
        sharp_rev = git(self.root, "rev-parse", "HEAD")
        git(self.root, "checkout", "-q", self.rev, "--", REVIEWER_PATH)  # working tree: dull
        report = self.compare(SpecAgent(), sharp_rev)
        self.assertEqual(
            (report.baseline, report.current, report.improves), ({"r1": 1}, {"r1": 0}, False)
        )
        refusal = self.gate(report)
        self.assertEqual(getattr(refusal, "code", None), "reviewer_unscored")

    def test_compare_refuses_dirty_cases(self) -> None:
        (self.root / "evals" / "cases" / "r1" / "change.diff").write_text("x")
        agent = SpecAgent()
        with self.assertRaises(StateConflict) as caught:
            self.compare(agent)
        self.assertEqual((caught.exception.code, agent.runs), ("cases_uncommitted", 0))

    def test_compare_refuses_what_is_not_a_commit(self) -> None:
        agent = SpecAgent()
        for rev in ("--output=x", "no-such-rev", "HEAD:evals"):
            with self.assertRaises(ValidationError) as caught:
                self.compare(agent, rev)
            self.assertEqual(caught.exception.code, "compare_bad_rev")
        self.assertEqual(agent.runs, 0)

    def test_missing_review_md_at_rev_is_the_default_guide(self) -> None:
        self.sharpen()
        self.assertEqual(self.compare(SpecAgent()).baseline, {"r1": 0})


if __name__ == "__main__":
    unittest.main()
