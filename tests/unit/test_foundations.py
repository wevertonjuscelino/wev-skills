"""Small building blocks added for the evidence and pinning rules."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import wev_skills
from wev_skills.config import (
    CONFIG_FILE_NAME,
    SOURCE_DEFAULTS,
    Config,
    config_digest,
    find_repo_root,
    resolve_config,
)
from wev_skills.core import fsutil
from wev_skills.core.contracts import RiskLevel, higher_risk, risk_rank
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.core.fingerprint import tree_fingerprint
from wev_skills.core.ports import SubprocessRunner
from wev_skills.core.textsafe import clean_data, clean_text
from wev_skills.verification.trivial import is_trivial

SRC = str(Path(wev_skills.__file__).resolve().parents[1])
HOLD_LOCK = """
import sys, time
from pathlib import Path
from wev_skills.core import fsutil
with fsutil.locked(Path(sys.argv[1])):
    print("held", flush=True)
    time.sleep(30)
"""


class TmpCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()


class RiskHelperTests(unittest.TestCase):
    def test_one_order_for_every_comparison(self) -> None:
        self.assertLess(risk_rank(RiskLevel.LOW), risk_rank(RiskLevel.MEDIUM))
        self.assertLess(risk_rank(RiskLevel.MEDIUM), risk_rank(RiskLevel.HIGH))
        self.assertIs(higher_risk(RiskLevel.LOW, RiskLevel.HIGH, RiskLevel.MEDIUM), RiskLevel.HIGH)
        self.assertIs(higher_risk(RiskLevel.MEDIUM), RiskLevel.MEDIUM)

    def test_no_second_risk_table_in_owned_modules(self) -> None:
        owned = ("core", "decisions", "models", "state", "guards", "verification", "evaluation")
        tables = []
        for name in owned:
            for path in (Path(SRC) / "wev_skills" / name).rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                if "RiskLevel.LOW: 0" in text:
                    tables.append(path.name)
        self.assertEqual(tables, ["contracts.py"])


class TextSafeTests(unittest.TestCase):
    def test_escape_sequences_and_control_characters_are_removed(self) -> None:
        hostile = "ok \x1b[31mred\x1b[0m \x1b]0;title\x07 bell\x07 nul\x00 ‮evil‬ done"
        self.assertEqual(clean_text(hostile), "ok red bell nul evil done")

    def test_newlines_collapse_and_long_text_is_cut_visibly(self) -> None:
        self.assertEqual(clean_text("a\n\n  b\r\n\tc"), "a b c")
        cut = clean_text("x" * 50, 10)
        self.assertEqual((len(cut), cut[-3:]), (10, "..."))

    def test_clean_data_walks_nested_values(self) -> None:
        cleaned = clean_data({"a": ["x\ny", {"b": "\x1b[1mz"}], "n": 3})
        self.assertEqual(cleaned, {"a": ["x y", {"b": "z"}], "n": 3})


class TrivialCheckTests(unittest.TestCase):
    def test_no_ops_are_trivial(self) -> None:
        for command in (
            ["true"],
            [":"],
            ["/usr/bin/true"],
            ["echo", "all", "good"],
            ["printf", "ok\\n"],
            ["test", "1", "-eq", "1"],
            ["[", "a", "=", "a", "]"],
            ["test", "-n", "x"],
            ["sh", "-c", "exit 0"],
            ["bash", "-c", "true; echo done && exit"],
            ["python3", "-c", "pass"],
            ["python3", "-c", "import sys; sys.exit(0)"],
            ["env", "FOO=1", "true"],
        ):
            self.assertTrue(is_trivial(command), command)

    def test_real_checks_are_not_trivial(self) -> None:
        for command in (
            ["make", "test"],
            ["python3", "-m", "unittest"],
            ["test", "-f", "greeting.txt"],
            ["sh", "-c", "make test"],
            ["python3", "-c", "import app; app.check()"],
            ["git", "diff", "--stat"],
        ):
            self.assertFalse(is_trivial(command), command)


class ConfigResolutionTests(TmpCase):
    def test_repo_root_is_the_nearest_git_ancestor_else_the_directory(self) -> None:
        (self.tmp / ".git").mkdir()
        nested = self.tmp / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(find_repo_root(nested), self.tmp)
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(find_repo_root(plain), Path(plain).resolve())

    def test_explicit_file_then_root_file_then_defaults(self) -> None:
        defaults = resolve_config(None, self.tmp)
        self.assertEqual((defaults.source, defaults.config), (SOURCE_DEFAULTS, Config()))
        root_file = self.tmp / CONFIG_FILE_NAME
        root_file.write_text(json.dumps({"limits": {"max_attempts": 5}}), encoding="utf-8")
        found = resolve_config(None, self.tmp)
        self.assertEqual((found.source, found.config.limits.max_attempts), (str(root_file), 5))
        other = self.tmp / "other.json"
        other.write_text(json.dumps({"limits": {"max_attempts": 7}}), encoding="utf-8")
        explicit = resolve_config(str(other), self.tmp)
        self.assertEqual(explicit.config.limits.max_attempts, 7)
        self.assertEqual(explicit.source, str(other))
        self.assertNotEqual(explicit.digest, found.digest)
        self.assertEqual(found.digest, config_digest(found.config))

    def test_resolved_config_is_as_written_without_a_cwd_dependent_path(self) -> None:
        resolved = resolve_config(None, self.tmp)
        self.assertEqual(resolved.config.permissions.protected_paths, (".git", ".env"))

    def test_new_settings_have_defaults_and_are_validated(self) -> None:
        self.assertTrue(Config().harness.baseline_checks)
        self.assertEqual(Config().limits.max_polling_commands, 60)
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps({"limits": {"max_polling_commands": 0}}), encoding="utf-8")
        with self.assertRaises(ValidationError):
            resolve_config(str(bad), self.tmp)


class LockTimeoutTests(TmpCase):
    def test_a_held_lock_times_out_with_a_clear_error(self) -> None:
        target = self.tmp / "state.json"
        env = {**os.environ, "PYTHONPATH": SRC}
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLD_LOCK, str(target)],
            stdout=subprocess.PIPE,
            env=env,
            text=True,
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        assert holder.stdout is not None
        self.addCleanup(holder.stdout.close)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        with self.assertRaises(StateConflict) as caught, fsutil.locked(target, timeout=0.2):
            self.fail("the lock was taken while another process held it")
        self.assertEqual(caught.exception.code, "lock_timeout")
        self.assertIn(str(target), caught.exception.message)


class StateDirIgnoreTests(TmpCase):
    def test_ignore_file_is_written_once_and_never_overwritten(self) -> None:
        state_dir = self.tmp / ".wev"
        fsutil.ensure_ignored_dir(state_dir)
        ignore = state_dir / ".gitignore"
        self.assertEqual(ignore.read_text(encoding="utf-8"), "*\n")
        ignore.write_text("custom\n", encoding="utf-8")
        fsutil.ensure_ignored_dir(state_dir)
        self.assertEqual(ignore.read_text(encoding="utf-8"), "custom\n")


@unittest.skipUnless(shutil.which("git"), "needs git")
class FingerprintTests(TmpCase):
    def git(self, *args: str) -> None:
        identity = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")
        subprocess.run(["git", *identity, *args], cwd=self.tmp, check=True, capture_output=True)

    def fingerprint(self) -> str:
        return tree_fingerprint(SubprocessRunner(), str(self.tmp), (".wev",))

    def test_changes_are_seen_and_the_state_directory_is_not(self) -> None:
        self.git("init", "-q")
        (self.tmp / "a.txt").write_text("one\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        clean = self.fingerprint()
        self.assertEqual(self.fingerprint(), clean)
        (self.tmp / ".wev").mkdir()
        (self.tmp / ".wev" / "state.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.fingerprint(), clean, "state directory must not count")
        (self.tmp / "a.txt").write_text("two\n", encoding="utf-8")
        edited = self.fingerprint()
        self.assertNotEqual(edited, clean)
        (self.tmp / "new.txt").write_text("x", encoding="utf-8")
        untracked = self.fingerprint()
        self.assertNotEqual(untracked, edited)
        (self.tmp / "new.txt").write_text("longer text", encoding="utf-8")
        self.assertNotEqual(self.fingerprint(), untracked, "untracked content must count")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "work")
        self.assertNotEqual(self.fingerprint(), clean, "a commit is a change too")

    def test_outside_a_repository_file_changes_still_show(self) -> None:
        (self.tmp / "a.txt").write_text("one\n", encoding="utf-8")
        before = self.fingerprint()
        self.assertTrue(before.startswith("fs:"))
        (self.tmp / ".wev").mkdir()
        (self.tmp / ".wev" / "x").write_text("x", encoding="utf-8")
        self.assertEqual(self.fingerprint(), before)
        (self.tmp / "a.txt").write_text("three!\n", encoding="utf-8")
        self.assertNotEqual(self.fingerprint(), before)


if __name__ == "__main__":
    unittest.main()
