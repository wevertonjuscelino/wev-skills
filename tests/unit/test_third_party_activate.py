"""Activation symlinks: only the links in the manifest are ever created, changed or removed."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.third_party import activate


class ActivateCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.home = base / "data"
        self.claude, self.agents, self.absent = base / "c", base / "a", base / "none"
        self.claude.mkdir()
        self.agents.mkdir()
        self.roots = [self.claude, self.agents, self.absent]
        self.version = self.home / "agent-skills" / "v1"
        for name in ("alpha", "beta"):
            self.skill(name)
        os.symlink("v1", self.home / "agent-skills" / "current")

    def skill(self, name: str) -> None:
        (self.version / "skills" / name).mkdir(parents=True)
        (self.version / "skills" / name / "SKILL.md").write_text("---\nname: x\n---\n")

    def test_links_in_every_existing_root_and_the_manifest_lists_them(self) -> None:
        manifest = activate.activate(self.home, self.roots)
        current = self.home / "agent-skills" / "current" / "skills"
        for root in (self.claude, self.agents):
            self.assertEqual(os.readlink(root / "alpha"), str(current / "alpha"))
            self.assertTrue((root / "beta").is_dir())
        self.assertFalse(self.absent.exists())
        self.assertEqual(len(manifest.files), 4)
        saved = json.loads((self.home / "manifest.json").read_text())
        self.assertEqual(sorted(saved["files"]), sorted(manifest.files))

    def test_a_foreign_entry_is_refused_and_nothing_is_created(self) -> None:
        (self.agents / "beta").mkdir()
        with self.assertRaises(StateConflict) as caught:
            activate.activate(self.home, self.roots)
        self.assertIn("beta", caught.exception.message)
        self.assertFalse((self.claude / "alpha").exists())
        self.assertFalse((self.home / "manifest.json").exists())

    def test_an_owned_path_replaced_by_a_real_file_is_refused_and_kept(self) -> None:
        activate.activate(self.home, self.roots)
        (self.claude / "alpha").unlink()
        (self.claude / "alpha").write_text("mine")
        with self.assertRaises(StateConflict) as caught:
            activate.activate(self.home, self.roots)
        self.assertIn("alpha", caught.exception.message)
        self.assertEqual((self.claude / "alpha").read_text(), "mine")

    def test_an_owned_path_replaced_by_a_real_dir_is_refused_and_kept(self) -> None:
        activate.activate(self.home, self.roots)
        (self.claude / "alpha").unlink()
        (self.claude / "alpha").mkdir()
        (self.claude / "alpha" / "f").write_text("mine")
        with self.assertRaises(StateConflict):
            activate.activate(self.home, self.roots)
        self.assertEqual((self.claude / "alpha" / "f").read_text(), "mine")

    def test_rerun_is_stable_and_drops_links_of_removed_skills(self) -> None:
        activate.activate(self.home, self.roots)
        (self.version / "skills" / "beta" / "SKILL.md").unlink()
        (self.version / "skills" / "beta").rmdir()
        manifest = activate.activate(self.home, self.roots)
        self.assertEqual(len(manifest.files), 2)
        self.assertFalse((self.claude / "beta").is_symlink())

    def test_only_directories_with_a_skill_md_are_linked(self) -> None:
        (self.version / "skills" / "notes").mkdir()
        (self.version / "skills" / "README.md").write_text("x")
        manifest = activate.activate(self.home, self.roots)
        self.assertEqual(sorted(Path(f).name for f in manifest.files), ["alpha"] * 2 + ["beta"] * 2)
        self.assertFalse(os.path.lexists(self.claude / "notes"))

    def repoint(self, link: Path) -> Path:
        mine = self.home.parent / f"mine-{link.name}"
        mine.mkdir()
        link.unlink()
        os.symlink(mine, link)
        return mine

    def test_an_owned_link_pointing_elsewhere_is_foreign_everywhere(self) -> None:
        activate.activate(self.home, self.roots)
        mine = self.repoint(self.claude / "alpha")
        with self.assertRaises(StateConflict) as caught:
            activate.activate(self.home, self.roots)
        self.assertIn("alpha", caught.exception.message)
        self.assertEqual(os.readlink(self.claude / "alpha"), str(mine))
        removed = activate.deactivate(self.home, self.roots)
        self.assertNotIn(str(self.claude / "alpha"), removed)
        self.assertEqual(os.readlink(self.claude / "alpha"), str(mine))

    def test_a_stale_owned_link_pointing_elsewhere_is_kept(self) -> None:
        activate.activate(self.home, self.roots)
        mine = self.repoint(self.claude / "beta")
        (self.version / "skills" / "beta" / "SKILL.md").unlink()
        manifest = activate.activate(self.home, self.roots)
        self.assertEqual(os.readlink(self.claude / "beta"), str(mine))
        self.assertNotIn(str(self.claude / "beta"), manifest.files)

    def test_deactivate_removes_only_manifest_links(self) -> None:
        activate.activate(self.home, self.roots)
        (self.claude / "mine").mkdir()
        (self.agents / "alpha").unlink()
        (self.agents / "alpha").mkdir()  # the person replaced our link with a real directory
        activate.deactivate(self.home, self.roots)
        self.assertTrue((self.claude / "mine").is_dir())
        self.assertTrue((self.agents / "alpha").is_dir())
        self.assertFalse((self.claude / "alpha").is_symlink())
        self.assertFalse((self.agents / "beta").is_symlink())
        self.assertFalse((self.home / "manifest.json").exists())

    def test_a_manifest_naming_a_path_outside_the_roots_is_rejected(self) -> None:
        victim = self.home.parent / "victim"
        victim.write_text("x")
        data = {"target": "agent-skills", "files": [str(victim)], "registrations": []}
        (self.home / "manifest.json").write_text(json.dumps(data))
        with self.assertRaises(ValidationError):
            activate.deactivate(self.home, self.roots)
        self.assertTrue(victim.exists())

    def test_without_a_manifest_deactivate_does_nothing(self) -> None:
        self.assertEqual(activate.deactivate(self.home, self.roots), ())

    def test_activate_needs_an_installed_agent_skills(self) -> None:
        (self.home / "agent-skills" / "current").unlink()
        with self.assertRaises(StateConflict):
            activate.activate(self.home, self.roots)

    def test_an_unsafe_skill_name_is_refused(self) -> None:
        self.skill("bad name")
        with self.assertRaises(ValidationError):
            activate.activate(self.home, self.roots)


if __name__ == "__main__":
    unittest.main()
