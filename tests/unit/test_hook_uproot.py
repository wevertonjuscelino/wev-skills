"""The registry directory is protected, and moving or removing an ancestor of a protected
path asks (deny in plan mode), with and without a run."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from tests.unit.test_hook_trust import ASK, DENY, TrustCase
from wev_skills.core import run_registry
from wev_skills.security.paths import is_protected

DOT_ENV = "." + "env"
HOLDS = "holds a protected path"
NO_RUN, EXECUTE, PLAN = "no run", "execute", "plan"


class UprootCase(TrustCase):
    """``HOME`` is a temporary directory and ``XDG_STATE_HOME`` is unset, so the registry
    lives at ``~/.local/state/wev-skills`` as on a default install."""

    def setUp(self) -> None:
        super().setUp()
        self.home = self.work.parent / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("XDG_STATE_HOME", None)
        self.regdir = self.home / ".local" / "state" / "wev-skills"
        self.assertEqual(run_registry.registry_path().parent, self.regdir)
        (self.work / "src" / "pkg" / DOT_ENV).write_text("K=v\n", encoding="utf-8")

    def rows(self) -> dict[str, str]:
        return {}

    def plan_rows(self) -> dict[str, str]:
        return {}

    def check(self, situation: str) -> None:
        if situation != NO_RUN:
            self.start(mode=situation)
        self.regdir.mkdir(parents=True, exist_ok=True)
        expected = {**self.rows(), **(self.plan_rows() if situation == PLAN else {})}
        for line, wanted in expected.items():
            with self.subTest(situation=situation, line=line):
                self.assertEqual(self.decision(line), wanted)


class SituationTests:
    """Mixin: run ``rows`` without a run, in an execute run and in a plan run."""

    def check(self, situation: str) -> None:
        raise NotImplementedError

    def test_without_a_run(self) -> None:
        self.check(NO_RUN)

    def test_in_an_execute_run(self) -> None:
        self.check(EXECUTE)

    def test_in_a_plan_run(self) -> None:
        self.check(PLAN)


class RegistryDirectoryTests(UprootCase, SituationTests):
    def rows(self) -> dict[str, str]:
        regdir = self.regdir
        return {
            f"mv {regdir} /tmp/x": DENY,
            "mv ~/.local/state/wev-skills /tmp/x": DENY,
            f"echo x > {regdir}/new.json": DENY,
            f"cp f.json {regdir}/": DENY,
            "cat ~/.local/state/wev-skills/active-runs.json": DENY,
            f"cd {regdir} && mv . ../y": DENY,
        }


class AncestorTests(UprootCase, SituationTests):
    def rows(self) -> dict[str, str]:
        return {
            "mv ~/.local/state /tmp/x": ASK,
            "mv ~/.local /tmp/x": ASK,
            "rmdir ~/.local": ASK,
            "mv src/pkg /tmp/x": ASK,
            "mv -t /tmp/x src/pkg": ASK,
            "rm src/pkg": ASK,
            "find src -delete": ASK,
        }

    def plan_rows(self) -> dict[str, str]:
        return dict.fromkeys(self.rows(), DENY)


class RecreateTests(UprootCase):
    def test_recreating_a_missing_registry_directory_is_denied(self) -> None:
        self.assertFalse(self.regdir.exists())
        for line in (f"mkdir -p {self.regdir}", f"cp -r /tmp/forged {self.regdir}"):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), DENY)

    def test_protection_matches_by_path_not_existence(self) -> None:
        missing = self.regdir / "active-runs.json"
        self.assertFalse(missing.parent.exists())
        self.assertTrue(is_protected(missing, self.work, (str(self.regdir),)))
        self.assertTrue(is_protected("~/.local/state/wev-skills", self.work, (str(self.regdir),)))


class AncestorDetailTests(UprootCase):
    def test_the_reason_names_the_directory(self) -> None:
        found = self.bash("mv ~/.local /tmp/x")
        assert found is not None
        self.assertIn(HOLDS, found["reason"])

    def test_moving_the_repository_itself_asks(self) -> None:
        self.assertEqual(self.decision("mv . ../moved"), ASK)
        self.assertEqual(self.decision(f"mv {self.work} /tmp/moved", self.work.parent), ASK)

    def test_a_plain_move_stays_silent(self) -> None:
        (self.work / "a.txt").write_text("a\n", encoding="utf-8")
        (self.work / "plain").mkdir()
        for line in ("mv a.txt b.txt", "mv plain /tmp/plain", "mv a.txt .."):
            with self.subTest(line=line):
                self.assertIsNone(self.decision(line))

    def test_a_destination_that_is_an_ancestor_is_not_a_removal(self) -> None:
        self.assertIsNone(self.decision(f"mv notes.txt {Path.home()}"))
