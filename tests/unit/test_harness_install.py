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
from wev_skills.adapters import harness_install
from wev_skills.adapters.harness_install import install, uninstall
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import RemoteError, ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.core.wiring import REPO_ROOT

WEV = REPO_ROOT / "bin" / "wev"
FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_codex.py"
MKT = "wev-skills"
PLUGIN = "wev-skills@wev-skills"


class FakeCodexRunner:
    """Runs the fake CLI in place of ``codex`` through the real subprocess runner."""

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None,
        timeout: float | None,
        env: Mapping[str, str] | None,
    ) -> RawCommandResult:
        assert argv[0] == "codex"
        return SubprocessRunner().run([sys.executable, str(FAKE), *argv[1:]], cwd, timeout, env)


class InstallBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name) / "data"
        self.log = Path(tmp.name) / "codex.log"
        env = mock.patch.dict(os.environ, {"FAKE_CODEX_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)
        self.root = self.data / "wev-skills" / "harness" / "codex"

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def fail_on(self, words: str) -> None:
        patcher = mock.patch.dict(os.environ, {"FAKE_CODEX_FAIL": words})
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self) -> object:
        return install("codex", FakeCodexRunner(), self.data, WEV)

    def files(self) -> set[str]:
        return {p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()}


class InstallTests(InstallBase):
    def test_install_builds_registers_and_writes_the_manifest(self) -> None:
        manifest = install("codex", FakeCodexRunner(), self.data, WEV)
        package = self.root / "package"
        self.assertTrue((package / ".codex-plugin" / "plugin.json").is_file())
        self.assertEqual(
            self.calls(),
            [["plugin", "marketplace", "add", str(package)], ["plugin", "add", PLUGIN]],
        )
        stored = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(stored["target"], "codex")
        self.assertEqual(manifest.target, "codex")
        self.assertIn(str(package / "hooks.json"), stored["files"])
        self.assertIn(str(package / ".agents" / "plugins" / "marketplace.json"), stored["files"])
        self.assertEqual(
            stored["registrations"],
            [
                ["codex", "plugin", "marketplace", "add", str(package)],
                ["codex", "plugin", "marketplace", "remove", MKT],
                ["codex", "plugin", "add", PLUGIN],
                ["codex", "plugin", "remove", PLUGIN],
            ],
        )
        for name in stored["files"]:
            self.assertTrue(Path(name).is_file(), name)

    def test_marketplace_names_the_plugin_at_the_package_root(self) -> None:
        self.install()
        data = json.loads((self.root / "package/.agents/plugins/marketplace.json").read_text())
        self.assertEqual(data["name"], MKT)
        self.assertEqual(data["plugins"][0]["name"], "wev-skills")
        self.assertEqual(data["plugins"][0]["source"], {"source": "local", "path": "./"})

    def test_reinstall_replaces_and_does_not_register_twice(self) -> None:
        self.install()
        (self.root / "package" / "stale.txt").write_text("x")  # not in the manifest
        stale_in_manifest = self.root / "package" / "skills" / "gone.md"
        stale_in_manifest.write_text("x")
        data = json.loads((self.root / "manifest.json").read_text())
        (self.root / "manifest.json").write_text(
            json.dumps({**data, "files": [*data["files"], str(stale_in_manifest)]})
        )
        self.install()
        self.assertFalse(stale_in_manifest.exists())
        self.assertTrue((self.root / "package" / "stale.txt").is_file())  # not wev's: it stays
        stored = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(len(stored["registrations"]), 4)
        self.assertEqual(len(stored["files"]), len(set(stored["files"])))
        registered = [c for c in self.calls() if c[:2] in (["plugin", "add"],)]
        removed = [c for c in self.calls() if c[:2] == ["plugin", "remove"]]
        self.assertEqual(len(registered), 2)
        self.assertEqual(len(removed), 1)  # the first registration was undone before the second

    def test_install_does_not_run_anything_but_registration(self) -> None:
        self.install()
        for call in self.calls():
            self.assertEqual(call[0], "plugin")
            self.assertNotIn("--dangerously-bypass-hook-trust", call)

    def test_failure_rolls_back_files_and_earlier_registrations(self) -> None:
        self.fail_on("plugin add")
        stray = self.root / "package" / "notes.txt"
        stray.parent.mkdir(parents=True)
        stray.write_text("mine")
        with self.assertRaises(RemoteError) as caught:
            self.install()
        self.assertEqual(caught.exception.exit_code, 8)
        self.assertEqual(self.files(), {"package/notes.txt"})
        self.assertEqual(stray.read_text(), "mine")
        self.assertFalse((self.root / "manifest.json").exists())
        self.assertEqual(
            self.calls()[-1], ["plugin", "marketplace", "remove", MKT]
        )  # the marketplace that was added is removed again

    def test_first_command_failure_leaves_nothing(self) -> None:
        self.data.mkdir()
        self.fail_on("plugin marketplace add")
        with self.assertRaises(RemoteError):
            self.install()
        self.assertEqual(self.files(), set())
        self.assertTrue(self.data.is_dir())  # data_home is not wev's to remove
        self.assertEqual(len(self.calls()), 1)

    def test_a_placeholder_file_is_refused(self) -> None:
        def build(target: str, out: Path, wev: Path) -> list[Path]:
            path = out / "plugins" / "wev-guard.js"
            path.parent.mkdir(parents=True)
            path.write_text("// wev-placeholder\nexport {}\n")
            return [path]

        patched = mock.patch.object(harness_install, "build_package", build)
        with patched, self.assertRaises(ValidationError):
            self.install()
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.root / "package").exists())

    def test_unknown_target_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            install("nope", FakeCodexRunner(), self.data, WEV)


class FixRoundTests(InstallBase):
    def manifest(self) -> dict[str, object]:
        return json.loads((self.root / "manifest.json").read_text())

    def store(self, data: object) -> None:
        (self.root / "manifest.json").write_text(json.dumps(data))

    def test_a_tampered_registration_is_never_run(self) -> None:
        self.install()
        before = len(self.calls())
        data = self.manifest()
        data["registrations"][1] = ["sh", "-c", "echo pwned > /tmp/never"]  # type: ignore[index]
        self.store(data)
        with self.assertRaises(ValidationError):
            uninstall("codex", FakeCodexRunner(), self.data)
        self.assertEqual(len(self.calls()), before)
        self.assertTrue((self.root / "package" / "hooks.json").is_file())

    def test_a_path_outside_the_package_is_rejected_and_nothing_is_removed(self) -> None:
        self.install()
        outside = self.data / "precious.txt"
        outside.write_text("x")
        data = self.manifest()
        data["files"] = [*data["files"], str(outside)]  # type: ignore[misc]
        self.store(data)
        with self.assertRaises(ValidationError):
            uninstall("codex", FakeCodexRunner(), self.data)
        self.assertTrue(outside.is_file())
        self.assertTrue((self.root / "package" / "hooks.json").is_file())

    def test_a_dotdot_or_symlinked_path_is_rejected(self) -> None:
        self.install()
        package = self.root / "package"
        outside = self.data / "precious.txt"
        outside.write_text("x")
        link = package / "link"
        link.symlink_to(self.data)
        for bad in (f"{package}/../../precious.txt", str(link / "precious.txt"), str(package)):
            data = self.manifest()
            data["files"] = [bad]  # type: ignore[assignment]
            self.store(data)
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                uninstall("codex", FakeCodexRunner(), self.data)
        self.assertTrue(outside.is_file())

    def test_a_corrupt_manifest_is_a_validation_error(self) -> None:
        self.install()
        for text in ("{not json", "[]", '{"target": "codex"}', '{"target": 3, "files": 1}'):
            (self.root / "manifest.json").write_text(text)
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                uninstall("codex", FakeCodexRunner(), self.data)
            self.assertEqual(caught.exception.exit_code, 2)

    def test_failed_reinstall_leaves_no_stale_manifest(self) -> None:
        self.install()
        self.fail_on("plugin add")
        with self.assertRaises(RemoteError):
            self.install()
        self.assertEqual(self.files(), set())
        adds = [c for c in self.calls() if c[:2] == ["plugin", "add"]]
        removes = [c for c in self.calls() if c[:2] == ["plugin", "remove"]]
        self.assertEqual((len(adds), len(removes)), (2, 1))
        marketplace = [c[3] for c in self.calls() if c[:2] == ["plugin", "marketplace"]]
        self.assertEqual(marketplace.count("add"), marketplace.count("remove"))

    def test_manifest_write_failure_undoes_both_registrations_newest_first(self) -> None:
        (self.root / "manifest.json").mkdir(parents=True)  # cannot be replaced by a file
        with self.assertRaises(RemoteError):
            self.install()
        self.assertEqual(
            self.calls()[2:],
            [["plugin", "remove", PLUGIN], ["plugin", "marketplace", "remove", MKT]],
        )
        self.assertFalse((self.root / "package").exists())

    def test_rollback_failures_are_reported_in_the_error(self) -> None:
        self.fail_on("plugin add|plugin marketplace remove")
        with self.assertRaises(RemoteError) as caught:
            self.install()
        failed = caught.exception.details["undo_failed"]
        self.assertEqual(failed, [["codex", "plugin", "marketplace", "remove", MKT]])


class SecondFixTests(InstallBase):
    def test_a_symlinked_directory_inside_the_package_is_refused(self) -> None:
        outside = self.data / "outside"
        outside.mkdir(parents=True)
        package = self.root / "package"
        package.mkdir(parents=True)
        (package / "skills").symlink_to(outside)
        with self.assertRaises(ValidationError) as caught:
            self.install()
        self.assertIn("skills", str(caught.exception))
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.calls(), [])

    def test_a_symlinked_package_is_refused(self) -> None:
        outside = self.data / "outside"
        outside.mkdir(parents=True)
        self.root.mkdir(parents=True)
        (self.root / "package").symlink_to(outside)
        with self.assertRaises(ValidationError):
            self.install()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.calls(), [])

    def test_a_partial_copy_is_removed_on_failure(self) -> None:
        (self.root / "package" / "hooks.json").mkdir(parents=True)  # the copy cannot replace it
        with self.assertRaises(OSError):
            self.install()
        self.assertEqual(self.files(), set())
        self.assertEqual(self.calls(), [])

    def test_manifest_write_failure_reports_failed_inverses(self) -> None:
        (self.root / "manifest.json").mkdir(parents=True)
        self.fail_on("plugin marketplace remove")
        with self.assertRaises(RemoteError) as caught:
            self.install()
        self.assertEqual(caught.exception.exit_code, 8)
        self.assertIsInstance(caught.exception.__cause__, OSError)
        failed = caught.exception.details["undo_failed"]
        self.assertEqual(failed, [["codex", "plugin", "marketplace", "remove", MKT]])

    def test_reinstall_keeps_the_old_manifest_when_an_undo_fails(self) -> None:
        self.install()
        self.fail_on("plugin remove")
        with self.assertRaises(RemoteError) as caught:
            self.install()
        self.assertEqual(
            caught.exception.details["undo_failed"], [["codex", "plugin", "remove", PLUGIN]]
        )
        self.assertTrue((self.root / "manifest.json").is_file())
        self.assertTrue((self.root / "package" / "hooks.json").is_file())

    def test_uninstall_keeps_the_manifest_when_a_removal_fails(self) -> None:
        self.install()
        hooks = self.root / "package" / "hooks.json"
        hooks.unlink()
        hooks.mkdir()  # unlink of a directory fails
        with self.assertRaises(OSError):
            uninstall("codex", FakeCodexRunner(), self.data)
        self.assertTrue((self.root / "manifest.json").is_file())

    def test_failed_first_install_removes_the_directories_wev_made(self) -> None:
        self.data.mkdir()
        self.fail_on("plugin add")
        with self.assertRaises(RemoteError):
            self.install()
        self.assertFalse((self.data / "wev-skills").exists())
        self.assertTrue(self.data.is_dir())

    def test_failed_first_install_keeps_a_wev_skills_directory_that_existed(self) -> None:
        (self.data / "wev-skills").mkdir(parents=True)
        self.fail_on("plugin add")
        with self.assertRaises(RemoteError):
            self.install()
        self.assertTrue((self.data / "wev-skills").is_dir())
        self.assertFalse((self.data / "wev-skills" / "harness").exists())


class UninstallTests(InstallBase):
    def test_uninstall_undoes_registrations_and_removes_only_manifest_files(self) -> None:
        self.install()
        mine = self.root / "package" / "notes.txt"
        mine.write_text("keep")
        uninstall("codex", FakeCodexRunner(), self.data)
        self.assertEqual(
            self.calls()[2:],
            [["plugin", "remove", PLUGIN], ["plugin", "marketplace", "remove", MKT]],
        )
        self.assertTrue(mine.is_file())
        self.assertEqual(self.files(), {"package/notes.txt"})

    def test_uninstall_removes_everything_it_created(self) -> None:
        self.install()
        uninstall("codex", FakeCodexRunner(), self.data)
        self.assertEqual(self.files(), set())
        self.assertFalse((self.root / "package").exists())

    def test_uninstall_without_install_is_not_found(self) -> None:
        from wev_skills.core.errors import NotFound

        with self.assertRaises(NotFound):
            uninstall("codex", FakeCodexRunner(), self.data)

    def test_failed_undo_keeps_the_manifest_for_a_retry(self) -> None:
        self.install()
        self.fail_on("plugin remove")
        with self.assertRaises(RemoteError):
            uninstall("codex", FakeCodexRunner(), self.data)
        self.assertTrue((self.root / "manifest.json").is_file())
        self.assertTrue((self.root / "package" / "hooks.json").is_file())


class CliTests(InstallBase):
    def run_cli(self, *argv: str) -> tuple[int, dict[str, object]]:
        out = io.StringIO()
        runner = mock.patch.object(harness_install_cmd(), "SubprocessRunner", FakeCodexRunner)
        env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.data)})
        with runner, env, contextlib.redirect_stdout(out):
            code = cli.main(["harness", *argv])
        return code, json.loads(out.getvalue())

    def test_install_then_uninstall_report_next_steps(self) -> None:
        code, payload = self.run_cli("install", "--target", "codex")
        self.assertEqual(code, 0, payload)
        steps = json.dumps(payload["next_steps"])
        self.assertIn("trust", steps)
        code, _ = self.run_cli("uninstall", "--target", "codex")
        self.assertEqual(code, 0)
        self.assertEqual(self.files(), set())

    def test_only_codex_installs(self) -> None:
        env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.data)})
        with contextlib.redirect_stderr(io.StringIO()), env:
            code = cli.main(["harness", "install", "--target", "gemini"])
        self.assertEqual(code, 2)
        self.assertEqual(self.calls(), [])


def harness_install_cmd() -> object:
    from wev_skills.commands import harness

    return harness
