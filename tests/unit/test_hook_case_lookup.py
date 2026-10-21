"""The run lookup compares paths casefolded where the file system ignores case."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from tests.unit.test_hook_trust import DENY, TrustCase
from tests.unit.test_hooks import RUN
from wev_skills.core import active

FOLD = "wev_skills.security.paths.CASE_INSENSITIVE"


class CaseLookupTests(TrustCase):
    def setUp(self) -> None:
        super().setUp()
        self.start(mode="plan")
        self.elsewhere = self.work.parent / "elsewhere"
        self.elsewhere.mkdir()
        self.shouted = Path(str(self.work).upper())

    def test_a_path_in_another_case_finds_the_registered_run(self) -> None:
        line = f"rm -rf {self.shouted}/src"
        with mock.patch(FOLD, True):
            found = self.bash(line, self.elsewhere)
        assert found is not None
        self.assertEqual(found["decision"], DENY)
        self.assertIn(f"wev run {RUN} (plan mode)", found["reason"])

    def test_a_parent_in_another_case_finds_the_registered_run(self) -> None:
        with mock.patch(FOLD, True):
            found = active.find_hook_run(self.elsewhere, targets=(self.shouted.parent,))
        assert found is not None
        self.assertEqual(found.run_id, RUN)

    def test_a_working_directory_in_another_case_finds_the_registered_run(self) -> None:
        with mock.patch(FOLD, True):
            found = active.find_hook_run(self.shouted / "src")
        assert found is not None
        self.assertEqual((found.run_id, found.state_error), (RUN, None))

    def test_case_counts_where_the_file_system_keeps_it(self) -> None:
        with mock.patch(FOLD, False):
            found = active.find_hook_run(self.elsewhere, (self.shouted / "src",))
        self.assertIsNone(found)


class CaseGitDirectoryTests(TrustCase):
    def setUp(self) -> None:
        super().setUp()
        self.start()

    def test_git_dash_c_in_another_case_stays_inside_the_root(self) -> None:
        line = f"git -C {str(self.work).upper()} status"
        with mock.patch(FOLD, True):
            self.assertIsNone(self.decision(line))
        with mock.patch(FOLD, False):
            self.assertEqual(self.decision(line), "ask")
