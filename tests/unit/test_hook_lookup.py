"""Hook run lookup and destructive forms the second independent pass found silent."""

from __future__ import annotations

import json
import time
from unittest import mock

from tests.unit.test_hooks import NO_RUN, WEV, HookCase
from wev_skills.adapters.claude_code import bash_guard

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
        self.assertEqual(self.without_run("rm -rf build", self.work.parent), ASK)
        self.assertIsNone(self.decision("ls", self.work.parent))

    def test_a_harmless_command_on_a_parent_stays_unasked(self) -> None:
        self.assertIsNone(self.decision(f"ls {self.work.parent}", self.elsewhere))

    def test_an_unrelated_path_finds_no_run(self) -> None:
        self.assertEqual(self.without_run(f"rm -rf {self.elsewhere}/build", self.elsewhere), ASK)


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

    def test_a_command_without_variables_elsewhere_gets_the_default_policy(self) -> None:
        for line in ("rm -rf build", "ls *.py"):
            with self.subTest(line=line):
                self.assertEqual(self.without_run(line, self.elsewhere), ASK)
        self.assertIsNone(self.decision("cat notes.txt", self.elsewhere))

    def test_no_registered_run_means_the_default_policy(self) -> None:
        self.wev("run", "finish")
        found = self.bash("rm -rf $TARGET", self.elsewhere)
        assert found is not None
        self.assertEqual(self.without_run("rm -rf $TARGET", self.elsewhere), ASK)
        self.assertNotIn("cannot be known", found["reason"])


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


class NoRunTests(HookCase):
    """No run anywhere: the Bash guard judges under the built-in defaults (execute, medium)."""

    LOOSE = {"permissions": {"protected_paths": [], "allowed_commands": ["rm", "git", "cat"]}}

    def setUp(self) -> None:
        super().setUp()
        (self.work / DOT_ENV).write_text("K=v\n", encoding="utf-8")

    def test_destructive_commands_ask_without_a_run(self) -> None:
        for line in ("rm -rf / --no-preserve-root", "git push --force origin main",
                     "rm -rf / --no-preserve-root; git push --force origin main"):  # fmt: skip
            with self.subTest(line=line):
                found = self.bash(line)
                assert found is not None
                self.assertEqual(found["decision"], ASK)
                self.assertIn(NO_RUN, found["reason"])

    def test_a_read_only_command_stays_silent(self) -> None:
        for line in ("git status", "ls -la"):
            with self.subTest(line=line):
                self.assertIsNone(self.bash(line))

    def test_protected_paths_are_denied_as_in_a_run(self) -> None:
        for line in ("cat .git/config", f"cat {DOT_ENV}", "echo x > .wev/approvals.json"):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), DENY)
        self.assertEqual(self.decision("cat ../.git/config", self.work / "src"), DENY)

    def test_engine_commands_keep_their_classification(self) -> None:
        for args in ("run start --objective x --mode execute", "approval grant apr-1",
                     "--config /tmp/a.json run status", "jev ask --questions q.json --state x",
                     "jev batch --questions q.json --items i.jsonl --out r.jsonl"):  # fmt: skip
            with self.subTest(args=args):
                self.assertEqual(self.decision(f"{WEV} {args}"), ASK)
        self.assertIsNone(self.decision(f"{WEV} jev status"))

    def test_the_jev_reason_names_the_service(self) -> None:
        found = self.bash(f"{WEV} jev ask --questions q.json --state-file notes.txt")
        assert found is not None
        self.assertIn("JEV service", found["reason"])

    def test_a_repository_configuration_cannot_loosen_the_guard(self) -> None:
        lines = ("cat .git/config", f"cat {DOT_ENV}", "rm -rf build", "git push -f origin main")
        before = {line: self.bash(line) for line in lines}
        (self.work / "wev.config.json").write_text(json.dumps(self.LOOSE), encoding="utf-8")
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(self.bash(line), before[line])
        self.start()  # a run pins the file, and then it does apply
        self.assertIsNone(self.decision("cat .git/config"))

    def test_an_internal_error_without_a_run_asks(self) -> None:
        with mock.patch.object(bash_guard, "decide_command", side_effect=RuntimeError("x")):
            found = self.bash("ls")
        assert found is not None
        self.assertEqual(found["decision"], ASK)
        self.assertIn("RuntimeError", found["reason"])
        self.assertIn(NO_RUN, found["reason"])

    def test_the_answer_follows_the_language_without_a_run(self) -> None:
        payload = {"cwd": str(self.work), "tool_name": "Bash",
                   "tool_input": {"command": "rm -rf build"}}  # fmt: skip
        out = self.hook("pre-tool-use", payload, "--lang", "pt-BR")[1]
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("sem execução", reason)

    def test_a_long_line_without_a_run_is_judged_quickly(self) -> None:
        words = " ".join(f"d/{index}" for index in range(1900))
        started = time.monotonic()
        self.assertIsNone(self.bash(f"nohup ls {words}"))
        self.assertLess(time.monotonic() - started, 5.0)
