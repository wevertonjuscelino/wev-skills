"""reviews.jsonl: what rounds and outcomes write, and the stats read back from it."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.fixtures.fake_agent import FakeAgent
from tests.fixtures.operator_prompt import ScriptedPrompt
from tests.unit import test_review_commands, test_review_round
from tests.unit._review_helpers import found, item, vote, votes
from wev_skills.review.stats import REVIEWS_FILE, review_stats


def lines(root: Path) -> list[dict[str, object]]:
    text = (root / "state" / REVIEWS_FILE).read_text()
    return [json.loads(row) for row in text.splitlines()]


class WrittenLines(test_review_commands.ReviewCommandCase):
    def test_round_and_outcome_lines_written(self) -> None:
        important, nit = self.review_two()
        self.cli("review", "resolve", nit, "--as", "intentional", "--reason", "SECRET reason")
        self.cli("review", "dismiss", important, "--as", "wrong", "--reason", "false alarm",
                 tty=True, prompt=ScriptedPrompt())  # fmt: skip
        round_line, nit_line, important_line = lines(self.root)
        self.assertEqual(
            {k: round_line[k] for k in ("kind", "run_id", "round", "depth", "important", "nit")},
            {"kind": "round", "run_id": "r1", "round": 1, "depth": "quick", "important": 1,
             "nit": 1},
        )  # fmt: skip
        self.assertEqual((round_line["pre_existing"], round_line["runs_used"]), (0, 2))
        self.assertEqual(
            (nit_line["finding"], nit_line["tag"], nit_line["outcome"], nit_line["by"]),
            (nit, "nit", "intentional", "agent"),
        )
        self.assertEqual((important_line["by"], important_line["round"]), ("person", 1))
        raw = (self.root / "state" / REVIEWS_FILE).read_text()
        for text in ("Big", "Small", "SECRET", "false alarm", "wrong."):
            self.assertNotIn(text, raw)

    def test_an_unwritable_stats_file_warns_and_never_fails_the_round(self) -> None:
        (self.root / "state").mkdir(exist_ok=True)
        (self.root / "state" / REVIEWS_FILE).mkdir()  # appending to a directory: OSError
        agent = FakeAgent(finder_replies=[found(item(5))], verifier_replies=[votes(vote(0))])
        code, out, err = self.cli("review", "run", agent=agent)
        self.assertEqual((code, len(out["round"]["findings"])), (0, 1))
        self.assertIn("Could not write reviews.jsonl", err)
        self.assertEqual(len(self.cli("review", "show")[1]["open"]), 1)  # the round is recorded

    def test_an_unwritable_stats_file_warns_and_never_fails_a_resolution(self) -> None:
        _, nit = self.review_two()
        path = self.root / "state" / REVIEWS_FILE
        path.unlink()
        path.mkdir()
        code, out, err = self.cli("review", "resolve", nit, "--as", "intentional", "--reason", "x")
        self.assertEqual((code, out["finding"]["status"]), (0, "dismissed"))
        self.assertIn("Could not write reviews.jsonl", err)

    def test_refused_resolution_writes_nothing(self) -> None:
        important, _ = self.review_two()
        self.cli("review", "resolve", important, "--as", "wrong", "--reason", "x")
        self.assertEqual([r["kind"] for r in lines(self.root)], ["round"])

    def test_stats_command_prints_candidates(self) -> None:
        important, _ = self.review_two()
        self.cli("review", "dismiss", important, "--as", "wrong", "--reason", "x",
                 tty=True, prompt=ScriptedPrompt())  # fmt: skip
        code, out, _ = self.cli("review", "stats")
        self.assertEqual(code, 0)
        self.assertEqual(out["clean_case_candidates"], [{"run_id": "r1", "finding": important}])


class FixedLine(test_review_round.RoundTests):
    def test_engine_fixed_finding_is_recorded(self) -> None:
        self.start()
        self.edit(5, "x5 = 'changed'")
        first = self.run_round(test_review_round.one_finding_agent())
        self.edit(5, "x5 = 'repaired'")
        self.run_round(FakeAgent(verifier_replies=[votes(vote(0, real=False))]))
        path = self.orch().services.state_dir / REVIEWS_FILE
        rows = [json.loads(r) for r in path.read_text().splitlines()]
        (fixed,) = [r for r in rows if r["kind"] == "outcome"]
        self.assertEqual(
            (fixed["finding"], fixed["outcome"], fixed["by"], fixed["round"]),
            (first.findings[0].id, "fixed", "engine", 1),
        )


class Stats(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / REVIEWS_FILE
        self.addCleanup(self.path.parent.rmdir)
        self.addCleanup(self.path.unlink, True)

    def write(self, *rows: object) -> None:
        self.path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows))

    def test_stats_aggregate_by_depth(self) -> None:
        def rnd(run: str, number: int, depth: str, important: int) -> dict[str, object]:
            return {"kind": "round", "run_id": run, "round": number, "depth": depth,
                    "important": important, "nit": 1, "pre_existing": 0, "skipped": 0,
                    "runs_used": 2}  # fmt: skip

        def out(finding: str, outcome: str, depth: str, by: str = "agent") -> dict[str, object]:
            return {"kind": "outcome", "run_id": "a", "finding": finding, "tag": "nit",
                    "outcome": outcome, "depth": depth, "round": 1, "by": by}  # fmt: skip

        self.write(
            rnd("a", 1, "quick", 1), rnd("b", 1, "quick", 0), rnd("b", 2, "quick", 2),
            rnd("a", 1, "deep", 3), out("f1", "wrong", "quick"), out("f2", "fixed", "quick"),
            out("f3", "wrong", "deep"),
        )  # fmt: skip
        depths = review_stats(self.path)["depths"]
        quick = depths["quick"]  # type: ignore[index]
        self.assertEqual((quick["rounds"], quick["runs"]), (3, 2))
        self.assertAlmostEqual(quick["findings_per_round"], (2 + 1 + 3) / 3)
        self.assertEqual(quick["outcome_share"], {"fixed": 0.5, "wrong": 0.5})
        self.assertAlmostEqual(quick["rounds_per_run"], 1.5)
        self.assertEqual(quick["runs_passing_after_one_round"], 1)
        self.assertEqual(depths["deep"]["outcome_share"], {"wrong": 1.0})  # type: ignore[index]

    def test_wrong_dismissal_listed_as_candidate(self) -> None:
        base = {"kind": "outcome", "run_id": "a", "tag": "important", "depth": "quick",
                "round": 1}  # fmt: skip
        self.write(
            {**base, "finding": "p1", "outcome": "wrong", "by": "person"},
            {**base, "finding": "p2", "outcome": "intentional", "by": "person"},
            {**base, "finding": "a1", "outcome": "wrong", "by": "agent"},
            "not json",
            "[1]",
            {"kind": "round", "run_id": 5},
            {**base, "finding": "p3", "outcome": "wrong", "by": "person", "round": True},
        )
        self.assertEqual(
            review_stats(self.path)["clean_case_candidates"], [{"run_id": "a", "finding": "p1"}]
        )

    def test_unreadable_and_deeply_nested_lines_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(review_stats(Path(tmp))["depths"], {})  # a directory: OSError
            path = Path(tmp) / "r.jsonl"
            path.write_text("[" * 200_000 + "\n")
            self.assertEqual(review_stats(path)["depths"], {})

    def test_missing_file_gives_empty_stats(self) -> None:
        self.assertEqual(
            review_stats(self.path.parent / "none.jsonl"),
            {"depths": {}, "clean_case_candidates": []},
        )
