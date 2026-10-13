from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import PermissionDenied
from wev_skills.security.paths import is_protected, resolve_within

SECRET_FILE = "." + "env"
PROTECTED = (".git", SECRET_FILE)


class PathCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root = base / "repo"
        self.outside = base / "outside"
        (self.root / "src").mkdir(parents=True)
        (self.root / ".git").mkdir()
        self.outside.mkdir()
        (self.root / "src" / "a.py").write_text("x")
        (self.root / SECRET_FILE).write_text("x")
        (self.outside / "secret.txt").write_text("x")


class ResolveWithinTests(PathCase):
    def test_returns_resolved_paths_inside_the_root(self) -> None:
        self.assertEqual(resolve_within(self.root, "src/a.py"), self.root / "src" / "a.py")
        self.assertEqual(resolve_within(self.root, "src/../src/a.py"), self.root / "src" / "a.py")
        self.assertEqual(resolve_within(self.root, "."), self.root)
        self.assertEqual(resolve_within(self.root, "new/file.txt"), self.root / "new" / "file.txt")
        self.assertEqual(resolve_within(str(self.root), self.root / "src"), self.root / "src")

    def test_rejects_parent_traversal(self) -> None:
        for path in ("..", "../outside/secret.txt", "src/../../outside", "src/../../../etc/passwd"):
            with self.subTest(path=path), self.assertRaises(PermissionDenied) as caught:
                resolve_within(self.root, path)
            self.assertEqual(caught.exception.code, "path_escape")

    def test_rejects_absolute_paths_outside_the_root(self) -> None:
        for path in ("/etc/passwd", str(self.outside / "secret.txt"), str(self.root) + "-sibling"):
            with self.subTest(path=path), self.assertRaises(PermissionDenied):
                resolve_within(self.root, path)

    def test_rejects_a_symlink_pointing_outside(self) -> None:
        (self.root / "leak").symlink_to(self.outside / "secret.txt")
        with self.assertRaises(PermissionDenied):
            resolve_within(self.root, "leak")

    def test_rejects_a_symlinked_parent_directory(self) -> None:
        (self.root / "vendor").symlink_to(self.outside, target_is_directory=True)
        for path in ("vendor/secret.txt", "vendor/not-there-yet.txt", "vendor"):
            with self.subTest(path=path), self.assertRaises(PermissionDenied):
                resolve_within(self.root, path)

    def test_allows_a_symlink_that_stays_inside(self) -> None:
        (self.root / "alias").symlink_to(self.root / "src", target_is_directory=True)
        self.assertEqual(resolve_within(self.root, "alias/a.py"), self.root / "src" / "a.py")

    def test_root_given_through_a_symlink_still_confines(self) -> None:
        link = self.outside / "repo-link"
        link.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(resolve_within(link, "src/a.py"), self.root / "src" / "a.py")
        with self.assertRaises(PermissionDenied):
            resolve_within(link, "../secret.txt")

    def test_nul_bytes_are_refused_as_permission_errors(self) -> None:
        with self.assertRaises(PermissionDenied):
            resolve_within(self.root, "a\x00b")

    def test_symlink_loop_never_escapes_or_raises_another_error(self) -> None:
        (self.root / "loop").symlink_to(self.root / "loop")
        try:
            resolved = resolve_within(self.root, "loop/x")
        except PermissionDenied:
            return  # Python <= 3.12 reports the loop; that is refused.
        self.assertIn(self.root, resolved.parents)

    def test_message_is_localized(self) -> None:
        with i18n.use_language("pt-BR"), self.assertRaises(PermissionDenied) as caught:
            resolve_within(self.root, "..")
        self.assertIn("fora da raiz", caught.exception.message)


class IsProtectedTests(PathCase):
    def test_protected_names_match_at_any_depth(self) -> None:
        for path in (
            ".git",
            ".git/config",
            "./.git/hooks/pre-commit",
            SECRET_FILE,
            f"src/{SECRET_FILE}",
            "sub/.git/config",
            f"src/../{SECRET_FILE}",
            str(self.root / ".git" / "HEAD"),
        ):
            with self.subTest(path=path):
                self.assertTrue(is_protected(path, self.root, PROTECTED))

    def test_similar_names_are_not_protected(self) -> None:
        for path in (
            ".gitignore",
            ".github/workflows/ci.yml",
            "src/a.py",
            "environment.py",
            f"{SECRET_FILE}.example",
            "src/git",
            ".",
            "repo.git",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_protected(path, self.root, PROTECTED))

    def test_names_match_case_insensitively(self) -> None:
        self.assertTrue(is_protected(".GIT/config", self.root, PROTECTED))
        self.assertTrue(is_protected(SECRET_FILE.upper(), self.root, PROTECTED))

    def test_symlink_to_a_protected_file_is_protected(self) -> None:
        (self.root / "harmless.txt").symlink_to(self.root / SECRET_FILE)
        (self.root / "meta").symlink_to(self.root / ".git", target_is_directory=True)
        self.assertTrue(is_protected("harmless.txt", self.root, PROTECTED))
        self.assertTrue(is_protected("meta/config", self.root, PROTECTED))

    def test_wildcards_and_located_entries(self) -> None:
        patterns = (SECRET_FILE + "*", "secrets/prod", str(self.outside))
        self.assertTrue(is_protected(f"{SECRET_FILE}.local", self.root, patterns))
        self.assertTrue(is_protected("secrets/prod/key.pem", self.root, patterns))
        self.assertTrue(is_protected("secrets/prod", self.root, patterns))
        self.assertFalse(is_protected("secrets/dev/key.pem", self.root, patterns))
        self.assertFalse(is_protected("other/secrets/prod", self.root, patterns))
        self.assertTrue(is_protected(str(self.outside / "secret.txt"), self.root, patterns))
        self.assertTrue(is_protected("../outside/secret.txt", self.root, patterns))

    def test_a_root_that_lives_under_a_protected_name_does_not_protect_everything(self) -> None:
        nested = self.root / ".git" / "worktree"
        nested.mkdir()
        self.assertFalse(is_protected("a.py", nested, PROTECTED))

    def test_empty_inputs_and_odd_values_do_not_raise(self) -> None:
        self.assertFalse(is_protected("src/a.py", self.root, ()))
        self.assertFalse(is_protected("src/a.py", self.root, ("",)))
        self.assertFalse(is_protected("-rf", self.root, PROTECTED))
        self.assertFalse(is_protected("x" * 5000, self.root, PROTECTED))
        self.assertIsInstance(is_protected("a\x00b", self.root, PROTECTED), bool)

    def test_relative_root_is_resolved_from_the_process_directory(self) -> None:
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.root)
        self.assertTrue(is_protected(".git/config", ".", PROTECTED))
        self.assertFalse(is_protected("src/a.py", ".", PROTECTED))


if __name__ == "__main__":
    unittest.main()
