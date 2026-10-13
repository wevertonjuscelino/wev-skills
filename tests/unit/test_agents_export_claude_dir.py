"""``wev agent export --out .claude/agents`` is allowed, and nothing else under ``.claude``."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from tests.unit._agent_helpers import RepoCase, run
from wev_skills.adapters.claude_code.subagent import GENERATED_MARKER

IDS = ("--id", "architect", "--id", "researcher")
AGENTS = ".claude/agents"


def export(out: str, *ids: str) -> tuple[int, object, str]:
    return run("agent", "export", *(ids or IDS), "--out", out)


class ExportIntoProjectAgentsTests(RepoCase):
    def test_exports_into_the_project_agents_directory_and_creates_it(self) -> None:
        code, out, err = export(AGENTS)
        self.assertEqual(code, 0, err)
        target = self.tmp / ".claude" / "agents"
        names = sorted(p.name for p in target.iterdir())
        self.assertEqual(names, ["architect.md", "researcher.md"])
        self.assertEqual(sorted(p.name for p in (self.tmp / ".claude").iterdir()), ["agents"])
        for path in target.iterdir():
            self.assertIn(GENERATED_MARKER, path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(out["exported"]), sorted(str(p) for p in target.iterdir()))  # type: ignore[index]

    def test_works_from_a_subdirectory_of_the_repository(self) -> None:
        (self.tmp / "sub").mkdir()
        os.chdir(self.tmp / "sub")
        self.assertEqual(export("../.claude/agents")[0], 0)
        self.assertTrue((self.tmp / ".claude" / "agents" / "architect.md").is_file())

    def test_replaces_only_files_it_generated(self) -> None:
        self.assertEqual(export(AGENTS)[0], 0)
        self.assertEqual(export(AGENTS)[0], 0)
        notes = self.tmp / ".claude" / "agents" / "researcher.md"
        notes.write_text("# my own agent\n", encoding="utf-8")
        code, _, err = export(AGENTS)
        self.assertEqual(code, 3)
        self.assertIn("not_generated_file", err)
        self.assertEqual(notes.read_text(encoding="utf-8"), "# my own agent\n")

    def test_leaves_other_files_in_the_directory_alone(self) -> None:
        agents = self.tmp / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "mine.md").write_text("mine\n", encoding="utf-8")
        self.assertEqual(export(AGENTS)[0], 0)
        self.assertEqual((agents / "mine.md").read_text(encoding="utf-8"), "mine\n")

    def test_refuses_a_symlinked_file_inside(self) -> None:
        outside = self.tmp.parent / "elsewhere.md"
        outside.write_text("keep\n", encoding="utf-8")
        agents = self.tmp / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "architect.md").symlink_to(outside)
        code, _, _ = export(AGENTS, "--id", "architect")
        self.assertNotEqual(code, 0)
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep\n")


class EverythingElseUnderClaudeStaysRefusedTests(RepoCase):
    def refused(self, target: str) -> None:
        code, _, err = export(target)
        self.assertEqual(code, 3, target)
        self.assertIn("output_refused", err, target)

    def test_settings_hooks_commands_skills_and_the_directory_itself(self) -> None:
        targets = (
            ".claude",
            ".claude/settings.json",
            ".claude/settings.local.json",
            ".claude/hooks",
            ".claude/hooks/agents",
            ".claude/commands",
            ".claude/skills",
            ".claude/agents/hooks",
            ".claude/agents/..",
            ".claude/agents/../hooks",
        )
        for target in targets:
            with self.subTest(target=target):
                self.refused(target)
        self.assertFalse((self.tmp / ".claude").exists())

    def test_existing_settings_are_never_touched(self) -> None:
        settings = self.write(".claude/settings.json", {"permissions": {"deny": ["Bash(rm:*)"]}})
        before = settings.read_bytes()
        self.refused(".claude/settings.json")
        self.refused(".claude")
        self.assertEqual(settings.read_bytes(), before)
        names = sorted(p.name for p in (self.tmp / ".claude").iterdir())
        self.assertEqual(names, ["settings.json"])

    def test_case_variants_of_the_directory_names_are_refused(self) -> None:
        for target in (".Claude/agents", ".CLAUDE/agents", ".claude/Agents", ".claude/AGENTS"):
            with self.subTest(target=target):
                self.refused(target)
        self.assertFalse((self.tmp / ".claude").exists())
        self.assertFalse((self.tmp / ".Claude").exists())

    def test_a_directory_that_differs_only_by_case_on_disk_is_refused(self) -> None:
        (self.tmp / ".Claude" / "agents").mkdir(parents=True)
        code, _, err = export(AGENTS)
        self.assertEqual(code, 3)
        self.assertIn("case_collision", err)
        self.assertEqual(list((self.tmp / ".Claude" / "agents").iterdir()), [])

    def test_a_symlinked_agents_directory_is_refused(self) -> None:
        for destination in (self.tmp.parent / "elsewhere", self.tmp / "inside"):
            with self.subTest(destination=destination.name):
                destination.mkdir()
                agents = self.tmp / ".claude" / "agents"
                agents.parent.mkdir(parents=True, exist_ok=True)
                agents.symlink_to(destination, target_is_directory=True)
                self.refused(AGENTS)
                self.assertEqual(list(destination.iterdir()), [])
                agents.unlink()

    def test_a_symlinked_claude_directory_is_refused(self) -> None:
        elsewhere = self.tmp.parent / "elsewhere"
        (elsewhere / "agents").mkdir(parents=True)
        (self.tmp / ".claude").symlink_to(elsewhere, target_is_directory=True)
        self.refused(AGENTS)
        self.assertEqual(list((elsewhere / "agents").iterdir()), [])

    def test_a_file_named_agents_is_refused(self) -> None:
        self.write(".claude/agents", {})
        self.refused(AGENTS)

    def test_a_protected_path_configuration_still_applies(self) -> None:
        config = self.write("c.json", {"permissions": {"protected_paths": [AGENTS]}})
        code, _, err = run("--config", str(config), "agent", "export", *IDS, "--out", AGENTS)
        self.assertEqual(code, 3)
        self.assertIn("output_refused", err)
        self.assertFalse((self.tmp / ".claude").exists())

    def test_agent_create_still_cannot_write_under_claude(self) -> None:
        base = ("agent", "create", "--template", "base", "--id", "z1", "--out")
        for target in (".claude/agents/z1.json", ".claude/settings.json", ".claude/hooks/z1.json"):
            with self.subTest(target=target):
                code, _, err = run(*base, target)
                self.assertEqual(code, 3)
                self.assertIn("output_refused", err)
        self.assertFalse(Path(self.tmp, ".claude").exists())


if __name__ == "__main__":
    unittest.main()
