"""Registry and state file of the third-party skill sources."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from wev_skills.core.errors import ValidationError
from wev_skills.third_party import sources, state


class SourcesCase(unittest.TestCase):
    def test_sources_are_exactly_the_three(self) -> None:
        got = {s.name: (s.kind, s.package, s.health) for s in sources.SOURCES}
        self.assertEqual(
            got,
            {
                "rea": ("npm", "rea-agents", "mcp"),
                "agent-skills": ("github", "addyosmani/agent-skills", "skills"),
                "wev-skills": ("github", "wevertonjuscelino/wev-skills", "wev"),
            },
        )
        for s in sources.SOURCES:
            self.assertIn("{version}", s.changelog)

    def test_unknown_source_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            sources.source("nope")
        self.assertEqual(ctx.exception.code, "unknown_source")


class StateCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "third-party" / "state.json"

    def write(self, data: object) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_state_roundtrip(self) -> None:
        item = state.SourceState("1.2.0", "1.1.0", True, "2026-10-21", "1.3.0", "1.3.0")
        original = state.State({"rea": item}, "2026-10-21T10:00:00Z")
        state.save(self.path, original)
        self.assertEqual(state.load(self.path), original)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_missing_state_is_empty(self) -> None:
        self.assertEqual(state.load(self.path), state.State({}, None))

    def test_invalid_state_rejected(self) -> None:
        good = {"active": "1.0.0", "previous": None, "frozen": False}
        for bad in (
            {"sources": {"rea": {**good, "active": "../x"}}},
            {"sources": {"rea": {**good, "active": "."}}},
            {"sources": {"rea": {**good, "previous": ".."}}},
            {"sources": {"rea": {**good, "frozen": "yes"}}},
            {"sources": {"rea": {**good, "extra": 1}}},
            {"sources": {}, "extra": 1},
            {"sources": {"evil": good}},
            [],
        ):
            self.write(bad)
            with self.assertRaises(ValidationError, msg=str(bad)) as ctx:
                state.load(self.path)
            self.assertEqual(ctx.exception.code, "state_invalid")
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValidationError):
            state.load(self.path)

    def test_data_home_follows_xdg(self) -> None:
        from unittest import mock

        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": "/x/data"}):
            self.assertEqual(state.data_home(), Path("/x/data/wev-skills/third-party"))

    def test_data_home_falls_back_to_local_share(self) -> None:
        from unittest import mock

        with mock.patch.dict("os.environ", {"HOME": "/h"}):
            os.environ.pop("XDG_DATA_HOME", None)
            self.assertEqual(state.data_home(), Path("/h/.local/share/wev-skills/third-party"))

    def test_dotted_versions_are_still_allowed(self) -> None:
        self.assertTrue(state.VERSION_RE.fullmatch("1.0.0-rc.1"))
        self.assertTrue(state.VERSION_RE.fullmatch("v1.5"))
        self.assertIsNone(state.VERSION_RE.fullmatch("..."))
        self.assertTrue(state.VERSION_RE.fullmatch("1" * 64))
        self.assertIsNone(state.VERSION_RE.fullmatch("1" * 65))


if __name__ == "__main__":
    unittest.main()
