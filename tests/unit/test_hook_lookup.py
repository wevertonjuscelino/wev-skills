"""Hook run lookup and destructive forms the second independent pass found silent."""

from __future__ import annotations

from tests.unit.test_hooks import HookCase

DOT_ENV = "." + "env"
ASK, DENY = "ask", "deny"


class LookupCase(HookCase):
    def setUp(self) -> None:
        super().setUp()
        self.start()
        self.elsewhere = self.work.parent / "elsewhere"
        self.elsewhere.mkdir()
        (self.work / DOT_ENV).write_text("K=v\n", encoding="utf-8")
        (self.work / "src" / "b.py").write_text("b\n", encoding="utf-8")


class ParentPathTests(LookupCase):
    def test_a_path_that_is_a_parent_of_the_run_root_finds_the_run(self) -> None:
        parent = self.work.parent
        for line in (f"rm -rf {parent}", f"rm -rf {parent}/", f"rm -rf {parent.parent}"):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line, self.elsewhere), ASK)
        self.assertEqual(self.decision("rm -rf ..", self.elsewhere), ASK)

    def test_the_working_directory_alone_is_not_a_target(self) -> None:
        self.assertIsNone(self.decision("rm -rf build", self.work.parent))
        self.assertIsNone(self.decision("ls", self.work.parent))

    def test_a_harmless_command_on_a_parent_stays_unasked(self) -> None:
        self.assertIsNone(self.decision(f"ls {self.work.parent}", self.elsewhere))

    def test_an_unrelated_path_finds_no_run(self) -> None:
        self.assertIsNone(self.decision(f"rm -rf {self.elsewhere}/build", self.elsewhere))


class UnknownTargetTests(LookupCase):
    def test_a_variable_in_a_path_word_asks_while_any_run_is_registered(self) -> None:
        for line in (
            "rm -rf $TARGET",
            'rm -rf "$HOME/x"',
            "cat ${DIR}/file",
            "D=/somewhere; rm -rf $D",
            "$TOOL --version",
        ):
            with self.subTest(line=line):
                found = self.bash(line, self.elsewhere)
                assert found is not None
                self.assertEqual(found["decision"], ASK)
                self.assertIn("cannot be known", found["reason"])

    def test_a_command_without_variables_elsewhere_stays_silent(self) -> None:
        for line in ("rm -rf build", "ls *.py", "cat notes.txt"):
            with self.subTest(line=line):
                self.assertIsNone(self.decision(line, self.elsewhere))

    def test_no_registered_run_means_silence(self) -> None:
        self.wev("run", "finish")
        self.assertIsNone(self.decision("rm -rf $TARGET", self.elsewhere))


class DestructiveFormTests(LookupCase):
    def test_the_reported_forms_ask(self) -> None:
        for line in (
            "rm --recursiv src",
            "rm --forc src/b.py",
            "rm --rec --for src",
            "git rm -r src",
            "git rm -rf src",
            "git rm --force src/b.py",
            "git clean -d",
            "git clean -x",
            "git clean -X",
            "git clean -fdx",
            "git clean -e keep -d",
            "git clean",
            "rsync --delete /tmp/empty/ src/",
            "rsync -a --delete-after /tmp/empty/ src/",
            "rsync --del /tmp/empty/ src/",
            "rsync --remove-source-files src/ /tmp/out/",
        ):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), ASK)

    def test_a_dry_run_of_git_clean_is_not_destructive(self) -> None:
        self.assertIsNone(self.decision("git clean -n"))
        self.assertIsNone(self.decision("git clean --dry-run -d"))


class RecursiveReaderTests(LookupCase):
    def test_a_recursive_reader_over_a_directory_holding_a_protected_file_is_stopped(self) -> None:
        for line in (
            "grep -r K .",
            "grep -R K .",
            "grep --recursive K .",
            f"grep -r K {self.work}",
            "rg --hidden K",
            "rg -uu K .",
            "find . -type f",
            "find . -name '*.py'",
            "tar czf /tmp/out.tgz .",
            "zip -r /tmp/out.zip .",
            "cp -r . /tmp/copy",
            "cp -a . /tmp/copy",
            "rsync -a . /tmp/copy",
            "nohup tar cf /tmp/out.tar .",
        ):
            with self.subTest(line=line):
                self.assertIn(self.decision(line), (ASK, DENY))

    def test_the_reason_names_the_directory_and_the_protected_path(self) -> None:
        found = self.bash("grep -r K .")
        assert found is not None
        self.assertIn("protected", found["reason"])

    def test_a_direct_read_is_still_denied(self) -> None:
        self.assertEqual(self.decision(f"cat {DOT_ENV}"), DENY)
        self.assertEqual(self.decision(f"grep K {DOT_ENV}"), DENY)

    def test_a_directory_without_protected_files_is_left_alone(self) -> None:
        for line in (
            "grep -r b src",
            "rg b src",
            "rg b",
            "find src -name '*.py'",
            "tar czf /tmp/out.tgz src",
            "cp -r src /tmp/copy",
            "grep K src/b.py",
            "ls",
        ):
            with self.subTest(line=line):
                self.assertIsNone(self.decision(line))

    def test_a_nested_protected_file_counts(self) -> None:
        (self.work / "src" / "pkg" / DOT_ENV).write_text("K=v\n", encoding="utf-8")
        for line in ("grep -r K src", "cp -r src /tmp/copy", "tar cf /tmp/o.tar src/pkg"):
            with self.subTest(line=line):
                self.assertIn(self.decision(line), (ASK, DENY))
        self.assertIsNone(self.decision("rg K src"))
        self.assertIn(self.decision("rg --hidden K src"), (ASK, DENY))
