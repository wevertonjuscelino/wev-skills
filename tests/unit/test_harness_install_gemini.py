import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest import mock

from wev_skills import cli
from wev_skills.adapters.harness_install import install, uninstall
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import NotFound, RemoteError, StateConflict, ValidationError
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
    def test_install_only_validates_and_leaves_the_link_to_the_person(self) -> None:
        self.install()
        calls = self.calls()
        self.assertEqual(calls[0], ["extensions", "list", "-o", "json"])
        self.assertEqual([c[:2] for c in calls[1:]], [["extensions", "validate"]])
        self.assertIn(".staging-", calls[1][2])  # the staged package is checked before the copy
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
        self.assertEqual([c[1] for c in self.calls()], ["list", "validate"])
        self.assertEqual(self.files(), set())
        self.assertFalse((self.data / "wev-skills").exists())

    def test_a_failed_validation_leaves_the_previous_install_intact(self) -> None:
        self.install()
        before = (self.root / "manifest.json").read_text()
        hooks = self.package / "hooks" / "hooks.json"
        self.fail_on("extensions validate")
        with self.assertRaises(RemoteError) as caught:
            self.install()
        self.assertNotIn("previous_removed", caught.exception.details)
        self.assertEqual((self.root / "manifest.json").read_text(), before)
        self.assertTrue(hooks.is_file())
        # no uninstall; the list check runs only when no wev manifest exists
        self.assertEqual([c[1] for c in self.calls()], ["list", "validate", "validate"])

    def test_reinstall_keeps_the_link_and_replaces_the_files(self) -> None:
        self.install()
        self.install()
        self.assertEqual([c[1] for c in self.calls()], ["list", "validate", "validate"])
        stored = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(len(stored["registrations"]), 2)
        self.assertEqual(len(stored["files"]), len(set(stored["files"])))

    def test_manifest_write_failure_runs_no_inverse_as_nothing_was_linked(self) -> None:
        (self.root / "manifest.json").mkdir(parents=True)
        with self.assertRaises(RemoteError):
            self.install()
        self.assertEqual([c[1] for c in self.calls()], ["list", "validate"])
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

    def test_a_manifest_of_another_target_is_refused_by_uninstall_and_install(self) -> None:
        package = self.root / "package"
        package.mkdir(parents=True)
        codex = [
            ["codex", "plugin", "marketplace", "add", str(package)],
            ["codex", "plugin", "marketplace", "remove", "wev-skills"],
            ["codex", "plugin", "add", "wev-skills@wev-skills"],
            ["codex", "plugin", "remove", "wev-skills@wev-skills"],
        ]
        crafted = {"target": "codex", "files": [], "registrations": codex}
        (self.root / "manifest.json").write_text(json.dumps(crafted))
        with self.assertRaises(ValidationError) as caught:
            uninstall("gemini", FakeGeminiRunner(), self.data)
        self.assertEqual(caught.exception.exit_code, 2)
        with self.assertRaises(ValidationError):
            self.install()
        self.assertEqual(self.calls(), [])

    def test_a_wev_skills_extension_wev_did_not_install_is_refused(self) -> None:
        listed = [{"name": "other"}, {"name": "wev-skills", "path": "/theirs"}]
        for output in (json.dumps(listed), json.dumps({"extensions": listed})):
            env = mock.patch.dict(os.environ, {"FAKE_GEMINI_LIST": output})
            with self.subTest(output=output):
                with env, self.assertRaises(StateConflict) as caught:
                    self.install()
                self.assertEqual(caught.exception.exit_code, 5)
                self.assertFalse((self.data / "wev-skills").exists())
        self.assertEqual({c[1] for c in self.calls()}, {"list"})

    def test_an_unreadable_extension_list_is_refused(self) -> None:
        env = mock.patch.dict(os.environ, {"FAKE_GEMINI_LIST": "not json"})
        with env, self.assertRaises(RemoteError):
            self.install()
        self.assertEqual([c[1] for c in self.calls()], ["list"])


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


class GeminiCliTests(GeminiBase):
    def test_install_reports_the_link_command_for_the_person_to_run(self) -> None:
        from wev_skills.commands import harness

        out = io.StringIO()
        runner = mock.patch.object(harness, "SubprocessRunner", FakeGeminiRunner)
        env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.data)})
        with runner, env, contextlib.redirect_stdout(out):
            code = cli.main(["harness", "install", "--target", "gemini"])
        self.assertEqual(code, 0, out.getvalue())
        steps = json.loads(out.getvalue())["next_steps"]
        self.assertIn(f"gemini extensions link {self.package}", steps[0])
        self.assertIn("gemini extensions list -o json", steps[1])
        self.assertEqual([c[1] for c in self.calls()], ["list", "validate"])  # no link
