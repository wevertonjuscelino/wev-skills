from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wev_skills.core import fsutil

PERMISSIVE_UMASK = 0o022


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class PermissiveUmaskCase(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name).resolve()
        previous = os.umask(PERMISSIVE_UMASK)
        self.addCleanup(os.umask, previous)


class EnsurePrivateDirTests(PermissiveUmaskCase):
    def test_every_created_directory_is_private_including_intermediate_ones(self) -> None:
        leaf = self.tmp / "a" / "b" / "c"

        result = fsutil.ensure_private_dir(leaf)

        self.assertEqual(result, leaf)
        for created in (self.tmp / "a", self.tmp / "a" / "b", leaf):
            with self.subTest(created=created.name):
                self.assertEqual(mode_of(created), fsutil.PRIVATE_DIR_MODE)

    def test_existing_directories_keep_their_mode(self) -> None:
        shared = self.tmp / "shared"
        shared.mkdir(mode=0o755)
        os.chmod(shared, 0o755)
        existing_leaf = shared / "kept"
        existing_leaf.mkdir()
        os.chmod(existing_leaf, 0o750)

        fsutil.ensure_private_dir(existing_leaf)
        fsutil.ensure_private_dir(shared / "new" / "leaf")

        self.assertEqual(mode_of(shared), 0o755)
        self.assertEqual(mode_of(existing_leaf), 0o750)
        self.assertEqual(mode_of(shared / "new"), fsutil.PRIVATE_DIR_MODE)
        self.assertEqual(mode_of(shared / "new" / "leaf"), fsutil.PRIVATE_DIR_MODE)

    def test_is_private_even_under_a_umask_that_strips_owner_bits(self) -> None:
        os.umask(0o277)
        leaf = self.tmp / "x" / "y"

        fsutil.ensure_private_dir(leaf)

        self.assertEqual(mode_of(self.tmp / "x"), fsutil.PRIVATE_DIR_MODE)
        self.assertEqual(mode_of(leaf), fsutil.PRIVATE_DIR_MODE)

    def test_repeated_calls_and_relative_paths_work(self) -> None:
        leaf = self.tmp / "again"
        fsutil.ensure_private_dir(leaf)
        fsutil.ensure_private_dir(leaf)
        self.assertEqual(mode_of(leaf), fsutil.PRIVATE_DIR_MODE)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.tmp)
        fsutil.ensure_private_dir(Path("rel") / "leaf")
        self.assertEqual(mode_of(self.tmp / "rel"), fsutil.PRIVATE_DIR_MODE)
        self.assertEqual(mode_of(self.tmp / "rel" / "leaf"), fsutil.PRIVATE_DIR_MODE)

    def test_a_file_in_the_way_is_an_error(self) -> None:
        blocker = self.tmp / "file"
        blocker.write_text("x", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            fsutil.ensure_private_dir(blocker)
        with self.assertRaises(OSError):
            fsutil.ensure_private_dir(blocker / "child")

    def test_callers_create_private_parents(self) -> None:
        target = self.tmp / "state" / "deep" / "file.json"
        fsutil.atomic_write_text(target, "{}")
        self.assertEqual(mode_of(self.tmp / "state"), fsutil.PRIVATE_DIR_MODE)
        self.assertEqual(mode_of(target), fsutil.PRIVATE_FILE_MODE)


class LockFileModeTests(PermissiveUmaskCase):
    def lock_path(self, target: Path) -> Path:
        return target.with_name(f".{target.name}.lock")

    def test_new_lock_file_is_private(self) -> None:
        target = self.tmp / "state.json"

        with fsutil.locked(target):
            self.assertEqual(mode_of(self.lock_path(target)), fsutil.PRIVATE_FILE_MODE)

        self.assertEqual(mode_of(self.lock_path(target)), fsutil.PRIVATE_FILE_MODE)

    def test_existing_permissive_lock_file_is_tightened(self) -> None:
        target = self.tmp / "state.json"
        lock = self.lock_path(target)
        lock.write_text("", encoding="utf-8")
        os.chmod(lock, 0o644)

        with fsutil.locked(target):
            pass

        self.assertEqual(mode_of(lock), fsutil.PRIVATE_FILE_MODE)

    def test_existing_stricter_lock_file_is_not_loosened(self) -> None:
        target = self.tmp / "state.json"
        lock = self.lock_path(target)
        lock.write_text("", encoding="utf-8")
        os.chmod(lock, 0o400)
        self.addCleanup(os.chmod, lock, 0o600)

        try:
            with fsutil.locked(target):
                pass
        except PermissionError:
            pass  # a read-only lock file cannot be opened for writing; the mode still holds

        self.assertEqual(mode_of(lock), 0o400)

    def test_append_line_leaves_private_lock_and_file(self) -> None:
        target = self.tmp / "logs" / "audit.jsonl"

        fsutil.append_line(target, "one")
        fsutil.append_line(target, "two")

        self.assertEqual(target.read_text(encoding="utf-8"), "one\ntwo\n")
        self.assertEqual(mode_of(target), fsutil.PRIVATE_FILE_MODE)
        self.assertEqual(mode_of(self.lock_path(target)), fsutil.PRIVATE_FILE_MODE)
        self.assertEqual(mode_of(self.tmp / "logs"), fsutil.PRIVATE_DIR_MODE)

    def test_lock_still_excludes_and_releases(self) -> None:
        target = self.tmp / "state.json"
        with fsutil.locked(target):
            pass
        with fsutil.locked(target, timeout=0.2):
            pass

    def test_append_file_is_private_before_content_is_flushed(self) -> None:
        target = self.tmp / "audit.jsonl"
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    os.chmod(target, 0o644)
                with patch.object(fsutil.os, "fsync") as sync:
                    sync.side_effect = lambda fd: self.assertEqual(
                        stat.S_IMODE(os.fstat(fd).st_mode), fsutil.PRIVATE_FILE_MODE
                    )
                    fsutil.append_line(target, "private event")
                sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
