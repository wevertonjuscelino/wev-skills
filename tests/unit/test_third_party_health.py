"""Health checks: fake npx over stdio, temp dirs, no network."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from wev_skills import i18n
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
    with mock.patch.dict(os.environ, {"NODE_FAKE_MCP_MODE": mode}):
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

    def test_exit_non_zero_reports_the_exit_code(self) -> None:
        report = mcp("exit-non-zero")
        self.assertEqual((report.code, dict(report.params)), ("spawn_failed", {"exit": 3}))

    def test_notification_flood_times_out(self) -> None:
        started = time.monotonic()
        with mock.patch.object(health_mod, "HEALTH_TIMEOUT", 2.0):
            report = mcp("flood")
        self.assertEqual(report.code, "timeout")
        self.assertLess(time.monotonic() - started, 6)

    def test_deeply_nested_json_is_bad_jsonrpc(self) -> None:
        self.assertEqual(mcp("nested").code, "bad_jsonrpc")

    def test_a_multi_megabyte_tools_list_passes(self) -> None:
        report = mcp("big-reply")
        self.assertTrue(report.ok, report)
        self.assertGreater(report.params["tools"], 1000)

    def test_a_reply_over_the_cap_is_refused_naming_the_limit(self) -> None:
        report = mcp("huge-reply")
        self.assertEqual(report.code, "reply_too_large")
        self.assertEqual(report.params["limit"], 32)
        self.assertGreater(report.params["seen"], health_mod.MAX_LINE)
        self.assertIn("32 MiB", health_mod.render(report, "en"))
        self.assertIn("32 MiB", health_mod.render(report, "pt-BR"))

    def test_grandchild_holding_stdout_does_not_hang_and_dies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / "pid"
            started = time.monotonic()
            with (
                mock.patch.object(health_mod, "HEALTH_TIMEOUT", 5.0),
                mock.patch.dict(os.environ, {"NODE_FAKE_MCP_PIDFILE": str(pidfile)}),
            ):
                report = mcp("grandchild")
            self.assertTrue(report.ok, report)
            self.assertLess(time.monotonic() - started, 5)
            pid = int(pidfile.read_text())
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_child_gets_a_minimal_environment(self) -> None:
        env = health_mod.child_env(
            {"PATH": "/bin", "AWS_SECRET_ACCESS_KEY": "x", "NODE_OPTIONS": "o"}
        )
        self.assertEqual(env, {"PATH": "/bin", "NODE_OPTIONS": "o"})

    def test_missing_npx_fails(self) -> None:
        self.assertEqual(mcp("ok", npx="/nonexistent/npx").code, "spawn_failed")

    def test_missing_npx_renders_without_a_placeholder(self) -> None:
        report = mcp("ok", npx="/nonexistent/npx")
        self.assertNotIn("{", health_mod.render(report, "en"))

    def test_mismatch_message_names_no_type(self) -> None:
        text = health_mod.render(health_mod.HealthReport(False, "version_mismatch"), "en")
        self.assertNotIn("{", text)

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
            self.assertEqual(self.check(Path(tmp)).code, "bad_skill")

    def test_empty_description_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(Path(tmp), "a", "name: a\ndescription:")
            self.assertEqual(self.check(Path(tmp)).code, "bad_skill")

    def test_bad_skill_dir_is_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(Path(tmp), "a b\x1b[31m" + "z" * 100, "name: x\ndescription: x")
            report = self.check(Path(tmp))
            dirname = str(report.params["dir"])
            self.assertRegex(dirname, r"^[A-Za-z0-9._-]{1,64}$")

    def test_symlinked_skill_outside_version_dir_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "SKILL.md").write_text("---\nname: a\ndescription: x\n---\n")
            link = root / "agent-skills" / "v1" / "skills" / "a"
            link.parent.mkdir(parents=True)
            link.symlink_to(outside)
            self.assertEqual(self.check(root).code, "bad_skill")


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

    def test_deeply_nested_version_output_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "wev-skills" / "v5.0.0" / "bin" / "wev"
            script.parent.mkdir(parents=True)
            script.write_text("print('[' * 500000)\n")
            report = health(WEV, "v5.0.0", Path(tmp), RUNNER)
            self.assertEqual(report.code, "version_mismatch")

    def test_mismatch_does_not_echo_child_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_wev(Path(tmp), "SECRETVALUE")
            report = health(WEV, "v5.0.0", Path(tmp), RUNNER)
            self.assertNotIn("SECRETVALUE", repr(report))

    def head_report(self, printed: str) -> health_mod.HealthReport:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "wev-skills" / "0123456789ab" / "bin" / "wev"
            script.parent.mkdir(parents=True)
            script.write_text(f"import json\nprint(json.dumps({{'version': {printed!r}}}))\n")
            return health(WEV, "0123456789ab", Path(tmp), RUNNER)

    def test_head_install_needs_only_a_well_formed_version(self) -> None:
        report = self.head_report("5.1.0")
        self.assertTrue(report.ok)
        self.assertEqual(report.code, "ok")

    def test_head_install_with_malformed_version_fails(self) -> None:
        self.assertEqual(self.head_report("not a version").code, "version_mismatch")

    def test_missing_binary_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "wev-skills" / "v5.0.0").mkdir(parents=True)
            self.assertEqual(health(WEV, "v5.0.0", Path(tmp), RUNNER).code, "spawn_failed")


class RenderTests(unittest.TestCase):
    CODES = (
        "ok",
        "spawn_failed",
        "timeout",
        "bad_jsonrpc",
        "reply_too_large",
        "no_tools",
        "no_skills",
        "bad_skill",
        "version_mismatch",
    )

    def test_every_code_has_a_key_in_both_languages(self) -> None:
        for lang in ("en", "pt-BR"):
            for code in self.CODES:
                with self.subTest(lang=lang, code=code):
                    key = f"skills.health.{code}"
                    self.assertNotEqual(i18n.t(key, lang), key)

    def test_render_fills_params(self) -> None:
        report = health_mod.HealthReport(False, "bad_skill", {"dir": "abc"})
        self.assertIn("abc", health_mod.render(report, "en"))
        self.assertIn("abc", health_mod.render(report, "pt-BR"))


if __name__ == "__main__":
    unittest.main()
