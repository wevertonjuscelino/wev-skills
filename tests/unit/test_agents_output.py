"""Where ``wev agent create`` and ``wev agent export`` may write."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.unit._agent_helpers import data
from wev_skills.agents.output import (
    OutputScope,
    case_collision,
    confine,
    refuse_case_collision,
    refuse_foreign_spec_file,
)
from wev_skills.core.errors import PermissionDenied

ENV_FILE = "." + "env"


class OutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.root = self.base / "proj"
        for name in (".git/hooks", ".wev", ".claude", "specs"):
            (self.root / name).mkdir(parents=True)
        self.scope = OutputScope(self.root, self.root / ".wev", (".git", ENV_FILE, ".wev"))
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)

    def refused(self, target: str | Path) -> str:
        with self.assertRaises(PermissionDenied) as ctx:
            confine(Path(target), self.scope)
        self.assertEqual(ctx.exception.code, "output_refused")
        return str(ctx.exception.details["reason"])

    def test_a_path_inside_the_root_is_returned_resolved(self) -> None:
        self.assertEqual(confine(Path("specs/new.json"), self.scope), self.root / "specs/new.json")
        self.assertEqual(confine(Path("."), self.scope), self.root)
        self.assertEqual(confine(Path("not/yet/there"), self.scope), self.root / "not/yet/there")

    def test_a_path_outside_the_root_is_refused(self) -> None:
        self.assertEqual(self.refused(self.base / "x.json"), "outside")
        self.assertEqual(self.refused("../x.json"), "outside")
        self.assertEqual(self.refused("specs/../../x.json"), "outside")

    def test_a_symlink_that_leaves_the_root_is_refused(self) -> None:
        (self.base / "elsewhere").mkdir()
        (self.root / "link").symlink_to(self.base / "elsewhere")
        (self.root / "file.json").symlink_to(self.base / "victim.json")
        self.assertEqual(self.refused("link/x.json"), "outside")
        self.assertEqual(self.refused("file.json"), "outside")

    def test_the_state_directory_is_refused(self) -> None:
        scope = OutputScope(self.root, self.root / ".wev", ())
        for target in (".wev/approvals.json", ".wev", ".WEV/approvals.json"):
            with self.subTest(target=target), self.assertRaises(PermissionDenied) as ctx:
                confine(Path(target), scope)
            self.assertEqual(ctx.exception.details["reason"], "state")

    def test_git_and_claude_directories_are_refused_at_any_depth(self) -> None:
        scope = OutputScope(self.root, self.root / ".wev", ())
        for target in (
            ".git/hooks/x.json",
            ".claude/settings.json",
            ".claude/agents",
            "pkg/.claude/agents/a.md",
            "pkg/.git/x.json",
            ".GIT/x.json",
            ".Claude/x.json",
        ):
            with self.subTest(target=target), self.assertRaises(PermissionDenied) as ctx:
                confine(Path(target), scope)
            self.assertEqual(ctx.exception.details["reason"], "forbidden")

    def test_a_symlink_into_a_forbidden_directory_is_refused(self) -> None:
        (self.root / "hooks").symlink_to(self.root / ".git" / "hooks")
        scope = OutputScope(self.root, self.root / ".wev", ())
        with self.assertRaises(PermissionDenied) as ctx:
            confine(Path("hooks/x.json"), scope)
        self.assertEqual(ctx.exception.details["reason"], "forbidden")

    def test_protected_paths_are_refused(self) -> None:
        scope = OutputScope(self.root, self.root / ".wev", (ENV_FILE, "secrets/keys"))
        for target in (ENV_FILE, f"sub/{ENV_FILE}", "secrets/keys/a.json"):
            with self.subTest(target=target), self.assertRaises(PermissionDenied) as ctx:
                confine(Path(target), scope)
            self.assertEqual(ctx.exception.details["reason"], "protected")

    def test_a_root_below_a_claude_directory_is_still_usable(self) -> None:
        root = self.base / ".claude" / "worktrees" / "w"
        root.mkdir(parents=True)
        scope = OutputScope(root, root / ".wev", (".git",))
        self.assertEqual(confine(root / "a.json", scope), root / "a.json")

    def test_case_collision_names_the_entry_that_differs_only_by_case(self) -> None:
        (self.root / "CLAUDE.md").write_text("# rules", encoding="utf-8")
        self.assertEqual(case_collision(self.root / "claude.md"), "CLAUDE.md")
        self.assertIsNone(case_collision(self.root / "CLAUDE.md"))
        self.assertIsNone(case_collision(self.root / "other.md"))
        self.assertIsNone(case_collision(self.root / "missing-dir" / "claude.md"))
        with self.assertRaises(PermissionDenied) as ctx:
            refuse_case_collision(self.root / "claude.md")
        self.assertEqual(ctx.exception.code, "case_collision")
        refuse_case_collision(self.root / "other.md")

    def test_only_an_existing_agent_spec_may_be_replaced(self) -> None:
        missing, spec = self.root / "specs/new.json", self.root / "specs/a.json"
        spec.write_text(json.dumps(data("a")), encoding="utf-8")
        self.assertFalse(refuse_foreign_spec_file(missing))
        self.assertTrue(refuse_foreign_spec_file(spec))
        foreign = {
            "settings.json": json.dumps({"hooks": {}}),
            "list.json": "[1]",
            "broken.json": "{",
            "half.json": json.dumps({"schema_version": 1, "id": "a"}),
            "binary.json": "\udcff",
        }
        for name, text in foreign.items():
            path = self.root / "specs" / name
            path.write_bytes(text.encode("utf-8", "surrogateescape"))
            with self.subTest(name=name), self.assertRaises(PermissionDenied) as ctx:
                refuse_foreign_spec_file(path)
            self.assertEqual(ctx.exception.code, "not_agent_spec")
        with self.assertRaises(PermissionDenied):
            refuse_foreign_spec_file(self.root / "specs")


if __name__ == "__main__":
    unittest.main()
