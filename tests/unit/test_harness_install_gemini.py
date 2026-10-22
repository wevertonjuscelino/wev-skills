import json
import os
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest import mock

from wev_skills.adapters.harness_install import install, uninstall
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import NotFound, RemoteError, ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.core.wiring import REPO_ROOT

WEV = REPO_ROOT / "bin" / "wev"
FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_gemini.py"


class FakeGeminiRunner:
    """Runs the fake CLI in place of ``gemini`` through the real subprocess runner."""

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None,
        timeout: float | None,
        env: Mapping[str, str] | None,
    ) -> RawCommandResult:
        assert argv[0] == "gemini"
        return SubprocessRunner().run([sys.executable, str(FAKE), *argv[1:]], cwd, timeout, env)


class GeminiBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name) / "data"
        self.log = Path(tmp.name) / "gemini.log"
        env = mock.patch.dict(os.environ, {"FAKE_GEMINI_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)
        self.root = self.data / "wev-skills" / "harness" / "gemini"
        self.package = self.root / "package"

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def fail_on(self, words: str) -> None:
        patcher = mock.patch.dict(os.environ, {"FAKE_GEMINI_FAIL": words})
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self) -> object:
        return install("gemini", FakeGeminiRunner(), self.data, WEV)

    def files(self) -> set[str]:
        return {p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()}


class GeminiInstallTests(GeminiBase):
    def test_validate_runs_before_link_and_the_manifest_lists_both_argv(self) -> None:
        self.install()
        self.assertEqual(
            self.calls(),
            [
                ["extensions", "validate", str(self.package)],
                ["extensions", "link", str(self.package)],
            ],
        )
        stored = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(
            stored["registrations"],
            [
                ["gemini", "extensions", "link", str(self.package)],
                ["gemini", "extensions", "uninstall", "wev-skills"],
            ],
        )
        self.assertTrue((self.package / "gemini-extension.json").is_file())
        self.assertFalse((self.package / ".agents").exists())  # the marketplace is Codex's

    def test_a_failed_validation_registers_nothing_and_leaves_no_files(self) -> None:
        self.data.mkdir()
        self.fail_on("extensions validate")
        with self.assertRaises(RemoteError) as caught:
            self.install()
        self.assertEqual(caught.exception.exit_code, 8)
        self.assertEqual([c[:2] for c in self.calls()], [["extensions", "validate"]])
        self.assertEqual(self.files(), set())
        self.assertFalse((self.data / "wev-skills").exists())

    def test_a_failed_link_leaves_nothing(self) -> None:
        self.fail_on("extensions link")
        with self.assertRaises(RemoteError):
            self.install()
        self.assertEqual(self.files(), set())
        self.assertNotIn("uninstall", [c[1] for c in self.calls()])  # nothing was linked

    def test_reinstall_unlinks_the_old_one_and_links_once_more(self) -> None:
        self.install()
        self.install()
        verbs = [c[1] for c in self.calls()]
        self.assertEqual(verbs, ["validate", "link", "uninstall", "validate", "link"])
        stored = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(len(stored["registrations"]), 2)
        self.assertEqual(len(stored["files"]), len(set(stored["files"])))

    def test_manifest_write_failure_unlinks_the_extension(self) -> None:
        (self.root / "manifest.json").mkdir(parents=True)
        with self.assertRaises(RemoteError):
            self.install()
        self.assertEqual(self.calls()[-1], ["extensions", "uninstall", "wev-skills"])
        self.assertFalse(self.package.exists())

    def test_a_tampered_gemini_registration_is_never_run(self) -> None:
        self.install()
        before = len(self.calls())
        data = json.loads((self.root / "manifest.json").read_text())
        data["registrations"][1] = ["sh", "-c", "echo pwned"]
        (self.root / "manifest.json").write_text(json.dumps(data))
        with self.assertRaises(ValidationError):
            uninstall("gemini", FakeGeminiRunner(), self.data)
        self.assertEqual(len(self.calls()), before)


class GeminiUninstallTests(GeminiBase):
    def test_uninstall_runs_the_inverse_and_removes_what_wev_made(self) -> None:
        self.install()
        uninstall("gemini", FakeGeminiRunner(), self.data)
        self.assertEqual(self.calls()[2:], [["extensions", "uninstall", "wev-skills"]])
        self.assertFalse((self.data / "wev-skills").exists())
        self.assertTrue(self.data.is_dir())

    def test_uninstall_keeps_directories_that_hold_other_files(self) -> None:
        self.install()
        other = self.data / "wev-skills" / "harness" / "codex"
        other.mkdir(parents=True)
        uninstall("gemini", FakeGeminiRunner(), self.data)
        self.assertFalse(self.root.exists())
        self.assertTrue(other.is_dir())

    def test_uninstall_without_install_is_not_found(self) -> None:
        with self.assertRaises(NotFound):
            uninstall("gemini", FakeGeminiRunner(), self.data)

    def test_a_failed_inverse_keeps_the_manifest_for_a_retry(self) -> None:
        self.install()
        self.fail_on("extensions uninstall")
        with self.assertRaises(RemoteError):
            uninstall("gemini", FakeGeminiRunner(), self.data)
        self.assertTrue((self.root / "manifest.json").is_file())
