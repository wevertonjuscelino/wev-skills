from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from tests.unit._agent_helpers import RepoCase, data, run
from wev_skills.commands.agent import catalog_directories, parse_overrides
from wev_skills.core.errors import ValidationError


class AgentCommandTests(RepoCase):
    def test_catalog_directories_exist_in_this_checkout(self) -> None:
        self.assertEqual([p.name for p in catalog_directories()], ["templates", "examples"])

    def test_list_includes_catalog_and_extra_dir(self) -> None:
        extra = self.tmp / "extra"
        extra.mkdir()
        (extra / "mine.json").write_text(json.dumps(data("mine")), encoding="utf-8")
        code, out, _ = run("agent", "list", "--dir", str(extra))
        ids = [a["id"] for a in out["agents"]]
        self.assertEqual(code, 0)
        self.assertEqual(ids, sorted(ids))
        self.assertIn("mine", ids)
        self.assertIn("code-reviewer", ids)

    def test_list_localizes_with_global_lang(self) -> None:
        _, out, _ = run("--lang", "pt-BR", "agent", "list")
        names = {a["id"]: a["name"] for a in out["agents"]}
        self.assertEqual(names["architect"], "Arquiteto")

    def test_show_raw_and_resolved(self) -> None:
        _, raw, _ = run("agent", "show", "code-reviewer")
        _, resolved, _ = run("agent", "show", "code-reviewer", "--resolved")
        self.assertEqual(raw["extends"], "base-reviewer")
        self.assertNotIn("extends", resolved)
        self.assertIn("Edit", resolved["tools"]["deny"])
        self.assertNotIn("Edit", resolved["tools"]["allow"])

    def test_show_unknown_agent_exits_not_found(self) -> None:
        code, _, err = run("agent", "show", "ghost")
        self.assertEqual(code, 7)
        self.assertIn("agent_not_found", err)

    def test_validate_accepts_good_and_rejects_bad_file(self) -> None:
        good = self.write("good.json", data("fresh", extends="base"))
        bad = self.write("bad.json", data("fresh", typo=1))
        code, out, _ = run("agent", "validate", str(good))
        self.assertEqual((code, out["valid"]), (0, True))
        code, _, err = run("agent", "validate", str(bad))
        self.assertEqual(code, 2)
        self.assertIn("/typo", err)

    def test_validate_rejects_unknown_parent(self) -> None:
        orphan = self.write("o.json", data("orphan", extends="ghost"))
        code, _, err = run("agent", "validate", str(orphan))
        self.assertEqual(code, 2)
        self.assertIn("ghost", err)

    def test_create_writes_child_spec_and_refuses_overwrite_without_force(self) -> None:
        out = self.tmp / "new.json"
        args = [
            "agent",
            "create",
            "--template",
            "base-engineer",
            "--id",
            "my-eng",
            "--set",
            "model=premium",
            "--set",
            "permissions.max_risk=low",
            "--set",
            'specialties=["x"]',
            "--out",
            str(out),
        ]
        code, result, _ = run(*args)
        self.assertEqual(code, 0)
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((written["extends"], written["model"]), ("base-engineer", "premium"))
        self.assertEqual(result["agent"]["permissions"]["max_risk"], "low")
        code, _, err = run(*args)
        self.assertEqual(code, 2)
        self.assertIn("--force", err)
        code, _, _ = run(*args, "--force")
        self.assertEqual(code, 0)

    def test_create_written_file_validates(self) -> None:
        out = self.tmp / "v.json"
        run("agent", "create", "--template", "base-reviewer", "--id", "rev", "--out", str(out))
        code, result, _ = run("agent", "validate", str(out))
        self.assertEqual((code, result["id"]), (0, "rev"))

    def test_create_rejects_widening_override(self) -> None:
        code, _, err = run(
            "agent",
            "create",
            "--template",
            "code-reviewer",
            "--id",
            "x",
            "--set",
            "permissions.may_mutate=true",
        )
        self.assertEqual(code, 2)
        self.assertIn("permissions.may_mutate", err)

    def test_export_writes_markdown_for_selected_ids(self) -> None:
        out = self.tmp / "out"
        code, result, _ = run(
            "agent",
            "export",
            "--id",
            "architect",
            "--id",
            "researcher",
            "--out",
            str(out),
            "--lang",
            "en",
        )
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["architect.md", "researcher.md"])
        self.assertEqual(len(result["exported"]), 2)

    def test_export_names_the_real_source_of_each_spec(self) -> None:
        specs = self.tmp / "specs"
        specs.mkdir()
        (specs / "mine.json").write_text(json.dumps(data("mine")), encoding="utf-8")
        out = self.tmp / "out"
        previous = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, previous)
        code, _, err = run(
            "agent", "export", "--dir", "specs", "--id", "mine", "--id", "architect",
            "--out", str(out), "--lang", "en",
        )  # fmt: skip
        self.assertEqual(code, 0, err)
        mine = (out / "mine.md").read_text(encoding="utf-8")
        self.assertIn("<!-- Generated from specs/mine.json. Do not edit by hand. -->", mine)
        self.assertNotIn("agent-specs/examples", mine)
        shipped = (out / "architect.md").read_text(encoding="utf-8")
        self.assertIn("<!-- Generated from agent-specs/examples/architect.json.", shipped)

    def test_list_skips_json_that_is_not_a_spec_and_reports_it(self) -> None:
        extra = self.tmp / "extra"
        extra.mkdir()
        (extra / "mine.json").write_text(json.dumps(data("mine")), encoding="utf-8")
        (extra / "package.json").write_text(json.dumps({"name": "site"}), encoding="utf-8")
        code, out, _ = run("agent", "list", "--dir", str(extra))
        self.assertEqual(code, 0)
        self.assertIn("mine", [a["id"] for a in out["agents"]])
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("package.json", out["warnings"][0])
        (extra / "broken.json").write_text(
            json.dumps({"schema_version": 1, "id": "broken"}), encoding="utf-8"
        )
        code, _, err = run("agent", "list", "--dir", str(extra))
        self.assertEqual(code, 2)
        self.assertIn("invalid_agent_file", err)

    def frontmatter(self, path: Path) -> dict[str, str]:
        lines = path.read_text(encoding="utf-8").split("\n")
        front = lines[1 : lines.index("---", 1)]
        return {k: v.strip().strip('"') for k, _, v in (line.partition(":") for line in front)}

    def test_export_applies_the_configured_tool_profile(self) -> None:
        config = self.write("wev.json", {"harness": {"tool_profile": "lean"}})
        structured, lean = self.tmp / "structured", self.tmp / "lean"
        ids = ("--id", "senior-engineer", "--id", "code-reviewer")
        run("agent", "export", *ids, "--out", str(structured), "--lang", "en")
        code, result, _ = run(
            "--config", str(config), "agent", "export", *ids, "--out", str(lean), "--lang", "en"
        )
        self.assertEqual((code, result["tool_profile"]), (0, "lean"))
        full = self.frontmatter(structured / "senior-engineer.md")
        reduced = self.frontmatter(lean / "senior-engineer.md")
        self.assertEqual(full["tools"], "Read, Grep, Glob, Edit, Write, Bash")
        self.assertEqual(reduced["tools"], "Read, Edit, Bash")
        self.assertEqual(reduced.get("disallowedTools"), full.get("disallowedTools"))
        self.assertEqual(
            (lean / "code-reviewer.md").read_bytes(), (structured / "code-reviewer.md").read_bytes()
        )

    def test_export_auto_profile_is_lean_only_for_premium_agents(self) -> None:
        out = self.tmp / "auto"
        specs = self.tmp / "specs"
        specs.mkdir()
        strong = data(
            "strong",
            extends="base-engineer",
            model="premium",
            tools={"allow": ["Grep"]},
        )
        (specs / "strong.json").write_text(json.dumps(strong), encoding="utf-8")
        run(
            "agent", "export", "--dir", str(specs), "--id", "strong", "--id", "senior-engineer",
            "--tool-profile", "auto", "--out", str(out), "--lang", "en",
        )  # fmt: skip
        self.assertEqual(self.frontmatter(out / "strong.md")["tools"], "Read, Edit, Bash")
        self.assertIn("Grep", self.frontmatter(out / "senior-engineer.md")["tools"])

    def test_export_default_skips_templates(self) -> None:
        out = self.tmp / "all"
        run("agent", "export", "--out", str(out), "--lang", "en")
        names = {p.stem for p in out.iterdir()}
        self.assertIn("decision-judge", names)
        self.assertFalse(names & {"base", "base-engineer", "base-reviewer"})


class ParseOverridesTests(unittest.TestCase):
    def test_nested_keys_and_json_values(self) -> None:
        got = parse_overrides(["a.b=1", "a.c=true", "d=text", 'e=["x","y"]', "f=a=b"])
        self.assertEqual(got, {"a": {"b": 1, "c": True}, "d": "text", "e": ["x", "y"], "f": "a=b"})

    def test_rejects_pair_without_equals_or_conflicting_nesting(self) -> None:
        with self.assertRaises(ValidationError):
            parse_overrides(["novalue"])
        with self.assertRaises(ValidationError):
            parse_overrides(["a=1", "a.b=2"])


if __name__ == "__main__":
    unittest.main()
