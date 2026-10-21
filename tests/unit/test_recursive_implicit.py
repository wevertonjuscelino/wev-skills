"""Recursive readers: tilde operands and the implicit working directory."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills.security import recursive

GIT = ".git"


class ReaderCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve() / "repo"
        (self.work / GIT).mkdir(parents=True)
        (self.work / GIT / "config").write_text("x\n", encoding="utf-8")
        (self.work / "src").mkdir()

    def hit(self, *argv: str, cwd: Path | None = None) -> tuple[str, str] | None:
        return recursive.protected_inside(argv, str(cwd or self.work), (GIT,))


class TildeOperandTests(ReaderCase):
    def test_tilde_plus_is_read_as_the_working_directory(self) -> None:
        self.assertIsNotNone(self.hit("rg", "--hidden", "k", "~+"))
        self.assertIsNotNone(self.hit("grep", "-r", "k", "~+/"))

    def test_tilde_minus_is_read_as_oldpwd(self) -> None:
        elsewhere = self.work / "src"
        with mock.patch.dict(os.environ, {"OLDPWD": str(self.work)}):
            self.assertIsNotNone(self.hit("grep", "-r", "k", "~-", cwd=elsewhere))

    def test_a_plain_tilde_still_expands_to_home(self) -> None:
        with mock.patch.dict(os.environ, {"HOME": str(self.work)}):
            self.assertIsNotNone(self.hit("grep", "-r", "k", "~", cwd=self.work / "src"))


class ImplicitDirectoryTests(ReaderCase):
    def test_a_pattern_naming_an_existing_file_keeps_the_implicit_directory(self) -> None:
        (self.work / "secret").write_text("s\n", encoding="utf-8")
        self.assertIsNotNone(self.hit("rg", "--hidden", "secret"))
        self.assertIsNotNone(self.hit("grep", "-r", "secret"))

    def test_a_pattern_naming_an_existing_directory_keeps_the_implicit_directory(self) -> None:
        self.assertIsNotNone(self.hit("grep", "-r", "src"))

    def test_an_explicit_path_operand_replaces_the_implicit_directory(self) -> None:
        self.assertIsNone(self.hit("rg", "--hidden", "k", "src"))
        self.assertIsNone(self.hit("grep", "-r", "k", "src"))

    def test_rg_without_hidden_still_skips_the_hidden_entry(self) -> None:
        (self.work / "secret").write_text("s\n", encoding="utf-8")
        self.assertIsNone(self.hit("rg", "secret"))


if __name__ == "__main__":
    unittest.main()
