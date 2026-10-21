"""Edges of the protected-path checks: symlinked ancestors, case-insensitive file systems,
an abbreviated ``--target-directory`` and the ``~+`` and ``~-`` tilde forms."""

from __future__ import annotations

import getpass
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from tests.unit.test_hook_trust import ASK, DENY
from tests.unit.test_hook_uproot import PLAN, SituationTests, UprootCase
from wev_skills.config import Config
from wev_skills.core import wiring
from wev_skills.core.contracts import Mode, PermissionOutcome, RiskLevel
from wev_skills.security import paths, recursive, uproot
from wev_skills.security.paths import glob_may_match_protected, is_protected

DOT_ENV = "." + "env"
FOLD = "wev_skills.security.paths.CASE_INSENSITIVE"


def volume_folds_case(directory: Path) -> bool:
    """Whether ``directory``'s file system reaches a file under its upper-case spelling."""
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        probe = Path(tmp) / "case-probe"
        probe.write_text("x\n", encoding="utf-8")
        return (Path(tmp) / "CASE-PROBE").exists()


class SymlinkedAncestorTests(UprootCase, SituationTests):
    """``~/.local`` is a symlink to a directory elsewhere, as dotfile managers set it up."""

    def check(self, situation: str) -> None:
        real = self.home.parent / "dotfiles-local"
        real.mkdir()
        (self.home / ".local").symlink_to(real, target_is_directory=True)
        super().check(situation)

    def rows(self) -> dict[str, str]:
        return {"mv ~/.local /tmp/x": ASK, "rm ~/.local": ASK, "unlink ~/.local": ASK}

    def plan_rows(self) -> dict[str, str]:
        return dict.fromkeys(self.rows(), DENY)


class AbbreviatedTargetTests(UprootCase, SituationTests):
    """GNU getopt accepts any unambiguous prefix of ``--target-directory``."""

    def rows(self) -> dict[str, str]:
        regdir = self.regdir
        return {
            f"mv --t=/tmp/x {regdir}": DENY,
            f"mv --targ /tmp/x {regdir}": DENY,
            "mv --t=/tmp/x ~/.local": ASK,
            "mv --targ /tmp/x ~/.local": ASK,
            "mv --ta=/tmp/x ~/.local/state": ASK,
            "mv --target-directory /tmp/x ~/.local": ASK,
        }

    def plan_rows(self) -> dict[str, str]:
        return dict.fromkeys(self.rows(), DENY)


class AbbreviatedTargetDetailTests(UprootCase):
    def test_only_a_prefix_of_three_characters_or_more_names_the_target(self) -> None:
        for arg in ("--t", "--ta=/x", "--target-dir", "--target-directory=/x", "-t", "-ft"):
            with self.subTest(arg=arg):
                self.assertTrue(uproot._names_target([arg, "a"]))
        for arg in ("--", "-f", "--verbose", "--no-target-directory"):
            with self.subTest(arg=arg):
                self.assertFalse(uproot._names_target([arg, "a"]))


class CaseFoldingTests(UprootCase):
    """On darwin and Windows a different case reaches the same file; on Linux it does not."""

    def decide_with(self, folding: bool, line: str) -> str | None:
        with mock.patch(FOLD, folding, create=True):
            return self.decision(line)

    def test_protected_names_deny_in_any_case_on_every_platform(self) -> None:
        (self.work / ".git" / "config").write_text("x\n", encoding="utf-8")
        for line in ("cat .GIT/config", "cat .Env", "cat .E" + DOT_ENV[2:].upper()):
            for folding in (True, False):
                with self.subTest(line=line, folding=folding):
                    self.assertEqual(self.decide_with(folding, line), DENY)

    def test_moving_a_protected_name_in_another_case_is_refused(self) -> None:
        self.assertEqual(self.decide_with(True, "mv .GIT x"), DENY)
        self.start(mode=PLAN)
        self.assertEqual(self.decide_with(True, "mv .GIT x"), DENY)

    def test_a_located_entry_in_another_case(self) -> None:
        self.regdir.mkdir(parents=True)
        rows = {
            "cat ~/.LOCAL/state/wev-skills/active-runs.json": DENY,
            f"cat {str(self.regdir).upper()}/active-runs.json": DENY,
            "mv ~/.LOCAL/state /tmp/x": ASK,
            "mv ~/.local/STATE /tmp/x": ASK,
        }
        for line, wanted in rows.items():
            with self.subTest(line=line, folding=True):
                self.assertEqual(self.decide_with(True, line), wanted)
            with self.subTest(line=line, folding=False):
                self.assertIsNone(self.decide_with(False, line))

    def test_a_located_entry_found_only_on_the_volume(self) -> None:
        """A case-differing match is accepted only when the file system confirms it."""
        self.regdir.mkdir(parents=True)
        line = "grep -r x ~/.LOCAL"
        folded = ASK if volume_folds_case(self.home) else None
        with self.subTest(line=line, folding=True):
            self.assertEqual(self.decide_with(True, line), folded)
        with self.subTest(line=line, folding=False):
            self.assertIsNone(self.decide_with(False, line))

    def test_is_protected_folds_located_entries_only_when_the_platform_does(self) -> None:
        entry = str(self.work.parent / "Keys" / "id")
        target = self.work.parent / "keys" / "ID"
        with mock.patch(FOLD, True, create=True):
            self.assertTrue(is_protected(target, self.work, (entry,)))
            self.assertTrue(glob_may_match_protected("../KEYS/i*", self.work, ("../keys/id",)))
        with mock.patch(FOLD, False, create=True):
            self.assertFalse(is_protected(target, self.work, (entry,)))
            self.assertFalse(glob_may_match_protected("../KEYS/i*", self.work, ("../keys/id",)))

    def test_the_flag_follows_the_platform(self) -> None:
        expected = sys.platform == "darwin" or sys.platform.startswith("win")
        self.assertEqual(paths.CASE_INSENSITIVE, expected)


class TildeFormTests(UprootCase):
    def test_tilde_plus_is_the_working_directory(self) -> None:
        (self.work / ".git" / "config").write_text("x\n", encoding="utf-8")
        self.assertEqual(self.decision("cat ~+/.git/config"), DENY)
        self.regdir.mkdir(parents=True)
        line = "cat ~+/.local/state/wev-skills/active-runs.json"
        self.assertEqual(self.decision(line, self.home), DENY)
        self.assertTrue(is_protected("~+/x", self.work, (str(self.work / "x"),)))

    def test_tilde_minus_is_oldpwd_when_set(self) -> None:
        secret = str(self.home / "secret")
        with mock.patch.dict(os.environ, {"OLDPWD": str(self.home)}):
            self.assertTrue(is_protected("~-/secret", self.work, (secret,)))
            self.assertTrue(is_protected("~-", self.work, (str(self.home),)))

    def test_tilde_minus_without_oldpwd_is_left_to_the_shell_check(self) -> None:
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("OLDPWD", None)
            self.assertFalse(is_protected("~-/secret", self.work, (str(self.home / "secret"),)))
            self.assertEqual(self.decision("mv ~-/x y"), ASK)

    def test_uproot_does_not_expand_another_users_home(self) -> None:
        user = getpass.getuser()
        argv = ["mv", f"~{user}/.local", "/tmp/x"]
        under = os.path.join(os.path.expanduser(f"~{user}"), ".local", "state", "wev-skills")
        self.assertIsNone(uproot.uprooted(argv, str(self.work), (under,)))
        self.assertEqual(self.decision(f"mv ~{user}/.local /tmp/x"), ASK)

    def test_uproot_expands_the_forms_paths_expands(self) -> None:
        protected = (str(self.regdir),)
        hit = uproot.uprooted(["mv", "~+/.local", "/tmp/x"], str(self.home), protected)
        self.assertIsNotNone(hit)
        with mock.patch.dict(os.environ, {"OLDPWD": str(self.home)}):
            hit = uproot.uprooted(["rm", "~-/.local"], str(self.work), protected)
        self.assertIsNotNone(hit)


class FoldedSliceTests(UprootCase):
    """``casefold`` can lengthen a path (``ß`` becomes ``ss``): the part below the folded
    prefix must be cut from the folded anchor, or a visible entry looks hidden."""

    def test_a_located_entry_below_a_lengthening_name_is_found(self) -> None:
        directory = self.work.parent / "straße"
        key = directory / "a.b" / "x" / "key"
        key.parent.mkdir(parents=True)
        key.write_text("k\n", encoding="utf-8")
        argv = ["rg", "x", str(directory)]
        with mock.patch(FOLD, True):
            hit = recursive.protected_inside(argv, str(self.work), (str(key),))
        self.assertIsNotNone(hit)


class LiteralTildeTests(UprootCase):
    """Without a shell ``~+/x`` is the relative path ``./~+/x``: both spellings count."""

    def setUp(self) -> None:
        super().setUp()
        (self.work / ".git" / "config").write_text("x\n", encoding="utf-8")
        (self.work / "~+").symlink_to(self.work / ".git", target_is_directory=True)

    def test_exec_policy_denies_a_literal_tilde_directory(self) -> None:
        policy = wiring.build_grantless_policy(Config(), self.work)
        decision = policy.check_command(
            ["cat", "~+/config"], str(self.work), Mode.EXECUTE, RiskLevel.LOW, consume=False
        )
        self.assertEqual(decision.outcome, PermissionOutcome.DENY)

    def test_the_hook_still_denies_the_expanded_spelling(self) -> None:
        self.assertEqual(self.decision("cat ~+/.git/config"), DENY)

    def test_is_protected_keeps_the_literal_spelling(self) -> None:
        literal = str(self.work / "~+" / "x")
        self.assertTrue(is_protected("~+/x", self.work, (literal,)))

    def test_uproot_keeps_the_literal_spelling(self) -> None:
        literal = str(self.work / "~+" / "sub" / "x")
        self.assertIsNotNone(uproot.uprooted(["rm", "~+/sub"], str(self.work), (literal,)))

    def test_recursive_readers_keep_the_literal_spelling(self) -> None:
        (self.work / "~").mkdir()
        (self.work / "~" / ".git").mkdir()
        argv = ["grep", "-r", "k", "~/"]
        self.assertIsNotNone(recursive.protected_inside(argv, str(self.work), (".git",)))
