from __future__ import annotations

import json
import unittest
from pathlib import Path

from wev_skills.adapters.claude_code.subagent import render_subagent
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.agents.spec import validate_data
from wev_skills.core.errors import ValidationError

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "agent-specs" / "templates"
EXAMPLES = ROOT / "agent-specs" / "examples"
EXPECTED_EXAMPLES = {
    "architect",
    "senior-engineer",
    "researcher",
    "code-reviewer",
    "security-auditor",
    "test-engineer",
    "frontend-engineer",
    "remote-ops",
    "decision-judge",
    "context-manager",
}
EXPECTED_TEMPLATES = {"base", "base-engineer", "base-reviewer"}
CONTRACT_WORDS = ("completed and verified", "partially completed", "blocked", "not executed")


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = AgentRegistry().discover([TEMPLATES, EXAMPLES])
        cls.factory = AgentFactory(cls.registry)
        cls.resolved = {s.id: cls.factory.resolve(s) for s in cls.registry.list()}

    def test_expected_templates_and_examples_exist(self) -> None:
        self.assertEqual({p.stem for p in TEMPLATES.glob("*.json")}, EXPECTED_TEMPLATES)
        self.assertEqual({p.stem for p in EXAMPLES.glob("*.json")}, EXPECTED_EXAMPLES)

    def test_file_names_match_ids_and_documents_validate(self) -> None:
        for path in [*TEMPLATES.glob("*.json"), *EXAMPLES.glob("*.json")]:
            with self.subTest(path=path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(validate_data(doc), [])
                self.assertEqual(doc["id"], path.stem)

    def test_every_spec_resolves_and_examples_extend_a_template(self) -> None:
        for agent_id in EXPECTED_EXAMPLES:
            with self.subTest(agent_id=agent_id):
                self.assertIsNone(self.resolved[agent_id].extends)
                self.assertIn(self.registry.get(agent_id).extends, self.registry_ids())

    def registry_ids(self) -> set[str]:
        return {s.id for s in self.registry.list()}

    def test_portuguese_text_exists_for_every_localizable_field(self) -> None:
        for agent_id, spec in self.resolved.items():
            for text in spec.localizable_texts():
                with self.subTest(agent_id=agent_id, text=str(text)[:40]):
                    self.assertTrue(text.has("pt-BR"))
                    self.assertNotEqual(text.get("pt-BR"), str(text))

    def test_examples_have_distinct_specialties_and_substance(self) -> None:
        seen: dict[str, str] = {}
        for agent_id in EXPECTED_EXAMPLES:
            spec = self.resolved[agent_id]
            self.assertGreaterEqual(len(spec.responsibilities), 3, agent_id)
            self.assertGreaterEqual(len(spec.success_criteria), 2, agent_id)
            self.assertTrue(spec.tools.allow, agent_id)
            for tag in spec.specialties:
                self.assertNotIn(tag, seen, f"{tag} used by {seen.get(tag)} and {agent_id}")
                seen[tag] = agent_id

    def test_instructions_state_reporting_contract_and_no_delegation(self) -> None:
        for agent_id in EXPECTED_EXAMPLES | EXPECTED_TEMPLATES:
            for lang in ("en", "pt-BR"):
                with self.subTest(agent_id=agent_id, lang=lang):
                    text = self.resolved[agent_id].localized(lang).instructions.lower()
                    if lang == "en":
                        for word in CONTRACT_WORDS:
                            self.assertIn(word, text)
                        self.assertIn("do not delegate", text)
                    else:
                        self.assertIn("não delegue", text)

    def test_permissions_match_the_roles(self) -> None:
        for agent_id in (
            "code-reviewer",
            "security-auditor",
            "decision-judge",
            "researcher",
            "architect",
            "context-manager",
            "remote-ops",
        ):
            self.assertFalse(self.resolved[agent_id].permissions.may_mutate, agent_id)
        for agent_id in ("senior-engineer", "test-engineer", "frontend-engineer"):
            self.assertTrue(self.resolved[agent_id].permissions.may_mutate, agent_id)
        remote = [i for i, s in self.resolved.items() if s.permissions.may_use_remote]
        self.assertEqual(remote, ["remote-ops"])

    def test_decision_judge_is_read_only_and_cannot_run_commands(self) -> None:
        tools = self.resolved["decision-judge"].tools
        self.assertEqual(set(tools.allow), {"Read", "Grep", "Glob"})
        self.assertIn("Bash", tools.deny)

    def test_reviewers_cannot_edit(self) -> None:
        for agent_id in ("code-reviewer", "security-auditor", "decision-judge"):
            tools = self.resolved[agent_id].tools
            self.assertFalse({"Edit", "Write"} & set(tools.allow), agent_id)
            self.assertTrue({"Edit", "Write"} <= set(tools.deny), agent_id)

    def test_reviewers_and_read_only_examples_set_a_permission_ceiling(self) -> None:
        for agent_id in ("base-reviewer", "code-reviewer", "security-auditor", "decision-judge"):
            self.assertIs(self.registry.get(agent_id).permissions.ceiling, True, agent_id)
        self.assertIs(self.registry.get("researcher").permissions.ceiling, True)
        for agent_id in ("base", "base-engineer"):
            self.assertIsNone(self.resolved[agent_id].permissions.ceiling, agent_id)

    def test_nothing_derived_from_a_reviewer_can_gain_write_access(self) -> None:
        for parent in ("base-reviewer", "code-reviewer", "security-auditor", "decision-judge"):
            for widened in ({"may_mutate": True}, {"may_use_remote": True}, {"ceiling": False}):
                overrides = {"id": "sneaky", "permissions": widened}
                with (
                    self.subTest(parent=parent, widened=widened),
                    self.assertRaises(ValidationError),
                ):
                    self.factory.create(parent, overrides)
        allowed = self.factory.create(
            "code-reviewer", {"id": "sneaky", "tools": {"allow": ["Edit"], "deny": []}}
        ).tools
        self.assertNotIn("Edit", allowed.allow)
        self.assertIn("Edit", allowed.deny)
        narrowed = self.factory.create(
            "code-reviewer", {"id": "strict", "permissions": {"max_risk": "low"}}
        )
        self.assertIs(narrowed.permissions.ceiling, True)

    def test_an_engineer_may_be_specialized_freely(self) -> None:
        got = self.factory.create(
            "senior-engineer", {"id": "release-engineer", "permissions": {"max_risk": "high"}}
        )
        self.assertEqual(got.permissions.max_risk.value, "high")

    def test_escalation_targets_exist(self) -> None:
        for spec in self.resolved.values():
            if spec.escalation and spec.escalation.to:
                self.assertIn(spec.escalation.to, self.registry_ids())

    def test_committed_subagent_files_match_exporter_output(self) -> None:
        agents_dir = ROOT / "agents"
        self.assertEqual({p.stem for p in agents_dir.glob("*.md")}, EXPECTED_EXAMPLES)
        for agent_id in EXPECTED_EXAMPLES:
            with self.subTest(agent_id=agent_id):
                committed = (agents_dir / f"{agent_id}.md").read_bytes()
                source = f"agent-specs/examples/{agent_id}.json"
                expected = render_subagent(self.resolved[agent_id], "en", source).encode("utf-8")
                self.assertEqual(committed, expected)


if __name__ == "__main__":
    unittest.main()
