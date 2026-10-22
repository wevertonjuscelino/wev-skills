"""Health checks: fake npx over stdio, temp dirs, no network."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills.core.ports import SubprocessRunner
from wev_skills.third_party import health as health_mod
from wev_skills.third_party import sources
from wev_skills.third_party.health import health

FAKE_NPX = str(Path(__file__).parent.parent / "fixtures" / "fake_npx_mcp.py")
RUNNER = SubprocessRunner()
REA = sources.source("rea")
SKILLS = sources.source("agent-skills")
WEV = sources.source("wev-skills")


def mcp(mode: str, npx: str = FAKE_NPX) -> health_mod.HealthReport:
    with mock.patch.dict(os.environ, {"FAKE_MCP_MODE": mode}):
        return health(REA, "1.0.0", Path("/nonexistent"), RUNNER, npx=npx)


def write_skill(root: Path, name: str, meta: str) -> None:
    folder = root / "agent-skills" / "v1" / "skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\n{meta}\n---\nbody\n", encoding="utf-8")


def write_wev(root: Path, printed: str) -> None:
    script = root / "wev-skills" / "v5.0.0" / "bin" / "wev"
    script.parent.mkdir(parents=True)
    script.write_text(f"import json\nprint(json.dumps({{'version': {printed!r}}}))\n")


class McpTests(unittest.TestCase):
    def test_ok(self) -> None:
        self.assertTrue(mcp("ok").ok)

    def test_empty_tools_list_fails(self) -> None:
        self.assertEqual(mcp("empty-tools").code, "no_tools")

    def test_garbage_fails(self) -> None:
        self.assertEqual(mcp("garbage").code, "bad_jsonrpc")

    def test_exit_non_zero_fails(self) -> None:
        self.assertEqual(mcp("exit-non-zero").code, "bad_jsonrpc")

    def test_missing_npx_fails(self) -> None:
        self.assertEqual(mcp("ok", npx="/nonexistent/npx").code, "spawn_failed")

    def test_mcp_timeout_fails(self) -> None:
        with mock.patch.object(health_mod, "HEALTH_TIMEOUT", 1.0):
            self.assertEqual(mcp("hang").code, "timeout")


class SkillsTests(unittest.TestCase):
    def check(self, root: Path) -> health_mod.HealthReport:
        return health(SKILLS, "v1", root, RUNNER)

    def test_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(Path(tmp), "a", "name: a\ndescription: does a")
            self.assertTrue(self.check(Path(tmp)).ok)

    def test_zero_skill_files_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "agent-skills" / "v1" / "skills").mkdir(parents=True)
            self.assertEqual(self.check(Path(tmp)).code, "no_skills")

    def test_skill_name_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(Path(tmp), "a", "name: b\ndescription: x")
            self.assertEqual(self.check(Path(tmp)).code, "bad_skill:a")

    def test_empty_description_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(Path(tmp), "a", "name: a\ndescription:")
            self.assertEqual(self.check(Path(tmp)).code, "bad_skill:a")

    def test_symlinked_skill_outside_version_dir_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "SKILL.md").write_text("---\nname: a\ndescription: x\n---\n")
            link = root / "agent-skills" / "v1" / "skills" / "a"
            link.parent.mkdir(parents=True)
            link.symlink_to(outside)
            self.assertEqual(self.check(root).code, "bad_skill:a")


class WevTests(unittest.TestCase):
    def test_ok_with_leading_v(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_wev(Path(tmp), "5.0.0")
            self.assertTrue(health(WEV, "v5.0.0", Path(tmp), RUNNER).ok)

    def test_wrong_wev_version_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_wev(Path(tmp), "4.9.9")
            report = health(WEV, "v5.0.0", Path(tmp), RUNNER)
            self.assertEqual(report.code, "version_mismatch")

    def test_missing_binary_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "wev-skills" / "v5.0.0").mkdir(parents=True)
            self.assertEqual(health(WEV, "v5.0.0", Path(tmp), RUNNER).code, "spawn_failed")


if __name__ == "__main__":
    unittest.main()
