"""Tool profiles: ``structured`` keeps the allow list, ``lean`` reduces it for agents that edit."""

from __future__ import annotations

import unittest

from tests.unit._agent_helpers import factory_for, make
from wev_skills.agents.spec import AgentSpec, Tools
from wev_skills.agents.tool_profile import LEAN, STRUCTURED, apply_profile, resolve_profile, tier_of
from wev_skills.config import ModelsConfig
from wev_skills.core.errors import ValidationError

DOER = {"modes": ["plan", "execute"], "max_risk": "medium", "may_mutate": True}
FULL = ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebFetch"]


def resolved(**fields: object) -> AgentSpec:
    spec = make("a", **fields)
    return factory_for(spec).resolve(spec)


class ResolveProfileTests(unittest.TestCase):
    def test_auto_is_structured_below_premium_and_lean_for_premium(self) -> None:
        self.assertEqual(resolve_profile("auto", "economy"), STRUCTURED)
        self.assertEqual(resolve_profile("auto", "standard"), STRUCTURED)
        self.assertEqual(resolve_profile("auto", "premium"), LEAN)
        self.assertEqual(resolve_profile("auto", "pinned"), STRUCTURED)

    def test_an_explicit_profile_ignores_the_tier(self) -> None:
        for tier in ("economy", "standard", "premium"):
            self.assertEqual(resolve_profile("structured", tier), STRUCTURED)
            self.assertEqual(resolve_profile("lean", tier), LEAN)

    def test_an_unknown_profile_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            resolve_profile("bash-only", "premium")

    def test_tier_of_a_tier_name_a_configured_model_and_an_unknown_model(self) -> None:
        models = ModelsConfig()
        self.assertEqual(tier_of("premium", models), "premium")
        self.assertEqual(tier_of("claude-haiku-5-5", models), "economy")
        self.assertEqual(tier_of("claude-sonnet-5-5", models), "standard")
        self.assertEqual(tier_of("vendor/model-x", models), "standard")
        self.assertEqual(tier_of(None, models), "standard")
        self.assertEqual(tier_of("", models), "standard")


class ApplyProfileTests(unittest.TestCase):
    def test_structured_keeps_the_full_allow_list(self) -> None:
        spec = resolved(permissions=DOER, tools={"allow": FULL, "deny": ["NotebookEdit"]})
        self.assertEqual(apply_profile(spec.tools, spec.permissions, STRUCTURED), spec.tools)

    def test_lean_keeps_the_shell_and_the_minimal_read_and_edit_tools(self) -> None:
        spec = resolved(permissions=DOER, tools={"allow": FULL, "deny": ["NotebookEdit"]})
        lean = apply_profile(spec.tools, spec.permissions, LEAN)
        self.assertEqual(lean, Tools(allow=("Read", "Edit", "Bash"), deny=("NotebookEdit",)))

    def test_lean_never_adds_a_tool_the_agent_did_not_have(self) -> None:
        spec = resolved(permissions=DOER, tools={"allow": ["Grep", "Write", "Bash(git status:*)"]})
        lean = apply_profile(spec.tools, spec.permissions, LEAN)
        self.assertEqual(lean.allow, ("Bash(git status:*)",))
        self.assertLessEqual(set(lean.allow), set(spec.tools.allow))

    def test_lean_counts_scoped_patterns_as_their_base_tool(self) -> None:
        spec = resolved(
            tools={"allow": ["Read", "Grep", "Edit(src/**)", "Bash(git status:*)"]},
            permissions=DOER,
        )
        got = apply_profile(spec.tools, spec.permissions, LEAN)
        assert got is not None
        self.assertEqual(got.allow, ("Read", "Edit(src/**)", "Bash(git status:*)"))

    def test_lean_never_removes_a_deny_entry(self) -> None:
        deny = ["WebFetch", "NotebookEdit", "Write"]
        spec = resolved(permissions=DOER, tools={"allow": ["Read", "Edit", "Bash"], "deny": deny})
        self.assertEqual(apply_profile(spec.tools, spec.permissions, LEAN).deny, tuple(deny))

    def test_lean_leaves_read_only_agents_alone(self) -> None:
        spec = resolved(tools={"allow": ["Read", "Grep", "Glob", "Bash"]})
        self.assertEqual(apply_profile(spec.tools, spec.permissions, LEAN), spec.tools)

    def test_lean_leaves_an_agent_without_a_shell_alone(self) -> None:
        spec = resolved(permissions=DOER, tools={"allow": ["Read", "Grep", "Edit", "Write"]})
        self.assertEqual(apply_profile(spec.tools, spec.permissions, LEAN), spec.tools)

    def test_inputs_are_not_changed_and_missing_tools_stay_missing(self) -> None:
        spec = resolved(permissions=DOER, tools={"allow": FULL})
        before = spec.tools
        apply_profile(spec.tools, spec.permissions, LEAN)
        self.assertEqual(spec.tools, before)
        self.assertIsNone(apply_profile(None, spec.permissions, LEAN))


if __name__ == "__main__":
    unittest.main()
