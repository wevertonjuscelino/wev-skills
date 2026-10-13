"""The deterministic local tool-selection policy: the floor plus what the task asks for."""

from __future__ import annotations

import unittest
from typing import Any

from tests.unit._agent_helpers import make
from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import HarnessSettings, LimitsConfig
from wev_skills.core.contracts import PlanTask, ToolSelection
from wev_skills.decisions.local import PROVIDER_ID, LocalPolicyProvider
from wev_skills.tools.registry import ToolRegistry

TOOLS = ToolRegistry.default().list()
FULL = ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebFetch", "WebSearch", "RemoteExec"]
DOER = {"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": True}


def agent(allow: list[str] | None = None, **permissions: Any) -> AgentSpec:
    tools = {"allow": allow if allow is not None else FULL}
    return make("worker", tools=tools, permissions={**DOER, **permissions})


def task(objective: str = "Tidy the parser", **fields: Any) -> PlanTask:
    return PlanTask.from_dict({"id": "t", "title": "Task", "objective": objective, **fields})


def select(
    objective: str = "Tidy the parser",
    worker: AgentSpec | None = None,
    profile: str = "structured",
    tier: str = "standard",
    lang: str = "en",
    **fields: Any,
) -> ToolSelection:
    provider = LocalPolicyProvider(LimitsConfig(), HarnessSettings(tool_profile=profile))
    with i18n.use_language(lang):
        return provider.select_tools(task(objective, **fields), worker or agent(), TOOLS, tier)


def reason_for(selection: ToolSelection, tool: str) -> str:
    return next(reason for reason in selection.reasons if reason.startswith(tool))


class FloorOnlyTests(unittest.TestCase):
    def test_a_task_that_gives_no_reason_gets_only_the_floor(self) -> None:
        chosen = select()
        self.assertEqual(chosen.selected, ("Read", "Grep", "Glob", "Edit"))
        self.assertEqual(chosen.dropped, ("Write", "Bash", "WebFetch", "WebSearch", "RemoteExec"))
        self.assertEqual((chosen.source, chosen.profile), (PROVIDER_ID, "structured"))

    def test_every_kept_and_dropped_tool_has_a_reason(self) -> None:
        chosen = select()
        for tool in chosen.offered:
            with self.subTest(tool=tool):
                self.assertTrue(reason_for(chosen, tool))
        self.assertIn("nothing in the task asks for it", reason_for(chosen, "Write"))
        self.assertIn("floor", reason_for(chosen, "Read"))

    def test_checks_keep_the_shell(self) -> None:
        chosen = select(checks=["make test"])
        self.assertIn("Bash", chosen.selected)
        self.assertIn("checks", reason_for(chosen, "Bash"))

    def test_a_read_only_task_gets_no_edit_tool(self) -> None:
        self.assertEqual(select("Review the parser", read_only=True).selected, READ)

    def test_it_is_deterministic_and_changes_no_argument(self) -> None:
        worker, plan_task = agent(), task("Add a new file with docs")
        before = (worker.to_dict(), plan_task.to_dict())
        provider = LocalPolicyProvider(LimitsConfig())
        first = provider.select_tools(plan_task, worker, TOOLS, "standard")
        second = provider.select_tools(plan_task, worker, TOOLS, "standard")
        self.assertEqual(first, second)
        self.assertEqual((worker.to_dict(), plan_task.to_dict()), before)


READ = ("Read", "Grep", "Glob")


class NetworkTests(unittest.TestCase):
    def test_english_terms_add_the_network_tools_with_the_matched_term(self) -> None:
        cases = {
            "Read the documentation of the client": "documentation",
            "Research how others paginate": "research",
            "Follow https://example.org/guide": "https",
            "Call the billing API": "api",
            "Apply the upgrade notes of the driver": "upgrade notes",
        }
        for objective, term in cases.items():
            with self.subTest(objective=objective):
                chosen = select(objective)
                self.assertIn("WebFetch", chosen.selected)
                self.assertIn("WebSearch", chosen.selected)
                self.assertIn(f"'{term}'", reason_for(chosen, "WebFetch"))

    def test_portuguese_terms_add_them_too_with_portuguese_reasons(self) -> None:
        cases = {
            "Consulte a documentação do cliente": "documentação",
            "Fazer uma pesquisa sobre paginação": "pesquisa",
            "Aplicar as notas de atualização do driver": "notas de atualização",
        }
        for objective, term in cases.items():
            with self.subTest(objective=objective):
                chosen = select(objective, lang="pt-BR")
                self.assertIn("WebFetch", chosen.selected)
                reason = reason_for(chosen, "WebFetch")
                self.assertIn(f"'{term}'", reason)
                self.assertIn("adicionada", reason)

    def test_terms_match_whole_words_only(self) -> None:
        for objective in ("Fix the rapid cache", "Tidy the capital module", "Undocumented x"):
            with self.subTest(objective=objective):
                self.assertNotIn("WebFetch", select(objective).selected)

    def test_criteria_and_title_are_read_as_well(self) -> None:
        chosen = select(acceptance_criteria=["Matches the API reference"])
        self.assertIn("WebFetch", chosen.selected)


class CreateTests(unittest.TestCase):
    def test_creating_files_adds_write_next_to_edit(self) -> None:
        for objective, term in (
            ("Create the export module", "create"),
            ("Add a retry helper", "add"),
            ("Put the helper in a new file", "new file"),
            ("Scaffold the plugin", "scaffold"),
        ):
            with self.subTest(objective=objective):
                chosen = select(objective)
                self.assertIn("Edit", chosen.selected)
                self.assertIn("Write", chosen.selected)
                self.assertIn(f"'{term}'", reason_for(chosen, "Write"))

    def test_portuguese_create_terms(self) -> None:
        for objective, term in (("Criar o módulo", "criar"), ("Adicionar um teste", "adicionar")):
            with self.subTest(objective=objective):
                chosen = select(objective, lang="pt-BR")
                self.assertIn("Write", chosen.selected)
                self.assertIn(f"'{term}'", reason_for(chosen, "Write"))
                self.assertIn("cria arquivos", reason_for(chosen, "Write"))

    def test_a_read_only_task_or_agent_does_not_get_write(self) -> None:
        self.assertNotIn("Write", select("Create a list of findings", read_only=True).selected)
        reader = agent(may_mutate=False)
        self.assertNotIn("Write", select("Create the module", reader).selected)


class RemoteTests(unittest.TestCase):
    def test_remote_systems_add_the_remote_tool_for_an_agent_that_may_use_them(self) -> None:
        chosen = select("Check the disk of the staging server", agent(may_use_remote=True))
        self.assertIn("RemoteExec", chosen.selected)
        self.assertIn("'server'", reason_for(chosen, "RemoteExec"))
        self.assertIn("Bash", chosen.selected)

    def test_an_agent_that_may_not_use_remote_does_not_get_it(self) -> None:
        self.assertNotIn("RemoteExec", select("Check the disk of the staging server").selected)

    def test_portuguese_remote_term(self) -> None:
        chosen = select("Ver o disco do servidor", agent(may_use_remote=True), lang="pt-BR")
        self.assertIn("RemoteExec", chosen.selected)
        self.assertIn("sistema remoto", reason_for(chosen, "RemoteExec"))


class NamedAndShellTests(unittest.TestCase):
    def test_a_specialized_tool_is_added_only_when_named(self) -> None:
        worker = agent(["Read", "Edit", "NotebookEdit", "mcp__db__query"])
        self.assertEqual(select("Tidy the parser", worker).selected, ("Read", "Edit"))
        named = select("Fix the plot cell with NotebookEdit", worker)
        self.assertIn("NotebookEdit", named.selected)
        self.assertNotIn("mcp__db__query", named.selected)
        self.assertIn("names it", reason_for(named, "NotebookEdit"))

    def test_a_notebook_task_gets_the_notebook_tool(self) -> None:
        worker = agent(["Read", "Edit", "NotebookEdit"])
        for objective in ("Clean the analysis notebook", "Fix report.ipynb"):
            with self.subTest(objective=objective):
                self.assertIn("NotebookEdit", select(objective, worker).selected)

    def test_running_a_command_adds_the_shell(self) -> None:
        chosen = select("Run the migration script")
        self.assertIn("Bash", chosen.selected)
        self.assertIn("'run'", reason_for(chosen, "Bash"))
        self.assertIn("Bash", select("Executar o script de carga", lang="pt-BR").selected)


class ProfileTests(unittest.TestCase):
    def test_the_profile_comes_from_the_harness_setting(self) -> None:
        self.assertEqual(select(profile="structured", tier="premium").profile, "structured")
        self.assertEqual(select(profile="lean", tier="economy").profile, "lean")

    def test_auto_resolves_by_tier(self) -> None:
        self.assertEqual(select(profile="auto", tier="premium").profile, "lean")
        self.assertEqual(select(profile="auto", tier="standard").profile, "structured")
        self.assertEqual(select(profile="auto", tier="unknown-tier").profile, "structured")

    def test_lean_wins_over_additions(self) -> None:
        chosen = select("Add docs from the API", profile="lean", checks=["make test"])
        self.assertEqual(chosen.selected, ("Read", "Edit", "Bash"))


if __name__ == "__main__":
    unittest.main()
