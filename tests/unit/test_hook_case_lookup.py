"""The run lookup compares paths without case only where the file system confirms it."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from tests.unit.test_hook_trust import DENY, TrustCase
from tests.unit.test_hooks import RUN
from wev_skills.core import active
from wev_skills.security import paths

FOLD = "wev_skills.security.paths.CASE_INSENSITIVE"
DIFFERENT_FILES = mock.patch("os.path.samefile", return_value=False)


class ShoutedCase(TrustCase):
    """``self.shouted`` is the repository's name in capitals. On a case-sensitive file
    system it is made a symlink to the repository, which is what a volume that ignores
    case reports."""

    def setUp(self) -> None:
        super().setUp()
        self.shouted = self.work.parent / self.work.name.upper()
        self.linked = not self.shouted.exists()
        if self.linked:
            self.shouted.symlink_to(self.work, target_is_directory=True)
        self.elsewhere = self.work.parent / "elsewhere"
        self.elsewhere.mkdir()


class CaseLookupTests(ShoutedCase):
    def setUp(self) -> None:
        super().setUp()
        self.start(mode="plan")

    def test_a_path_in_another_case_finds_the_registered_run(self) -> None:
        with mock.patch(FOLD, True):
            found = self.bash(f"rm -rf {self.shouted}/src", self.elsewhere)
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


class CaseSensitiveVolumeTests(ShoutedCase):
    """A case-sensitive volume on macOS keeps ``Repo`` and ``repo`` apart."""

    def test_another_directory_with_a_folded_equal_name_is_not_the_run(self) -> None:
        self.start(mode="plan")
        with mock.patch(FOLD, True), DIFFERENT_FILES:
            found = active.find_hook_run(self.elsewhere, (Path(f"{self.work}X".upper()),))
            beside = active.find_hook_run(self.elsewhere, (self.shouted / "src",))
        self.assertIsNone(found)
        if not self.linked:
            self.assertIsNone(beside)

    def test_a_forged_tree_beside_a_registered_one_stays_unregistered(self) -> None:
        self.start()
        forged = self.work.parent / "REPO-forged"
        self.forge_at(forged)
        entry = active.run_registry.read_entries()[0]
        twin = active.run_registry.RegistryEntry(str(forged).lower(), entry.state_dir, RUN)
        with (
            mock.patch(FOLD, True),
            DIFFERENT_FILES,
            mock.patch.object(active.run_registry, "read_registry", return_value=(twin,)),
        ):
            found = active.find_hook_run(forged)
        assert found is not None
        self.assertEqual(found.state_error, active.UNREGISTERED)

    def forge_at(self, place: Path) -> None:
        (place / ".git").mkdir(parents=True)
        previous = self.work
        self.work = place
        try:
            self.forge()
        finally:
            self.work = previous


class SamePlaceTests(unittest.TestCase):
    def test_folded_equal_spellings_need_the_file_system_to_agree(self) -> None:
        with mock.patch(FOLD, True):
            with DIFFERENT_FILES:
                self.assertFalse(paths.same_place("/v/Repo", "/v/repo"))
                self.assertFalse(paths.place_within("/v/REPO/src", "/v/repo"))
            with mock.patch("os.path.samefile", return_value=True):
                self.assertTrue(paths.same_place("/v/Repo", "/v/repo"))
                self.assertTrue(paths.place_within("/v/REPO/src", "/v/repo"))
            with mock.patch("os.path.samefile", side_effect=OSError):
                self.assertFalse(paths.same_place("/v/Repo", "/v/repo"))

    def test_without_folding_only_the_exact_spelling_matches(self) -> None:
        with mock.patch(FOLD, False):
            self.assertTrue(paths.place_within("/v/repo/src", "/v/repo/"))
            self.assertTrue(paths.same_place("/v/repo", "/v/repo"))
            self.assertFalse(paths.same_place("/v/Repo", "/v/repo"))
            self.assertFalse(paths.place_within("/v/repository", "/v/repo"))


class CaseGitDirectoryTests(ShoutedCase):
    def setUp(self) -> None:
        super().setUp()
        self.start()

    def test_git_dash_c_in_another_case_stays_inside_the_root(self) -> None:
        line = f"git -C {self.shouted} status"
        with mock.patch(FOLD, True):
            self.assertIsNone(self.decision(line))

    @unittest.skipIf(os.name != "posix", "symlinks")
    def test_git_dash_c_into_a_different_folded_equal_directory_asks(self) -> None:
        other = self.work.parent / f"{self.work.name}X".upper()
        other.mkdir()
        with mock.patch(FOLD, True), DIFFERENT_FILES:
            self.assertEqual(self.decision(f"git -C {other} status"), "ask")
            if not self.linked:
                self.assertEqual(self.decision(f"git -C {self.shouted} status"), "ask")
