from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.contracts import Mode, RawCommandResult, TaskResult, TaskStatus
from wev_skills.core.ports import SubprocessRunner
from wev_skills.state import model
from wev_skills.state.model import RepoSnapshot, RunState
from wev_skills.state.resume import DriftReport, check_drift, snapshot_repo

AT = "2026-10-13T12:00:00.000000Z"
GIT_IDENTITY = (
    "-c",
    "user.name=Wev Test",
    "-c",
    "user.email=wev-test@example.invalid",
    "-c",
    "commit.gpgsign=false",
)


class FakeRunner:
    """Answers every git call with one canned result and records what was asked."""

    def __init__(
        self, exit_code: int | None = 0, stdout: str = "", timed_out: bool = False
    ) -> None:
        self.result = (exit_code, stdout, timed_out)
        self.calls: list[tuple[tuple[str, ...], str | None, Mapping[str, str] | None]] = []

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None,
        timeout: float | None,
        env: Mapping[str, str] | None,
    ) -> RawCommandResult:
        self.calls.append((tuple(argv), cwd, env))
        exit_code, stdout, timed_out = self.result
        return RawCommandResult(tuple(argv), exit_code, stdout, "", 1, timed_out)


def new_state(**overrides: object) -> RunState:
    fields = {
        "run_id": "run-1",
        "objective": "ship",
        "mode": Mode.RESUME,
        "created_at": AT,
        "updated_at": AT,
        **overrides,
    }
    return RunState(**fields)  # type: ignore[arg-type]


def with_finished_task(state: RunState, task_id: str, files: tuple[str, ...]) -> RunState:
    state = model.with_task(state, task_id)
    state = model.with_task_status(state, task_id, TaskStatus.RUNNING, AT)
    return model.with_result(state, TaskResult(task_id, TaskStatus.VERIFIED, "ok", (), files), AT)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class GitCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve() / "repo"
        self.repo.mkdir()
        self.runner = SubprocessRunner()
        self.git("init", "--quiet", "--initial-branch=main")

    def git(self, *args: str) -> str:
        done = subprocess.run(
            ["git", *GIT_IDENTITY, *args], cwd=self.repo, capture_output=True, text=True, check=True
        )
        return done.stdout.strip()

    def commit(self, name: str, text: str = "x\n") -> str:
        (self.repo / name).write_text(text, encoding="utf-8")
        self.git("add", "--", name)
        self.git("commit", "--quiet", "-m", f"add {name}")
        return self.git("rev-parse", "HEAD")

    def snapshot(self) -> RepoSnapshot:
        snap = snapshot_repo(str(self.repo), self.runner)
        assert snap is not None
        return snap


class SnapshotTests(GitCase):
    def test_repository_without_commits_has_empty_head(self) -> None:
        snap = self.snapshot()
        self.assertEqual((snap.root, snap.branch, snap.head), (str(self.repo), "main", ""))
        self.assertEqual(snap.dirty_files, ())

    def test_snapshot_reports_head_branch_and_dirty_files(self) -> None:
        self.commit("a.txt")
        head = self.commit("b.txt")
        (self.repo / "a.txt").write_text("changed\n", encoding="utf-8")
        (self.repo / "new file.txt").write_text("n\n", encoding="utf-8")
        self.git("mv", "b.txt", "renamed.txt")
        snap = self.snapshot()
        self.assertEqual((snap.head, snap.branch), (head, "main"))
        self.assertEqual(snap.dirty_files, ("a.txt", "new file.txt", "renamed.txt"))

    def test_snapshot_from_subdirectory_reports_the_toplevel(self) -> None:
        self.commit("a.txt")
        (self.repo / "sub").mkdir()
        snap = snapshot_repo(str(self.repo / "sub"), self.runner)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.root if snap else "", str(self.repo))

    def test_detached_head_has_empty_branch(self) -> None:
        head = self.commit("a.txt")
        self.git("checkout", "--quiet", "--detach")
        self.assertEqual((self.snapshot().branch, self.snapshot().head), ("", head))

    def test_non_ascii_file_names_are_unquoted(self) -> None:
        (self.repo / "ação.txt").write_text("x", encoding="utf-8")
        self.assertEqual(self.snapshot().dirty_files, ("ação.txt",))

    def test_outside_a_repository_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as plain:
            self.assertIsNone(snapshot_repo(plain, self.runner))


class DriftTests(GitCase):
    def recorded(self) -> RunState:
        self.commit("a.txt")
        return model.with_repo(new_state(), self.snapshot())

    def test_unchanged_repository_has_no_drift(self) -> None:
        state = with_finished_task(self.recorded(), "t1", ("a.txt",))
        self.assertEqual(check_drift(state, self.runner), DriftReport(False))

    def test_new_commit_is_reported_as_head_change(self) -> None:
        state = self.recorded()
        self.commit("b.txt")
        report = check_drift(state, self.runner)
        self.assertTrue(report.drifted and report.head_changed)
        self.assertFalse(report.branch_changed)
        self.assertEqual(len(report.notes), 1)

    def test_branch_switch_is_reported(self) -> None:
        state = self.recorded()
        self.git("checkout", "--quiet", "-b", "feature")
        report = check_drift(state, self.runner)
        self.assertTrue(report.drifted and report.branch_changed)
        self.assertFalse(report.head_changed)

    def test_only_newly_dirty_files_are_reported(self) -> None:
        self.commit("a.txt")
        self.commit("b.txt")
        (self.repo / "a.txt").write_text("dirty before\n", encoding="utf-8")
        state = model.with_repo(new_state(), self.snapshot())
        self.assertFalse(check_drift(state, self.runner).drifted)
        (self.repo / "b.txt").write_text("dirty after\n", encoding="utf-8")
        report = check_drift(state, self.runner)
        self.assertTrue(report.drifted)
        self.assertEqual(report.new_dirty_files, ("b.txt",))

    def test_files_claimed_by_results_that_no_longer_exist_are_reported(self) -> None:
        state = with_finished_task(self.recorded(), "t1", ("a.txt", "gone.py", "sub/also-gone.py"))
        report = check_drift(state, self.runner)
        self.assertTrue(report.drifted)
        self.assertEqual(report.missing_files, ("gone.py", "sub/also-gone.py"))

    def test_claimed_paths_outside_the_root_are_noted_not_probed(self) -> None:
        state = with_finished_task(self.recorded(), "t1", ("../outside.txt", "/etc/hosts"))
        report = check_drift(state, self.runner)
        self.assertEqual(report.missing_files, ())
        self.assertFalse(report.drifted)
        self.assertIn("../outside.txt", report.notes[0])

    def test_task_recorded_as_running_is_never_assumed_finished(self) -> None:
        state = model.with_task(self.recorded(), "t1")
        state = model.with_task_status(state, "t1", TaskStatus.RUNNING, AT)
        report = check_drift(state, self.runner)
        self.assertTrue(report.drifted)
        self.assertEqual(report.stale_running_tasks, ("t1",))
        self.assertEqual(state.tasks["t1"].status, TaskStatus.RUNNING)

    def test_recorded_repository_that_disappeared_is_drift(self) -> None:
        state = self.recorded()
        shutil.rmtree(self.repo / ".git")
        report = check_drift(state, self.runner)
        self.assertTrue(report.drifted)
        self.assertEqual(
            report.notes, (i18n.t("state.drift.repo_unavailable", root=str(self.repo)),)
        )


class NoGitTests(unittest.TestCase):
    def test_missing_git_returns_none(self) -> None:
        runner = FakeRunner(exit_code=127)
        self.assertIsNone(snapshot_repo("/somewhere", runner))
        self.assertEqual(runner.calls[0][0], ("git", "rev-parse", "--show-toplevel"))
        self.assertEqual(runner.calls[0][1], "/somewhere")

    def test_not_a_repository_and_timeout_return_none(self) -> None:
        self.assertIsNone(snapshot_repo("/x", FakeRunner(exit_code=128)))
        self.assertIsNone(snapshot_repo("/x", FakeRunner(exit_code=None, timed_out=True)))

    def test_snapshot_never_passes_an_environment(self) -> None:
        runner = FakeRunner(stdout="/x\n")
        snapshot_repo("/x", runner)
        self.assertEqual(
            [call[0][1:] for call in runner.calls],
            [
                ("rev-parse", "--show-toplevel"),
                ("rev-parse", "HEAD"),
                ("branch", "--show-current"),
                ("status", "--porcelain"),
            ],
        )
        self.assertTrue(all(call[2] is None for call in runner.calls))

    def test_drift_without_recorded_root_runs_nothing_and_says_so(self) -> None:
        runner = FakeRunner()
        report = check_drift(new_state(), runner)
        self.assertEqual(runner.calls, [])
        self.assertFalse(report.drifted)
        self.assertEqual(report.notes, (i18n.t("state.drift.no_root"),))

    def test_drift_with_explicit_root_but_no_git_still_checks_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            Path(root, "kept.py").write_text("x", encoding="utf-8")
            state = with_finished_task(new_state(), "t1", ("kept.py", "lost.py"))
            report = check_drift(state, FakeRunner(exit_code=127), root=root)
        self.assertTrue(report.drifted)
        self.assertEqual(report.missing_files, ("lost.py",))
        self.assertFalse(report.head_changed or report.branch_changed)

    def test_recorded_repository_with_git_missing_is_drift(self) -> None:
        state = model.with_repo(new_state(), RepoSnapshot(os.getcwd(), "main", "abc"))
        report = check_drift(state, FakeRunner(exit_code=127))
        self.assertTrue(report.drifted)

    def test_report_serializes(self) -> None:
        report = DriftReport(True, True, False, ("a",), ("b",), ("t",), ("n",))
        self.assertEqual(DriftReport.from_dict(report.to_dict()), report)


if __name__ == "__main__":
    unittest.main()
