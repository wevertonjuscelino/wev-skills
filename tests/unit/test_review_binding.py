from __future__ import annotations

import time
from dataclasses import replace

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.core import progress
from wev_skills.state.model import iso_utc
from wev_skills.state.records import ReviewRecord


class ReviewBindingTests(OrchestratorCase):
    def two_tasks(self) -> None:
        self.start(files_touched_estimate=8)
        self.set_plan(
            {"id": "a", "acceptance_criteria": ["works"], "checks": ["make test"]},
            {"id": "b", "acceptance_criteria": ["works"], "checks": ["make test"]},
        )
        self.run_task("a")
        self.verify("a")

    def accepted(self, task_id: str = "a") -> bool:
        return progress.review_accepted(self.state(), task_id)

    def test_review_stores_the_task_recorded_tree(self) -> None:
        self.two_tasks()
        self.orch().review_task("a", "reviewer", True, "ok")
        state = self.state()
        stored = progress.latest_review(state, "a")
        assert stored is not None
        self.assertTrue(stored.fingerprint)
        self.assertEqual(stored.fingerprint, progress.recorded_tree(state, "a"))

    def test_review_survives_another_task_editing_other_files(self) -> None:
        self.two_tasks()
        self.orch().review_task("a", "reviewer", True, "ok")
        self.orch().next_tasks()
        self.orch().start_task("b")
        self.verify("b")
        self.assertTrue(self.accepted("a"))

    def test_review_voids_when_the_task_is_redone(self) -> None:
        self.two_tasks()
        self.orch().review_task("a", "reviewer", True, "ok")
        self.orch().reopen_task("a", "redo it", "ana", "tty")
        self.run_task("a")
        self.verify("a")
        self.assertFalse(self.accepted("a"))
        self.assertIn("wev task review a", self.state().next_step)

    def test_review_voids_when_the_task_is_redone_to_an_identical_tree(self) -> None:
        # The engine will not verify a redone task whose tree equals its baseline, so the
        # redo is staged: same recorded tree and fingerprint, finished after the review.
        self.two_tasks()
        self.orch().review_task("a", "reviewer", True, "ok")
        state = self.state()
        self.assertTrue(progress.review_accepted(state, "a"))
        record = state.tasks["a"]
        redone = replace(record, finished_at=iso_utc(time.time() + 3600))
        later = replace(state, tasks={**state.tasks, "a": redone})
        review = progress.latest_review(later, "a")
        assert review is not None
        self.assertEqual(review.fingerprint, progress.recorded_tree(later, "a"))
        self.assertFalse(progress.review_accepted(later, "a"))

    def test_review_survives_a_recheck_before_finish(self) -> None:
        self.two_tasks()
        self.orch().review_task("a", "reviewer", True, "ok")
        self.runner.edit("later")
        self.orch().check_task("a")
        self.assertTrue(self.accepted("a"))

    def test_old_review_without_fingerprint_does_not_count(self) -> None:
        self.two_tasks()
        self.orch().review_task("a", "reviewer", True, "ok")
        state = self.state()
        old = ReviewRecord.from_dict({**state.reviews[0].to_dict()})
        data = {k: v for k, v in old.to_dict().items() if k != "fingerprint"}
        loaded = ReviewRecord.from_dict(data)
        self.assertEqual(loaded.fingerprint, "")
        self.assertFalse(progress.review_accepted(replace(state, reviews=(loaded,)), "a"))
