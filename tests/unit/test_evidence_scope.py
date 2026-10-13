"""Manual evidence must point at the run's records or the task's own files, and the plan
author is told when a task leans on files git ignores (they are outside the fingerprint)."""

from __future__ import annotations

from typing import Any

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.core.contracts import Evidence, EvidenceLabel, TaskStatus
from wev_skills.core.errors import ValidationError

TASK = {
    "id": "docs",
    "files": ["README.md", "docs"],
    "acceptance_criteria": ["README reworded"],
    "checks": ["true"],
}


class EvidenceScopeTests(OrchestratorCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / "docs").mkdir()
        for name in ("README.md", "docs/guide.md", "unrelated.txt"):
            (self.root / name).write_text("text\n", encoding="utf-8")
        self.start("Update README wording", files_touched_estimate=6)
        self.set_plan(TASK)
        self.orch().next_tasks()
        self.orch().start_task("docs")
        self.runner.edit("reworded")

    def record(self, ref: str) -> dict[str, Any]:
        proof = Evidence("criterion:README reworded", "read back", ref, 0, EvidenceLabel.TESTED)
        return self.orch().record_task("docs", TaskStatus.VERIFIED, "reworded", evidence=(proof,))

    def test_an_arbitrary_existing_file_is_not_evidence(self) -> None:
        for ref in ("Makefile", "unrelated.txt", "plan.json", str(self.root / "Makefile")):
            with self.subTest(ref=ref), self.assertRaises(ValidationError) as caught:
                self.record(ref)
            error = caught.exception
            self.assertEqual(error.code, "invalid_evidence_ref")
            self.assertIn("log", error.message)
            self.assertIn("evidence directory", error.message)
            self.assertIn("README.md, docs", error.message)
        self.assertEqual(self.status_of("docs"), TaskStatus.RUNNING)

    def test_a_file_the_task_lists_is_accepted(self) -> None:
        self.assertEqual(self.record("README.md")["status"], "verified")

    def test_a_file_inside_a_listed_directory_is_accepted(self) -> None:
        self.assertEqual(self.record("docs/guide.md")["status"], "verified")

    def test_a_command_log_of_the_run_is_accepted(self) -> None:
        payload, _ = self.orch().exec_command(("cat", "README.md"), task_id="docs")
        self.assertEqual(self.record(payload["record"]["stdout_ref"])["status"], "verified")

    def test_a_file_in_the_runs_evidence_directory_is_accepted(self) -> None:
        directory = self.orch().store.run_dir / "evidence"
        directory.mkdir()
        (directory / "screenshot.txt").write_text("seen\n", encoding="utf-8")
        self.assertEqual(self.record(str(directory / "screenshot.txt"))["status"], "verified")

    def test_the_rest_of_the_state_directory_is_still_refused(self) -> None:
        for ref in (".wev/audit.jsonl", str(self.orch().store.run_dir / "state.json")):
            with self.subTest(ref=ref), self.assertRaises(ValidationError):
                self.record(ref)


class IgnoredFileTests(OrchestratorCase):
    def ignore(self, *paths: str) -> None:
        original = self.runner._git

        def git(args: tuple[str, ...]) -> tuple[int | None, str, str]:
            if args[1:3] == ("check-ignore", "--"):
                hit = [path for path in args[3:] if path in paths]
                return (0 if hit else 1), "".join(f"{path}\n" for path in hit), ""
            return original(args)

        self.runner._git = git  # type: ignore[method-assign]

    def test_plan_set_warns_about_ignored_files_and_check_arguments(self) -> None:
        self.ignore("local_settings.py", "build/out.txt")
        self.start("planned", files_touched_estimate=6)
        out = self.set_plan(
            {"id": "a", "files": ["calc.py", "local_settings.py"], "checks": ["make test"]},
            {"id": "b", "files": ["b.py"], "checks": ["test -f build/out.txt"]},
            {"id": "c", "files": ["c.py"], "checks": ["make test"]},
        )
        self.assertEqual(len(out["warnings"]), 2, out["warnings"])
        first, second = out["warnings"]
        self.assertIn("a", first)
        self.assertIn("local_settings.py", first)
        self.assertIn("outside the tree fingerprint", first)
        self.assertIn("build/out.txt", second)

    def test_no_ignored_path_means_no_warning(self) -> None:
        self.ignore()
        self.start("planned", files_touched_estimate=6)
        self.assertEqual(self.set_plan({"id": "a", "files": ["calc.py"]})["warnings"], [])

    def test_the_verification_and_the_report_say_ignored_files_are_outside(self) -> None:
        self.start()
        self.run_task()
        checked = self.orch().check_task("task-1")
        self.assertIn("ignores are outside", checked["fingerprint_notice"])
        notices = "\n".join(self.orch().report()["notices"])
        self.assertIn("ignores are outside", notices)
        self.assertIn("not continuously", notices)
