"""update, rollback and freeze: fake opener, in-memory tarballs, isolated data dir."""

from __future__ import annotations

import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

from tests.unit.test_third_party_fetch import add_file, tarball
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.third_party import check, sources, switch
from wev_skills.third_party.state import SourceState, State

SRC = sources.source("agent-skills")
API = "https://api.github.com/repos/addyosmani/agent-skills"


def release_tar(valid: bool = True) -> bytes:
    meta = b"---\nname: a\ndescription: d\n---\nbody\n" if valid else b"no frontmatter"

    def build(archive: tarfile.TarFile) -> None:
        add_file(archive, "x-abc/skills/a/SKILL.md", meta)

    return tarball(build)


def opener(version: str, *, valid: bool = True, fail: bool = False) -> check.Opener:
    def get(url: str, _timeout: float) -> bytes:
        if fail:
            raise OSError("down")
        if url == f"{API}/releases/latest":
            return json.dumps(
                {"tag_name": version, "tarball_url": f"{API}/tarball/{version}"}
            ).encode()
        if url == f"{API}/tarball/{version}":
            return release_tar(valid)
        raise AssertionError(url)

    return get


class SwitchCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.runner = SubprocessRunner()

    def update(
        self, state: State, op: check.Opener, *, yes: bool = False
    ) -> tuple[State, switch.UpdateResult]:
        return switch.update(
            SRC, self.home, state, op, self.runner, check.BASE_URLS, yes=yes, download=op
        )

    def current(self) -> str:
        return os.readlink(self.home / SRC.name / "current")

    def test_update_ok_switches_and_keeps_previous(self) -> None:
        state = State({SRC.name: SourceState(active="v1", declined="v2")})
        (self.home / SRC.name / "v1").mkdir(parents=True)
        new, result = self.update(state, opener("v2"), yes=True)
        item = new.sources[SRC.name]
        self.assertEqual((result.ok, result.code, result.version), (True, "updated", "v2"))
        self.assertEqual((item.active, item.previous, item.declined), ("v2", "v1", None))
        self.assertEqual(self.current(), "v2")
        self.assertFalse((self.home / SRC.name / "current.tmp").exists())

    def test_failing_health_keeps_everything_and_the_new_dir(self) -> None:
        (self.home / SRC.name / "v1").mkdir(parents=True)
        os.symlink("v1", self.home / SRC.name / "current")
        state = State({SRC.name: SourceState(active="v1")})
        new, result = self.update(state, opener("v2", valid=False))
        self.assertEqual((result.ok, result.code), (False, "bad_skill"))
        self.assertEqual(new, state)
        self.assertEqual(self.current(), "v1")
        self.assertTrue((self.home / SRC.name / "v2").is_dir())

    def test_check_failure_is_reported_and_state_kept(self) -> None:
        state = State({SRC.name: SourceState(active="v1")})
        new, result = self.update(state, opener("v2", fail=True))
        self.assertEqual((result.ok, result.code), (False, "unreachable"))
        self.assertEqual(new, state)

    def test_update_twice_is_noop_and_state_stable(self) -> None:
        state, _ = self.update(State({}), opener("v2"))
        again, result = self.update(state, opener("v2"))
        self.assertEqual((result.ok, result.code), (True, "up_to_date"))
        self.assertEqual(again, state)
        self.assertEqual(self.current(), "v2")
        self.assertIsNone(again.sources[SRC.name].previous)

    def test_registry_json_and_tarball_take_their_own_openers(self) -> None:
        seen: list[tuple[str, str]] = []
        real = opener("v2")

        def registry(url: str, timeout: float) -> bytes:
            seen.append(("registry", url))
            return real(url, timeout)

        def download(url: str, timeout: float) -> bytes:
            seen.append(("download", url))
            return real(url, timeout)

        switch.update(
            SRC, self.home, State({}), registry, self.runner, check.BASE_URLS, download=download
        )
        self.assertEqual(
            seen, [("registry", f"{API}/releases/latest"), ("download", f"{API}/tarball/v2")]
        )

    def test_a_reserved_version_name_is_refused_before_anything_is_written(self) -> None:
        for tag in ("current", "current.tmp", "1.tmp-5"):
            with self.subTest(tag=tag):
                state, result = self.update(State({}), opener(tag))
                self.assertEqual((result.ok, result.code), (False, "bad_version"))
                self.assertEqual(state, State({}))
                self.assertFalse((self.home / SRC.name).exists())

    def test_a_link_that_lags_the_state_is_repaired_by_the_next_update(self) -> None:
        state, _ = self.update(State({}), opener("v1"))
        state, _ = self.update(state, opener("v2"))
        os.replace(self._tmp_link("v1"), self.home / SRC.name / "current")  # crash simulation
        again, result = self.update(state, opener("v2"))
        self.assertEqual((result.ok, result.code), (True, "updated"))
        self.assertEqual(self.current(), "v2")
        self.assertEqual(
            (again.sources[SRC.name].active, again.sources[SRC.name].previous), ("v2", "v1")
        )

    def _tmp_link(self, version: str) -> Path:
        tmp = self.home / SRC.name / "x.tmp"
        os.symlink(version, tmp)
        return tmp

    def test_frozen_is_refused(self) -> None:
        state = State({SRC.name: SourceState(active="v1", frozen=True)})
        with self.assertRaises(ValidationError) as caught:
            self.update(state, opener("v2"))
        self.assertEqual(caught.exception.code, "frozen")
        self.assertFalse((self.home / SRC.name / "v2").exists())

    def test_declined_version_needs_yes(self) -> None:
        state = State({SRC.name: SourceState(active="v1", declined="v2")})
        with self.assertRaises(ValidationError) as caught:
            self.update(state, opener("v2"))
        self.assertEqual(caught.exception.code, "declined")
        _, result = self.update(state, opener("v2"), yes=True)
        self.assertTrue(result.ok)

    def test_rollback_swaps_and_repoints(self) -> None:
        state, _ = self.update(State({SRC.name: SourceState(active="v1")}), opener("v2"))
        (self.home / SRC.name / "v1").mkdir(exist_ok=True)
        back = switch.rollback(SRC, self.home, state)
        self.assertEqual(
            (back.sources[SRC.name].active, back.sources[SRC.name].previous), ("v1", "v2")
        )
        self.assertEqual(self.current(), "v1")
        forward = switch.rollback(SRC, self.home, back)
        self.assertEqual(forward.sources[SRC.name].active, "v2")
        self.assertEqual(self.current(), "v2")

    def test_rollback_without_previous_is_conflict(self) -> None:
        state = State({SRC.name: SourceState(active="v1")})
        with self.assertRaises(StateConflict) as caught:
            switch.rollback(SRC, self.home, state)
        self.assertEqual(caught.exception.code, "no_previous")
        self.assertFalse((self.home / SRC.name / "current").exists())

    def test_rollback_to_a_missing_directory_is_conflict(self) -> None:
        state = State({SRC.name: SourceState(active="v2", previous="v1")})
        with self.assertRaises(StateConflict):
            switch.rollback(SRC, self.home, state)

    def test_freeze_on_and_off(self) -> None:
        on = switch.freeze(SRC, State({}), True)
        self.assertTrue(on.sources[SRC.name].frozen)
        self.assertFalse(switch.freeze(SRC, on, False).sources[SRC.name].frozen)


if __name__ == "__main__":
    unittest.main()
