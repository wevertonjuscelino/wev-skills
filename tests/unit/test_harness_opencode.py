import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills import cli
from wev_skills.adapters.harness_opencode import install, uninstall
from wev_skills.core.errors import NotFound, RemoteError, StateConflict, ValidationError
from wev_skills.core.wiring import REPO_ROOT

WEV = REPO_ROOT / "bin" / "wev"


class OpenCodeBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.data = self.tmp / "data"
        self.config = self.tmp / "config" / "opencode"
        self.root = self.data / "wev-skills" / "harness" / "opencode"

    def install(self) -> object:
        return install(self.data, self.config, WEV)

    def tree(self) -> set[str]:
        return {
            p.relative_to(self.config).as_posix() for p in self.config.rglob("*") if p.is_file()
        }


class InstallTests(OpenCodeBase):
    def test_install_copies_plugin_skills_and_agents_and_lists_them(self) -> None:
        manifest = self.install()
        files = self.tree() - {"opencode.json"}  # the settings file is merged, not a manifest file
        self.assertIn("plugins/wev-guard.js", files)
        self.assertIn("skills/wev-orchestrate/SKILL.md", files)
        self.assertIn("agents/wev-architect.md", files)
        self.assertNotIn("wev-placeholder", (self.config / "plugins/wev-guard.js").read_text())
        stored = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(stored["target"], "opencode")
        self.assertEqual(sorted(stored["files"]), sorted(str(self.config / f) for f in files))
        self.assertEqual(sorted(manifest.files), sorted(stored["files"]))  # type: ignore[attr-defined]

    def test_reinstall_does_not_duplicate_and_keeps_the_person_files(self) -> None:
        (self.config / "agents").mkdir(parents=True)
        mine = self.config / "agents" / "mine.md"
        mine.write_text("mine")
        self.install()
        first = self.tree()
        self.install()
        self.assertEqual(self.tree(), first)
        self.assertEqual(mine.read_text(), "mine")

    def test_reinstall_removes_a_stale_entry_of_the_previous_manifest(self) -> None:
        self.install()
        stale = self.config / "agents" / "wev-old.md"
        stale.write_text("old")
        path = self.root / "manifest.json"
        data = json.loads(path.read_text())
        data["files"].append(str(stale))
        path.write_text(json.dumps(data))
        self.install()
        self.assertFalse(stale.exists())

    def test_install_refuses_to_overwrite_a_file_it_did_not_create(self) -> None:
        (self.config / "plugins").mkdir(parents=True)
        theirs = self.config / "plugins" / "wev-guard.js"
        theirs.write_text("theirs")
        with self.assertRaises(StateConflict) as ctx:
            self.install()
        self.assertIn("wev-guard.js", str(ctx.exception))
        self.assertEqual(theirs.read_text(), "theirs")
        self.assertEqual(self.tree(), {"plugins/wev-guard.js"})  # nothing else was written
        self.assertFalse((self.root / "manifest.json").exists())

    def test_install_refuses_a_symlinked_destination(self) -> None:
        (self.config / "skills").mkdir(parents=True)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (self.config / "skills" / "wev-orchestrate").symlink_to(elsewhere)
        with self.assertRaises((ValidationError, StateConflict)):
            self.install()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_a_symlinked_directory_is_named_in_the_error(self) -> None:
        (self.config / "skills").mkdir(parents=True)
        link = self.config / "skills" / "wev-orchestrate"
        link.symlink_to(self.tmp)
        with self.assertRaises(ValidationError) as ctx:
            self.install()
        self.assertEqual(ctx.exception.details["path"], str(link))

    def test_a_refused_install_leaves_no_empty_wev_directories(self) -> None:
        (self.config / "plugins").mkdir(parents=True)
        (self.config / "plugins" / "wev-guard.js").write_text("theirs")
        with self.assertRaises(StateConflict):
            self.install()
        self.assertFalse((self.data / "wev-skills").exists())

    def test_a_failed_copy_rolls_back_the_files_written_so_far(self) -> None:
        calls = {"n": 0}
        from wev_skills.core import fsutil

        real = fsutil.atomic_write_text

        def flaky(path: Path, text: str) -> None:
            calls["n"] += 1
            if calls["n"] == 5:
                raise OSError("disk full")
            real(path, text)

        patched = mock.patch("wev_skills.adapters.harness_install.atomic_write_text", flaky)
        with patched, self.assertRaises(RemoteError):
            self.install()
        self.assertEqual(self.tree(), set())


class McpTests(OpenCodeBase):
    @property
    def settings(self) -> Path:
        return self.config / "opencode.json"

    def _put(self, data: dict[str, object]) -> None:
        self.config.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps(data))

    def _mcp(self) -> dict[str, object]:
        return json.loads(self.settings.read_text())["mcp"]

    def test_install_writes_the_rea_server_and_keeps_the_other_keys(self) -> None:
        self._put({"theme": "x", "mcp": {"other": {"type": "local", "command": ["a"]}}})
        self.install()
        rea = self._mcp()["rea"]
        self.assertEqual(
            rea, {"type": "local", "command": [sys.executable, str(WEV), "rea", "serve"]}
        )
        self.assertIn("other", self._mcp())
        self.assertEqual(json.loads(self.settings.read_text())["theme"], "x")
        self.assertNotIn("opencode.json", [Path(f).name for f in self.manifest_files()])

    def manifest_files(self) -> list[str]:
        return json.loads((self.root / "manifest.json").read_text())["files"]

    def test_install_without_a_config_file_creates_it(self) -> None:
        self.install()
        self.assertEqual(list(self._mcp()), ["rea"])

    def test_install_refuses_a_foreign_rea_entry_and_writes_nothing(self) -> None:
        self._put({"mcp": {"rea": {"type": "local", "command": ["mine"]}}})
        before = self.settings.read_text()
        with self.assertRaises(StateConflict):
            self.install()
        self.assertEqual(self.settings.read_text(), before)
        self.assertEqual(self.tree(), {"opencode.json"})
        self.assertFalse((self.root / "manifest.json").exists())

    def test_reinstall_replaces_its_own_entry(self) -> None:
        self.install()
        with mock.patch.object(sys, "executable", "/other/python3"):
            self.install()
        self.assertEqual(self._mcp()["rea"]["command"][0], "/other/python3")  # type: ignore[index]

    def test_reinstall_refuses_an_entry_the_person_edited(self) -> None:
        self.install()
        self._put({"mcp": {"rea": {"type": "local", "command": ["edited"]}}})
        with self.assertRaises(StateConflict):
            self.install()

    def test_install_refuses_a_config_that_is_not_json(self) -> None:
        self.config.mkdir(parents=True)
        self.settings.write_text("// comment\n{}")
        with self.assertRaises(ValidationError):
            self.install()
        self.assertEqual(self.settings.read_text(), "// comment\n{}")

    def test_uninstall_removes_only_the_wev_entry(self) -> None:
        self._put({"theme": "x", "mcp": {"other": {"type": "local", "command": ["a"]}}})
        self.install()
        uninstall(self.data, self.config)
        data = json.loads(self.settings.read_text())
        self.assertEqual(
            data, {"theme": "x", "mcp": {"other": {"type": "local", "command": ["a"]}}}
        )

    def test_uninstall_deletes_a_config_that_only_held_the_wev_entry(self) -> None:
        self.install()
        uninstall(self.data, self.config)
        self.assertFalse(self.settings.exists())

    def test_uninstall_keeps_an_entry_the_person_edited(self) -> None:
        self.install()
        edited = {"mcp": {"rea": {"type": "local", "command": ["edited"]}}}
        self._put(edited)
        uninstall(self.data, self.config)
        self.assertEqual(json.loads(self.settings.read_text()), edited)

    def test_a_symlinked_config_is_refused_and_left_alone(self) -> None:
        self.config.mkdir(parents=True)
        real = self.tmp / "real.json"
        real.write_text('{"theme": "x"}')
        self.settings.symlink_to(real)
        with self.assertRaises(StateConflict):
            self.install()
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(real.read_text(), '{"theme": "x"}')
        self.assertFalse((self.root / "manifest.json").exists())

    def test_uninstall_refuses_a_config_replaced_by_a_symlink(self) -> None:
        self.install()
        real = self.tmp / "real.json"
        real.write_text(self.settings.read_text())
        self.settings.unlink()
        self.settings.symlink_to(real)
        with self.assertRaises(StateConflict):
            uninstall(self.data, self.config)
        self.assertTrue(self.settings.is_symlink())

    def test_the_file_mode_survives_install_and_uninstall(self) -> None:
        self._put({"theme": "x", "mcp": {"other": {"type": "local", "command": ["a"]}}})
        self.settings.chmod(0o644)
        self.install()
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o644)
        uninstall(self.data, self.config)
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o644)

    def test_a_jsonc_config_without_a_json_one_is_refused(self) -> None:
        self.config.mkdir(parents=True)
        (self.config / "opencode.jsonc").write_text("{}")
        with self.assertRaises(ValidationError):
            self.install()
        self.assertFalse(self.settings.exists())

    def test_a_failing_restore_does_not_skip_the_cleanup(self) -> None:
        self._put({"theme": "x"})
        patched = mock.patch(
            "wev_skills.adapters.harness_opencode._write", side_effect=OSError("x")
        )
        restore = mock.patch(
            "wev_skills.adapters.harness_opencode_mcp.restore", side_effect=OSError("restore")
        )
        with patched, restore, self.assertRaises(OSError) as ctx:
            self.install()
        self.assertEqual(str(ctx.exception), "restore")
        self.assertIsNotNone(ctx.exception.__context__)
        self.assertEqual(self.tree(), {"opencode.json"})

    def test_a_failed_install_restores_the_config_file(self) -> None:
        self._put({"theme": "x"})
        before = self.settings.read_text()
        patched = mock.patch(
            "wev_skills.adapters.harness_opencode._write", side_effect=OSError("x")
        )
        with patched, self.assertRaises(OSError):
            self.install()
        self.assertEqual(self.settings.read_text(), before)


class UninstallTests(OpenCodeBase):
    def test_uninstall_removes_only_the_manifest_files(self) -> None:
        self.install()
        mine = self.config / "plugins" / "mine.js"
        mine.write_text("mine")
        extra = self.config / "skills" / "wev-orchestrate" / "mine.md"
        extra.write_text("mine")
        uninstall(self.data, self.config)
        self.assertEqual(self.tree(), {"plugins/mine.js", "skills/wev-orchestrate/mine.md"})
        self.assertFalse((self.root / "manifest.json").exists())

    def test_uninstall_removes_the_directories_wev_created_only(self) -> None:
        (self.config / "agents").mkdir(parents=True)  # the person's own, empty
        self.install()
        uninstall(self.data, self.config)
        self.assertTrue((self.config / "agents").is_dir())
        self.assertFalse((self.config / "plugins").exists())
        self.assertFalse((self.config / "skills").exists())

    def test_reinstall_keeps_knowing_which_directories_wev_created(self) -> None:
        self.install()
        self.install()
        uninstall(self.data, self.config)
        self.assertFalse((self.config / "plugins").exists())

    def test_uninstall_without_manifest_is_not_found(self) -> None:
        with self.assertRaises(NotFound):
            uninstall(self.data, self.config)

    def test_a_manifest_entry_outside_the_wev_entries_is_refused(self) -> None:
        self.install()
        victim = self.config / "agents" / "mine.md"
        victim.write_text("mine")
        path = self.root / "manifest.json"
        data = json.loads(path.read_text())
        data["files"].append(str(victim))
        path.write_text(json.dumps(data))
        with self.assertRaises(ValidationError):
            uninstall(self.data, self.config)
        self.assertTrue(victim.is_file())

    def test_a_manifest_entry_with_dotdot_is_refused(self) -> None:
        self.install()
        victim = self.tmp / "victim.txt"
        victim.write_text("x")
        path = self.root / "manifest.json"
        data = json.loads(path.read_text())
        data["files"].append(str(self.config / "plugins" / ".." / ".." / "victim.txt"))
        path.write_text(json.dumps(data))
        with self.assertRaises(ValidationError):
            uninstall(self.data, self.config)
        self.assertTrue(victim.is_file())


class CommandTests(OpenCodeBase):
    def run_cli(self, *argv: str) -> tuple[int, dict[str, object]]:
        env = mock.patch.dict(
            os.environ,
            {"XDG_DATA_HOME": str(self.data), "XDG_CONFIG_HOME": str(self.tmp / "config")},
        )
        out = io.StringIO()
        with env, contextlib.redirect_stdout(out):
            code = cli.main(["harness", *argv])
        return code, json.loads(out.getvalue())

    def test_install_and_uninstall_through_the_cli(self) -> None:
        code, payload = self.run_cli("install", "--target", "opencode")
        self.assertEqual(code, 0, payload)
        self.assertIn("plugins/wev-guard.js", self.tree())
        self.assertIn("opencode", json.dumps(payload["next_steps"]))
        self.assertTrue(any("run brief" in note for note in payload["skipped"]))
        code, _ = self.run_cli("uninstall", "--target", "opencode")
        self.assertEqual(code, 0)
        self.assertEqual(self.tree(), set())
