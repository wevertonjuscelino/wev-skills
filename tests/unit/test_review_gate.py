import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.config import Config
from wev_skills.config_review import ReviewConfig
from wev_skills.core.contracts import Mode
from wev_skills.core.errors import StateConflict
from wev_skills.core.ports import SubprocessRunner
from wev_skills.review.changed import changed_paths
from wev_skills.review.gate import (
    config_weakened,
    current_config,
    finish_refusal,
    read_comparisons,
)
from wev_skills.review.trees import write_tree
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
    def refusal(self, st, cfg=None, changed=(), comparisons=(), weakened=False):
        return finish_refusal(st, cfg or config(), FP, changed, comparisons, weakened)

    def refused(self, *args, **kwargs):
        err = self.refusal(*args, **kwargs)
        self.assertIsNotNone(err)
        return err

    def test_open_important_refuses_and_lists_ids(self) -> None:
        err = self.refused(state(finding(name="abc123")))
        self.assertEqual(err.code, "review_open_important")
        self.assertIn("abc123", err.message)
        self.assertEqual(err.exit_code, 5)

    def test_stale_review_refuses(self) -> None:
        self.assertEqual(self.refused(state(fingerprint="old")).code, "review_stale")

    def test_no_round_refuses(self) -> None:
        self.assertEqual(self.refused(state(rounds=False)).code, "review_stale")

    def test_unscored_reviewer_change_refuses(self) -> None:
        for path in ("REVIEW.md", REVIEWER):
            err = self.refused(state(), changed={path})
            self.assertEqual(err.code, "reviewer_unscored")

    def test_unnormalized_project_dir_still_protects_reviewer(self) -> None:
        for project_dir in ("./wev-specialists", "wev-specialists/"):
            cfg = replace(config(), agents=replace(Config().agents, project_dir=project_dir))
            err = self.refused(state(), cfg, changed={REVIEWER})
            self.assertEqual(err.code, "reviewer_unscored")

    def test_weakened_config_refuses(self) -> None:
        err = self.refused(state(), weakened=True)
        self.assertEqual(err.code, "review_config_weakened")

    def test_config_weakened_rules(self) -> None:
        def cfg(**review: object) -> Config:
            return replace(
                Config(), review=ReviewConfig(**{"agent": "r", "depth": "standard", **review})
            )

        pinned = cfg()
        self.assertTrue(config_weakened(pinned, cfg(depth="off")))
        self.assertTrue(config_weakened(pinned, cfg(depth="quick")))
        self.assertTrue(config_weakened(pinned, cfg(agent="x")))
        self.assertTrue(config_weakened(pinned, None))
        other = replace(pinned, agents=replace(pinned.agents, project_dir="other"))
        self.assertTrue(config_weakened(pinned, other))
        self.assertFalse(config_weakened(pinned, cfg(depth="deep")))
        self.assertFalse(config_weakened(pinned, replace(pinned, harness=Config().harness)))

    def test_current_config_resolves_like_run_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, user = Path(tmp) / "repo", Path(tmp) / "user.json"
            root.mkdir()
            custom = root / "custom.json"  # an explicit --config path
            custom.write_text(json.dumps({"review": {"depth": "quick", "agent": "r"}}))
            self.assertEqual(current_config(str(custom), root).review.depth, "quick")
            custom.write_text("{not json")
            self.assertIsNone(current_config(str(custom), root))
            self.assertEqual(current_config("defaults", root).review.depth, "off")
            repo_file = root / "wev.config.json"
            repo_file.write_text(json.dumps({"review": {"depth": "standard", "agent": "r"}}))
            user.write_text(json.dumps({"review": {"depth": "off"}}))
            with mock.patch("wev_skills.config.user_config_path", return_value=user):
                # the user tier is merged under the repository file: unchanged repo file wins
                self.assertEqual(current_config(str(repo_file), root).review.depth, "standard")
                repo_file.write_text("{}")
                now = current_config(str(repo_file), root)
                self.assertTrue(config_weakened(config(), now))

    def test_off_finishes_as_before(self) -> None:
        st = state(rounds=False)
        self.assertIsNone(self.refusal(st, config("off"), {"REVIEW.md"}))

    def test_dismissed_important_does_not_block(self) -> None:
        self.assertIsNone(self.refusal(state(finding(status="dismissed"))))

    def test_pre_existing_never_blocks(self) -> None:
        self.assertIsNone(self.refusal(state(finding(tag="pre_existing"))))

    def test_improving_comparison_lets_reviewer_change_finish(self) -> None:
        changed = {REVIEWER}
        self.assertIsNone(self.refusal(state(), changed=changed, comparisons=[comparison()]))

    def test_hand_edited_or_mismatched_comparison_does_not_count(self) -> None:
        changed = {REVIEWER}
        for bad in (
            comparison(current={"c": 0}),
            comparison(fingerprint="other"),
            comparison(depth="deep"),
            comparison(improves=False),
            comparison(baseline="x"),
        ):
            err = self.refused(state(), changed=changed, comparisons=[bad])
            self.assertEqual(err.code, "reviewer_unscored")

    def test_read_comparisons_skips_bad_lines_and_other_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores.jsonl"
            self.assertEqual(read_comparisons(path), [])
            path.write_text(
                "not json\n" + json.dumps({"score": 1}) + "\n" + json.dumps(comparison()) + "\n"
            )
            self.assertEqual(read_comparisons(path), [comparison()])


class ChangedPathsTest(unittest.TestCase):
    def test_deletion_and_mode_change_are_changed_paths(self) -> None:
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "REVIEW.md").write_text("x\n")
        (root / "run.sh").write_text("x\n")
        (root / "odd name.txt").write_text("x\n")
        runner = SubprocessRunner()
        base = write_tree(runner, root)
        (root / "REVIEW.md").unlink()
        (root / "run.sh").chmod(0o755)
        now = write_tree(runner, root)
        self.assertEqual(changed_paths(runner, root, base, now), {"REVIEW.md", "run.sh"})


class FinishWiringTest(OrchestratorCase):
    def test_finish_raises_before_recording_anything(self) -> None:
        self.start()
        orch = self.orch()
        orch.commit(lambda s: replace(s, review_rounds=state(finding()).review_rounds), "x", {})
        with self.assertRaises(StateConflict) as caught:
            orch.finish()
        self.assertEqual(caught.exception.code, "review_open_important")
        self.assertNotEqual(self.state().phase, Phase.DONE)

    def test_deleting_review_md_refuses_finish(self) -> None:
        self.overrides = {"review": {"depth": "quick", "agent": "r"}}
        (self.root / "wev.config.json").write_text(json.dumps(self.overrides))
        self.runner = SubprocessRunner()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "REVIEW.md").write_text("x\n")
        self.start()
        orch = self.orch()
        base = write_tree(orch.services.runner, self.root)
        (self.root / "REVIEW.md").unlink()
        fingerprint = orch.fingerprint(self.state())
        rec = ReviewRoundRecord(1, "now", "full", base, fingerprint, "quick")
        orch.commit(lambda s: replace(s, base=base, review_rounds=(rec,)), "x", {})
        with self.assertRaises(StateConflict) as caught:
            orch.finish()
        self.assertEqual(caught.exception.code, "reviewer_unscored")

    def test_depth_off_does_no_git_work(self) -> None:
        self.runner = SubprocessRunner()
        self.start()
        orch = self.orch()
        orch.commit(lambda s: replace(s, base="0" * 40), "x", {})
        self.assertEqual(orch.finish()["phase"], "done")

    def test_pinned_review_on_and_config_file_off_refuses(self) -> None:
        self.overrides = {"review": {"depth": "standard", "agent": "r"}}
        self.runner = SubprocessRunner()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.start()
        orch = self.orch()
        (self.root / "wev.config.json").write_text(json.dumps({"review": {"depth": "off"}}))
        base = write_tree(orch.services.runner, self.root)
        rec = ReviewRoundRecord(1, "now", "full", base, orch.fingerprint(self.state()), "standard")
        orch.commit(lambda s: replace(s, base=base, review_rounds=(rec,)), "x", {})
        with self.assertRaises(StateConflict) as caught:
            orch.finish()
        self.assertEqual(caught.exception.code, "review_config_weakened")

    def test_off_with_nothing_open_finishes(self) -> None:
        self.start()
        self.assertEqual(self.orch().finish()["phase"], "done")


if __name__ == "__main__":
    unittest.main()
