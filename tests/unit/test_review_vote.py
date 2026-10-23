import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.fixtures.fake_agent import FakeAgent
from tests.unit._agent_helpers import make
from wev_skills.config import LimitsConfig
from wev_skills.config_review import ReviewShape
from wev_skills.core.contracts import AgentRunResult
from wev_skills.core.errors import ProviderError, StateConflict
from wev_skills.core.ports import READ_ONLY_TOOLS
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.review.findings import finding_id
from wev_skills.review.guide import ReviewGuide
from wev_skills.review.vote import VoteInputs, find_and_vote
from wev_skills.state.review_records import FindingRecord

TOUCHED = {"a.py": frozenset({5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15})}


def item(line: int = 5, title: str = "Off by one", file: str = "a.py", tag: str = "important"):
    return {"file": file, "line": line, "title": title, "body": "It is wrong.", "tag": tag,
            "class_wide": False}  # fmt: skip


def found(*items: dict[str, object]) -> str:
    return json.dumps({"findings": list(items)})


def vote(index: int, real: bool = True, kind: str = "bug", tag: str = "important"):
    return {"index": index, "real": real, "tag": tag, "kind": kind}


def votes(*items: dict[str, object]) -> str:
    return json.dumps({"votes": list(items)})


def posted(file: str, line: int, title: str) -> FindingRecord:
    return FindingRecord(
        finding_id(file, line, title), 1, file, line, title, "b", "important", False, 2, 3
    )


class VoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("a.py", "b.py", "skipme.py"):
            (self.root / name).write_text("x = 1\n" * 30)
        self.policy = LocalPolicyProvider(LimitsConfig())

    def inputs(self, agent: FakeAgent, shape: ReviewShape, **over: object) -> VoteInputs:
        base = VoteInputs(
            root=self.root, agent=agent, spec=make("rev"), diff="d", run_touched=TOUCHED,
            intent="i", guide=ReviewGuide(), claude_md="", posted=(), rechecks=(), shape=shape,
            timeout=5.0, round=2, decide=self.policy.resolve_conflict, lang="en",
        )  # fmt: skip
        return replace(base, **over)

    def test_quorum_keeps_and_drops(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item(5, "kept"), item(20, "dropped"))],
            verifier_replies=[votes(vote(0), vote(1)), votes(vote(0), vote(1, False)),
                              votes(vote(0, False), vote(1, False))],
        )  # fmt: skip
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 3, 2)))
        self.assertEqual([r.title for r in result.kept], ["kept"])
        record = result.kept[0]
        self.assertEqual((record.votes_real, record.votes_total, record.round), (2, 3, 2))
        self.assertEqual(record.id, finding_id("a.py", 5, "kept"))
        self.assertEqual(result.runs_used, 4)
        self.assertTrue(all(t == READ_ONLY_TOOLS for t in agent.tools))

    def test_fewer_answering_verifiers_than_quorum_is_incomplete(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item())],
            verifier_replies=[votes(vote(0)), AgentRunResult(False, "")],
        )
        with self.assertRaises(ProviderError) as caught:
            find_and_vote(self.inputs(agent, ReviewShape(1, 2, 2)))
        self.assertEqual(caught.exception.code, "review_incomplete")
        self.assertEqual(caught.exception.details["runs_used"], 3)

    def test_all_verifiers_failing_is_incomplete(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item())], verifier_replies=[AgentRunResult(False, "")]
        )
        with self.assertRaises(ProviderError) as caught:
            find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1)))
        self.assertEqual(caught.exception.code, "review_incomplete")

    def test_recheck_offset_follows_the_candidates(self) -> None:
        gone, stays = posted("a.py", 5, "gone"), posted("a.py", 10, "stays")
        agent = FakeAgent(
            finder_replies=[found(item(15, "new"))],
            verifier_replies=[votes(vote(0), vote(1, False), vote(2))],
        )
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1), rechecks=(gone, stays)))
        self.assertEqual(result.fixed, (gone.id,))
        self.assertEqual([r.title for r in result.kept], ["new"])

    def test_style_votes_drop_a_finding(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item())], verifier_replies=[votes(vote(0, kind="style"))]
        )
        self.assertEqual(find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1))).kept, ())

    def test_pre_existing_from_run_diff_not_round_diff(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item(5, "touched"), item(25, "old"))],
            verifier_replies=[votes(vote(0), vote(1))],
        )
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1)))
        self.assertEqual([r.tag for r in result.kept], ["important", "pre_existing"])

    def test_most_accepting_votes_decide_important_or_nit(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item())],
            verifier_replies=[votes(vote(0, tag="nit")), votes(vote(0, tag="nit")),
                              votes(vote(0))],
        )  # fmt: skip
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 3, 2)))
        self.assertEqual(result.kept[0].tag, "nit")

    def test_nit_cap_keeps_most_voted(self) -> None:
        titles = ("one", "two", "three")
        agent = FakeAgent(
            finder_replies=[found(*(item(5 + 5 * i, t, tag="nit") for i, t in enumerate(titles)))],
            verifier_replies=[
                votes(*(vote(i, tag="nit") for i in range(3))),
                votes(vote(1, tag="nit"), vote(2, tag="nit")),
            ],
        )
        guide = ReviewGuide(nit_cap=1)
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 2, 1), guide=guide))
        self.assertEqual([r.title for r in result.kept], ["two"])

    def test_duplicates_merged(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item(5, "first"), item(8, "near"), item(9, "far"))],
            verifier_replies=[votes(vote(0), vote(1))],
        )
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1)))
        self.assertEqual([r.title for r in result.kept], ["first", "far"])

    def test_posted_ids_not_repeated(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item(5, "seen"), item(10, "new"))],
            verifier_replies=[votes(vote(0))],
        )
        old = posted("a.py", 5, "seen")
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1), posted=(old,)))
        self.assertEqual([r.title for r in result.kept], ["new"])

    def test_unproven_findings_are_dropped(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item(99, "nowhere"), item(5, "nofile", file="zz.py"))]
        )
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1)))
        self.assertEqual((result.kept, result.runs_used, agent.runs), ((), 1, 1))

    def test_skipped_counted(self) -> None:
        agent = FakeAgent(
            finder_replies=[
                found(item(5, "gen", file="skipme.py"), item(5, "gen", file="skipme.py"), item(5))
            ],
            verifier_replies=[votes(vote(0))],
        )
        guide = ReviewGuide(skip=("skip*.py",))
        result = find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1), guide=guide))
        self.assertEqual((result.skipped, len(result.kept)), (1, 1))

    def test_recheck_marks_fixed(self) -> None:
        gone, stays = posted("a.py", 5, "gone"), posted("a.py", 10, "stays")
        agent = FakeAgent(
            verifier_replies=[votes(vote(0, False), vote(1)), votes(vote(0, False), vote(1)),
                              votes(vote(0), vote(1))],
        )  # fmt: skip
        inputs = self.inputs(agent, ReviewShape(1, 3, 2), rechecks=(gone, stays))
        result = find_and_vote(inputs)
        self.assertEqual((result.fixed, result.kept), ((gone.id,), ()))

    def test_one_finder_timeout_continues(self) -> None:
        agent = FakeAgent(
            finder_replies=[AgentRunResult(False, "", True), found(item())],
            verifier_replies=[votes(vote(0))],
        )
        result = find_and_vote(self.inputs(agent, ReviewShape(2, 1, 1)))
        self.assertEqual((len(result.kept), result.runs_used), (1, 3))

    def test_output_of_a_failed_run_is_ignored(self) -> None:
        agent = FakeAgent(finder_replies=[AgentRunResult(False, found(item())), found()])
        result = find_and_vote(self.inputs(agent, ReviewShape(2, 1, 1)))
        self.assertEqual((result.kept, result.runs_used), ((), 2))

    def test_no_finder_answering_is_incomplete(self) -> None:
        for replies in (
            [AgentRunResult(False, "", True)] * 2,
            [AgentRunResult(False, "", True), AgentRunResult(False, "boom")],
        ):
            agent = FakeAgent(finder_replies=replies)
            with self.assertRaises(ProviderError) as caught:
                find_and_vote(self.inputs(agent, ReviewShape(2, 1, 1)))
            self.assertEqual(caught.exception.code, "review_incomplete")
            self.assertEqual(caught.exception.details["runs_used"], 2)

    def test_all_finders_fail_raises(self) -> None:
        agent = FakeAgent(finder_replies=[AgentRunResult(False, "boom")] * 2)
        with self.assertRaises(ProviderError) as caught:
            find_and_vote(self.inputs(agent, ReviewShape(2, 1, 1)))
        self.assertEqual(caught.exception.code, "review_agent_failed")
        self.assertEqual(caught.exception.details["runs_used"], 2)

    def test_runs_used_counts_every_run(self) -> None:
        agent = FakeAgent(finder_replies=[found(item())] * 3, verifier_replies=[votes(vote(0))] * 2)
        result = find_and_vote(self.inputs(agent, ReviewShape(3, 2, 1)))
        self.assertEqual((result.runs_used, agent.runs), (5, 5))

    def test_prose_finder_answers_are_incomplete_when_none_parsed(self) -> None:
        for reply in ("Looks fine to me.", "{not json", json.dumps({"other": []}), found() * 30000):
            agent = FakeAgent(finder_replies=[reply])
            with self.assertRaises(ProviderError) as caught:
                find_and_vote(self.inputs(agent, ReviewShape(1, 1, 1)))
            self.assertEqual(caught.exception.code, "review_incomplete")

    def test_one_parsed_finder_is_enough(self) -> None:
        agent = FakeAgent(finder_replies=["prose", found()])
        result = find_and_vote(self.inputs(agent, ReviewShape(2, 1, 1)))
        self.assertEqual(result.kept, ())

    def test_garbled_ballot_does_not_count_toward_the_quorum(self) -> None:
        agent = FakeAgent(
            finder_replies=[found(item())], verifier_replies=[votes(vote(0)), "I agree with all"]
        )
        with self.assertRaises(ProviderError) as caught:
            find_and_vote(self.inputs(agent, ReviewShape(1, 2, 2)))
        self.assertEqual(caught.exception.code, "review_incomplete")

    def test_oversized_prompt_is_refused_before_any_agent_runs(self) -> None:
        agent = FakeAgent(finder_replies=[found()])
        big = self.inputs(agent, ReviewShape(1, 1, 1), diff="x" * 100_001)
        with self.assertRaises(StateConflict) as caught:
            find_and_vote(big)
        self.assertEqual(caught.exception.code, "review_diff_too_large")
        self.assertEqual(agent.runs, 0)
        self.assertIn("over the limit of 100000", str(caught.exception))
