import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.config import Config
from wev_skills.config_review import ReviewConfig
from wev_skills.core.contracts import Mode
from wev_skills.core.errors import StateConflict
from wev_skills.review.gate import finish_refusal, read_comparisons
from wev_skills.state.model import Phase, RunState
from wev_skills.state.review_records import FindingRecord, ReviewRoundRecord

FP = "fp-now"
REVIEWER = "wev-specialists/wev-reviewer.json"


def finding(tag: str = "important", status: str = "open", name: str = "f1") -> FindingRecord:
    return FindingRecord(name, 1, "a.py", 2, "t", "b", tag, False, 2, 3, status=status)


def state(*findings: FindingRecord, fingerprint: str = FP, rounds: bool = True) -> RunState:
    rec = ReviewRoundRecord(1, "now", "full", "t", fingerprint, "standard", findings)
    return RunState(
        "run-1", "goal", Mode.EXECUTE, "now", "now", review_rounds=(rec,) if rounds else ()
    )


def config(depth: str = "standard") -> Config:
    return replace(Config(), review=ReviewConfig(agent="wev-reviewer", depth=depth))


def comparison(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "compare": "HEAD", "fingerprint": FP, "depth": "standard",
        "baseline": {"c": 1}, "current": {"c": 2}, "improves": True,
    }  # fmt: skip
    return {**base, **over}


class FinishGateTest(unittest.TestCase):
    def refusal(self, st, cfg=None, touched=None, comparisons=()):
        return finish_refusal(st, cfg or config(), FP, touched or {}, comparisons)

    def test_open_important_refuses_and_lists_ids(self) -> None:
        err = self.refusal(state(finding(name="abc123")))
        self.assertEqual(err.code, "review_open_important")
        self.assertIn("abc123", err.message)
        self.assertEqual(err.exit_code, 5)

    def test_stale_review_refuses(self) -> None:
        self.assertEqual(self.refusal(state(fingerprint="old")).code, "review_stale")

    def test_no_round_refuses(self) -> None:
        self.assertEqual(self.refusal(state(rounds=False)).code, "review_stale")

    def test_unscored_reviewer_change_refuses(self) -> None:
        for path in ("REVIEW.md", REVIEWER):
            err = self.refusal(state(), touched={path: frozenset({1})})
            self.assertEqual(err.code, "reviewer_unscored")

    def test_off_finishes_as_before(self) -> None:
        st = state(rounds=False)
        self.assertIsNone(self.refusal(st, config("off"), {"REVIEW.md": frozenset({1})}))

    def test_dismissed_important_does_not_block(self) -> None:
        self.assertIsNone(self.refusal(state(finding(status="dismissed"))))

    def test_pre_existing_never_blocks(self) -> None:
        self.assertIsNone(self.refusal(state(finding(tag="pre_existing"))))

    def test_improving_comparison_lets_reviewer_change_finish(self) -> None:
        touched = {REVIEWER: frozenset({1})}
        self.assertIsNone(self.refusal(state(), touched=touched, comparisons=[comparison()]))

    def test_hand_edited_or_mismatched_comparison_does_not_count(self) -> None:
        touched = {REVIEWER: frozenset({1})}
        for bad in (
            comparison(current={"c": 0}),
            comparison(fingerprint="other"),
            comparison(depth="deep"),
            comparison(improves=False),
            comparison(baseline="x"),
        ):
            err = self.refusal(state(), touched=touched, comparisons=[bad])
            self.assertEqual(err.code, "reviewer_unscored")

    def test_read_comparisons_skips_bad_lines_and_other_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores.jsonl"
            self.assertEqual(read_comparisons(path), [])
            path.write_text(
                "not json\n" + json.dumps({"score": 1}) + "\n" + json.dumps(comparison()) + "\n"
            )
            self.assertEqual(read_comparisons(path), [comparison()])


class FinishWiringTest(OrchestratorCase):
    def test_finish_raises_before_recording_anything(self) -> None:
        self.start()
        orch = self.orch()
        orch.commit(lambda s: replace(s, review_rounds=state(finding()).review_rounds), "x", {})
        with self.assertRaises(StateConflict) as caught:
            orch.finish()
        self.assertEqual(caught.exception.code, "review_open_important")
        self.assertNotEqual(self.state().phase, Phase.DONE)

    def test_off_with_nothing_open_finishes(self) -> None:
        self.start()
        self.assertEqual(self.orch().finish()["phase"], "done")


if __name__ == "__main__":
    unittest.main()
