"""The safety rules of per-task tool selection: what no provider's answer can change."""

from __future__ import annotations

import unittest
from typing import Any

from tests.unit._agent_helpers import make
from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.core.contracts import PlanTask, ToolSelection
from wev_skills.decisions import tool_selection as ts
from wev_skills.decisions.tool_selection import Proposal
from wev_skills.tools.registry import DEFAULT_DEFINITION_TOKENS, ToolRegistry, ToolSpec

TOOLS = ToolRegistry.default().list()
DOER = {"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": True}
READER = {"modes": ["plan", "execute"], "max_risk": "low", "may_mutate": False}
FULL = ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebFetch", "WebSearch"]


def agent(allow: list[str], deny: list[str] | None = None, **permissions: Any) -> AgentSpec:
    tools = {"allow": allow, "deny": deny or []}
    return make("worker", tools=tools, permissions={**DOER, **permissions})


def task(**fields: Any) -> PlanTask:
    return PlanTask.from_dict({"id": "t", "title": "Tidy", "objective": "Tidy up", **fields})


def proposal(*selected: str, profile: str = "structured", source: str = "fake") -> Proposal:
    return Proposal(tuple(selected), profile, ("because",), source)


def tokens(*names: str) -> int:
    return sum(ToolRegistry.default().get(name).approx_definition_tokens for name in names)


class EnglishCase(unittest.TestCase):
    def setUp(self) -> None:
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)


class CandidateTests(EnglishCase):
    def test_candidates_are_the_allow_list_minus_the_deny_list(self) -> None:
        worker = agent(FULL, deny=["Write", "WebSearch"])
        self.assertEqual(
            ts.candidate_tools(worker), ("Read", "Grep", "Glob", "Edit", "Bash", "WebFetch")
        )

    def test_a_scoped_pattern_is_treated_by_its_base_tool_name(self) -> None:
        self.assertEqual(ts.base_name("Bash(git:*)"), "Bash")
        worker = agent(["Read", "Bash(git:*)", "Bash(make:*)", "Edit(docs/**)"], deny=["Edit"])
        self.assertEqual(ts.candidate_tools(worker), ("Read", "Bash(git:*)", "Bash(make:*)"))

    def test_a_scoped_deny_removes_only_that_entry(self) -> None:
        worker = agent(["Read", "Bash(git:*)", "Bash(rm:*)"], deny=["Bash(rm:*)"])
        self.assertEqual(ts.candidate_tools(worker), ("Read", "Bash(git:*)"))

    def test_an_agent_without_tools_has_no_candidates(self) -> None:
        bare = make("bare", permissions=DOER)
        self.assertEqual(ts.candidate_tools(bare), ())
        chosen = ts.enforce(task(), bare, TOOLS, proposal("Read"))
        self.assertEqual((chosen.offered, chosen.selected, chosen.dropped), ((), (), ()))


class SubsetTests(EnglishCase):
    def test_the_result_is_always_a_subset_of_the_candidates(self) -> None:
        worker = agent(["Read", "Grep", "Edit"])
        chosen = ts.enforce(task(), worker, TOOLS, proposal("Read", "Bash", "RemoteExec", "Edit"))
        self.assertEqual(chosen.offered, ("Read", "Grep", "Edit"))
        self.assertTrue(set(chosen.selected) <= set(chosen.offered))
        self.assertNotIn("Bash", chosen.selected)
        self.assertNotIn("RemoteExec", chosen.selected)
        self.assertTrue(any("Bash" in r and "only narrow" in r for r in chosen.reasons))

    def test_a_denied_tool_is_never_added(self) -> None:
        worker = agent(FULL, deny=["Bash", "Write"])
        chosen = ts.enforce(task(), worker, TOOLS, proposal(*FULL))
        self.assertNotIn("Bash", chosen.selected)
        self.assertNotIn("Write", chosen.selected)
        self.assertNotIn("Bash", chosen.offered)

    def test_offered_selected_and_dropped_partition_the_candidates(self) -> None:
        worker = agent(FULL)
        chosen = ts.enforce(task(read_only=True), worker, TOOLS, proposal("Read"))
        self.assertEqual(chosen.offered, tuple(FULL))
        self.assertEqual(chosen.selected, ("Read", "Grep", "Glob"))
        self.assertEqual(chosen.dropped, ("Edit", "Write", "Bash", "WebFetch", "WebSearch"))
        self.assertEqual(sorted(chosen.selected + chosen.dropped), sorted(chosen.offered))

    def test_scoped_entries_of_one_base_are_kept_or_dropped_together(self) -> None:
        worker = agent(["Read", "Bash(git:*)", "Bash(make:*)", "WebFetch"])
        kept = ts.enforce(task(), worker, TOOLS, proposal("Read", "Bash"))
        self.assertEqual(kept.selected, ("Read", "Bash(git:*)", "Bash(make:*)"))
        dropped = ts.enforce(task(), worker, TOOLS, proposal("Read"))
        self.assertEqual(dropped.dropped, ("Bash(git:*)", "Bash(make:*)", "WebFetch"))


class PermissionTests(EnglishCase):
    def test_selection_carries_no_permission_and_changes_none(self) -> None:
        worker = agent(FULL, may_use_remote=True)
        before = worker.to_dict()
        chosen = ts.enforce(task(), worker, TOOLS, proposal("Read"))
        self.assertEqual(worker.to_dict(), before)
        fields = set(chosen.to_dict())
        self.assertFalse(fields & {"may_mutate", "modes", "max_risk", "may_use_remote"})

    def test_a_read_only_agent_never_gets_an_edit_tool_it_was_not_offered(self) -> None:
        reader = make("reader", tools={"allow": ["Read", "Grep"]}, permissions=READER)
        chosen = ts.enforce(task(), reader, TOOLS, proposal("Read", "Edit", "Write"))
        self.assertEqual(chosen.selected, ("Read", "Grep"))


class FloorTests(EnglishCase):
    def test_the_read_tools_the_agent_had_are_always_kept(self) -> None:
        worker = agent(["Read", "Glob", "Edit", "WebFetch"])
        chosen = ts.enforce(task(read_only=True), worker, TOOLS, proposal("WebFetch"))
        self.assertEqual(chosen.selected, ("Read", "Glob", "WebFetch"))
        self.assertTrue(any("Read" in r and "floor" in r for r in chosen.reasons))

    def test_the_edit_tool_is_kept_when_the_task_changes_files(self) -> None:
        worker = agent(FULL)
        chosen = ts.enforce(task(), worker, TOOLS, proposal("Read"))
        self.assertIn("Edit", chosen.selected)
        self.assertNotIn("Write", chosen.selected)

    def test_write_is_the_edit_tool_of_an_agent_without_edit(self) -> None:
        worker = agent(["Read", "Write", "WebFetch"])
        self.assertIn("Write", ts.enforce(task(), worker, TOOLS, proposal("Read")).selected)

    def test_no_edit_tool_in_the_floor_for_a_read_only_task_or_agent(self) -> None:
        worker = agent(FULL)
        self.assertNotIn(
            "Edit", ts.enforce(task(read_only=True), worker, TOOLS, proposal("Read")).selected
        )
        reader = agent(FULL, may_mutate=False)
        self.assertNotIn("Edit", ts.enforce(task(), reader, TOOLS, proposal("Read")).selected)

    def test_the_shell_is_kept_when_the_task_has_checks(self) -> None:
        worker = agent(FULL)
        with_checks = ts.enforce(task(checks=["make test"]), worker, TOOLS, proposal("Read"))
        self.assertIn("Bash", with_checks.selected)
        self.assertNotIn("Bash", ts.enforce(task(), worker, TOOLS, proposal("Read")).selected)

    def test_an_agent_without_read_tools_keeps_its_whole_list(self) -> None:
        fetcher = make("fetcher", tools={"allow": ["WebFetch", "WebSearch"]}, permissions=READER)
        chosen = ts.enforce(task(), fetcher, TOOLS, proposal("WebFetch"))
        self.assertEqual(chosen.selected, ("WebFetch", "WebSearch"))
        self.assertEqual(chosen.dropped, ())

    def test_floor_names_are_base_names(self) -> None:
        worker = agent(["Read", "Bash(make:*)", "WebFetch"])
        self.assertEqual(
            ts.floor_tools(task(checks=["make test"]), worker, ts.candidate_tools(worker)),
            ("Read", "Bash"),
        )


class InvalidResultTests(EnglishCase):
    def local(self) -> Proposal:
        return Proposal(("Read", "Edit", "WebFetch"), "structured", ("local",), "local-policy")

    def test_an_empty_result_falls_back_to_the_local_policy(self) -> None:
        chosen = ts.enforce(task(), agent(FULL), TOOLS, proposal(), self.local)
        self.assertEqual(chosen.source, "local-policy")
        self.assertEqual(chosen.selected, ("Read", "Grep", "Glob", "Edit", "WebFetch"))
        self.assertIn("was not usable", chosen.reasons[0])
        self.assertIn("empty", chosen.reasons[0])

    def test_a_result_naming_only_unknown_tools_is_empty(self) -> None:
        chosen = ts.enforce(task(), agent(FULL), TOOLS, proposal("Nope", "Deploy"), self.local)
        self.assertEqual(chosen.source, "local-policy")

    def test_an_unknown_profile_is_invalid(self) -> None:
        bad = proposal("Read", profile="turbo")
        chosen = ts.enforce(task(), agent(FULL), TOOLS, bad, self.local)
        self.assertEqual((chosen.source, chosen.profile), ("local-policy", "structured"))
        self.assertIn("profile", chosen.reasons[0])

    def test_names_that_are_not_text_are_invalid(self) -> None:
        bad = Proposal(("Read", 7), "structured", (), "fake")  # type: ignore[arg-type]
        chosen = ts.enforce(task(), agent(FULL), TOOLS, bad, self.local)
        self.assertEqual(chosen.source, "local-policy")

    def test_without_a_fallback_an_invalid_result_keeps_every_candidate(self) -> None:
        chosen = ts.enforce(task(), agent(FULL), TOOLS, proposal())
        self.assertEqual((chosen.selected, chosen.dropped), (tuple(FULL), ()))
        self.assertIn("whole tool list was kept", chosen.reasons[0])


class ProfileTests(EnglishCase):
    def test_lean_narrows_to_the_shell_and_minimal_read_and_edit_tools(self) -> None:
        chosen = ts.enforce(
            task(checks=["make test"]), agent(FULL), TOOLS, proposal(*FULL, profile="lean")
        )
        self.assertEqual((chosen.profile, chosen.selected), ("lean", ("Read", "Edit", "Bash")))
        self.assertEqual(chosen.offered, tuple(FULL))
        self.assertTrue(any("lean" in r and "Grep" in r for r in chosen.reasons))

    def test_lean_does_not_apply_to_an_agent_that_may_not_change_files(self) -> None:
        reader = agent(["Read", "Grep", "Bash"], may_mutate=False)
        chosen = ts.enforce(task(), reader, TOOLS, proposal("Read", "Bash", profile="lean"))
        self.assertEqual(chosen.selected, ("Read", "Grep", "Bash"))


class EstimateTests(EnglishCase):
    def test_token_figures_sum_the_registry_estimates(self) -> None:
        chosen = ts.enforce(task(read_only=True), agent(FULL), TOOLS, proposal("Read"))
        self.assertEqual(chosen.estimated_tokens_offered, tokens(*FULL))
        self.assertEqual(chosen.estimated_tokens_selected, tokens("Read", "Grep", "Glob"))

    def test_scoped_entries_count_once_and_unknown_tools_use_the_default(self) -> None:
        worker = agent(["Read", "Bash(git:*)", "Bash(make:*)", "mcp__db__query"])
        chosen = ts.enforce(task(), worker, TOOLS, proposal("Read", "Bash", "mcp__db__query"))
        expected = tokens("Read", "Bash") + DEFAULT_DEFINITION_TOKENS
        self.assertEqual(chosen.estimated_tokens_selected, expected)

    def test_a_registered_custom_tool_brings_its_own_estimate(self) -> None:
        extra = ToolSpec("Lookup", approx_definition_tokens=40)
        worker = agent(["Read", "Lookup"])
        chosen = ts.enforce(task(), worker, (*TOOLS, extra), proposal("Read", "Lookup"))
        self.assertEqual(chosen.estimated_tokens_selected, tokens("Read") + 40)

    def test_the_selection_round_trips_through_json(self) -> None:
        chosen = ts.enforce(task(), agent(FULL), TOOLS, proposal("Read"))
        self.assertEqual(ToolSelection.from_dict(chosen.to_dict()), chosen)

    def test_a_negative_estimate_is_refused(self) -> None:
        from wev_skills.core.errors import ValidationError

        with self.assertRaises(ValidationError):
            ToolSpec("Odd", approx_definition_tokens=-1)


if __name__ == "__main__":
    unittest.main()
