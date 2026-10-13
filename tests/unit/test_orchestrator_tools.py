"""Tool selection wired into the contract, the run state, the report and the recovery path."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

from tests.unit._agent_helpers import make
from tests.unit._orchestrator_helpers import DOER, READER, OrchestratorCase
from wev_skills import schema
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.agents.tool_profile import resolve_profile, tier_of
from wev_skills.config import load_config
from wev_skills.core import planning, report_markdown, wiring
from wev_skills.core.contracts import TaskContract
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.core.tool_select import SOURCE
from wev_skills.decisions.jev import JevProvider
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.security.redact import redact
from wev_skills.state.model import RunState, TaskRecord

FAKE = str(Path(__file__).resolve().parents[1] / "fixtures" / "fake_jev.py")
FULL = ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebFetch", "WebSearch"]
FLOOR = ("Read", "Grep", "Glob", "Edit", "Bash")
TASK = {"id": "a", "title": "Tidy", "objective": "Tidy the parser", "agent_hint": "builder"}


def catalog() -> wiring.AgentCatalog:
    specs = [
        make(
            "builder",
            specialties=["implementation"],
            model="standard",
            permissions=DOER,
            tools={"allow": FULL, "deny": ["NotebookEdit"]},
        ),
        make("reviewer", specialties=["review"], permissions=READER, tools={"allow": ["Read"]}),
    ]
    registry = AgentRegistry(specs)
    return wiring.AgentCatalog(registry, AgentFactory(registry), frozenset())


class ToolsCase(OrchestratorCase):
    selection = "local"
    use_fake_jev = False

    def services(self) -> wiring.Services:
        self.overrides = {**self.overrides, "harness": {"tool_selection": self.selection}}
        built = replace(super().services(), agents=catalog())
        if not self.use_fake_jev:
            return built
        local = LocalPolicyProvider(built.config.limits, built.config.harness)
        command = (sys.executable, FAKE)
        jev = JevProvider(SubprocessRunner(), local, command, 20.0, redactor=redact)
        return replace(built, provider=jev)

    def begin(self, **task: Any) -> None:
        self.start("Tidy the parser")
        self.set_plan({**TASK, **task})

    def contract(self) -> TaskContract:
        return TaskContract.from_dict(self.orch().next_tasks()["tasks"][0])

    def record(self) -> TaskRecord:
        found: TaskRecord = self.state().tasks["a"]
        return found

    def selection_decisions(self) -> list[Any]:
        return [d for d in self.state().decisions if d.source == SOURCE]


class OffTests(ToolsCase):
    selection = "off"

    def test_off_leaves_the_contract_exactly_as_before(self) -> None:
        self.begin()
        contract = self.contract()
        state, orch = self.state(), self.orch()
        spec = orch.services.agents.resolved("builder")
        config = orch.services.config
        profile = resolve_profile(
            config.harness.tool_profile, tier_of(state.tasks["a"].model, config.models)
        )
        before = planning.build_contract(
            state, state.plan.tasks[0], spec, config.permissions.protected_paths, profile
        )
        self.assertEqual(contract, before)
        self.assertEqual(contract.permissions, tuple(FULL))
        self.assertNotIn("Tools for this task", contract.context)

    def test_off_stores_nothing_and_records_no_decision(self) -> None:
        self.begin()
        self.orch().next_tasks()
        self.orch().start_task("a")
        self.assertIsNone(self.record().tool_selection)
        self.assertEqual(self.selection_decisions(), [])
        self.assertIsNone(self.orch().report()["tasks"][0]["tool_selection"])

    def test_off_is_the_default(self) -> None:
        self.assertEqual(load_config().harness.tool_selection, "off")

    def test_restoring_a_tool_is_refused_when_nothing_was_selected(self) -> None:
        self.begin()
        self.orch().next_tasks()
        self.orch().start_task("a")
        with self.assertRaises(ValidationError) as caught:
            self.orch().restore_tool("a", "Write", "needed")
        self.assertEqual(caught.exception.code, "no_tool_selection")


class ContractTests(ToolsCase):
    def test_the_contract_grants_only_the_selected_tools(self) -> None:
        self.begin()
        contract = self.contract()
        self.assertEqual(contract.permissions, FLOOR)
        self.assertIn("Tools for this task: Read, Grep, Glob, Edit, Bash.", contract.context)
        self.assertIn("Write, WebFetch, WebSearch", contract.context)
        self.assertIn("wev task tools a --add", contract.context)

    def test_permissions_are_the_same_with_and_without_selection(self) -> None:
        self.begin()
        narrowed = self.contract()
        fields = ("may_mutate", "may_use_remote", "risk", "read_only", "max_attempts", "checks")
        self.selection = "off"
        full = TaskContract.from_dict(self.orch().start_task("a")["contract"])
        for name in fields:
            with self.subTest(field=name):
                self.assertEqual(getattr(narrowed, name), getattr(full, name))

    def test_the_selection_is_stored_with_the_task_and_recorded_as_a_decision(self) -> None:
        self.begin()
        self.orch().next_tasks()
        chosen = self.record().tool_selection
        assert chosen is not None
        self.assertEqual((chosen.selected, chosen.source), (FLOOR, "local-policy"))
        self.assertEqual(chosen.dropped, ("Write", "WebFetch", "WebSearch"))
        self.assertGreater(chosen.estimated_tokens_offered, chosen.estimated_tokens_selected)
        decisions = self.selection_decisions()
        self.assertEqual(len(decisions), 1)
        self.assertIn("task a", decisions[0].decision)
        self.assertTrue(any(r.startswith("Write dropped") for r in decisions[0].reasons))

    def test_the_selection_is_computed_once_per_task(self) -> None:
        self.begin()
        self.orch().next_tasks()
        self.orch().next_tasks()
        started = self.orch().start_task("a")
        self.assertEqual(tuple(started["contract"]["permissions"]), FLOOR)
        self.assertEqual(len(self.selection_decisions()), 1)

    def test_starting_without_asking_for_the_next_tasks_still_selects(self) -> None:
        self.begin()
        started = self.orch().start_task("a")
        self.assertEqual(tuple(started["contract"]["permissions"]), FLOOR)
        self.assertEqual(len(self.selection_decisions()), 1)

    def test_the_task_reasons_shape_the_selection(self) -> None:
        self.begin(objective="Create a client from the API documentation")
        self.assertEqual(self.contract().permissions, tuple(FULL))

    def test_the_stored_state_validates_and_older_states_still_load(self) -> None:
        self.begin()
        self.orch().next_tasks()
        data = self.state().to_dict()
        self.assertEqual(schema.validate(data, schema.load("state")), [])
        older = json.loads(json.dumps(data))
        for record in older["tasks"].values():
            del record["tool_selection"], record["tool_misses"]
        loaded = RunState.from_dict(older)
        self.assertIsNone(loaded.tasks["a"].tool_selection)
        self.assertEqual(schema.validate(older, schema.load("state")), [])


class RecoveryTests(ToolsCase):
    def running(self) -> None:
        self.begin()
        self.orch().next_tasks()
        self.orch().start_task("a")

    def test_a_dropped_tool_is_restored_and_counted_as_a_miss(self) -> None:
        self.running()
        out = self.orch().restore_tool("a", "Write", "the helper goes in a new file")
        self.assertEqual(tuple(out["contract"]["permissions"]), (*FLOOR[:4], "Write", "Bash"))
        self.assertEqual(out["misses"], 1)
        record = self.record()
        assert record.tool_selection is not None
        self.assertNotIn("Write", record.tool_selection.dropped)
        self.assertEqual(
            [(m.tool, m.reason, m.attempt) for m in record.tool_misses],
            [("Write", "the helper goes in a new file", 1)],
        )
        self.assertEqual(len(self.selection_decisions()), 2)
        self.assertIn("task.tool_restored", self.audit_types())
        offered = record.tool_selection.estimated_tokens_offered
        self.assertLess(record.tool_selection.estimated_tokens_selected, offered)

    def test_a_tool_outside_the_agents_candidates_is_refused(self) -> None:
        self.running()
        for tool in ("RemoteExec", "NotebookEdit", "Deploy"):
            with self.subTest(tool=tool), self.assertRaises(PermissionDenied) as caught:
                self.orch().restore_tool("a", tool, "wanted")
            self.assertEqual(caught.exception.code, "tool_not_offered")
        self.assertEqual(self.record().tool_misses, ())

    def test_a_tool_already_selected_or_an_empty_reason_is_refused(self) -> None:
        self.running()
        with self.assertRaises(ValidationError) as caught:
            self.orch().restore_tool("a", "Read", "again")
        self.assertEqual(caught.exception.code, "tool_already_selected")
        with self.assertRaises(ValidationError) as caught:
            self.orch().restore_tool("a", "Write", "   ")
        self.assertEqual(caught.exception.code, "reason_required")

    def test_only_a_running_task_can_have_a_tool_restored(self) -> None:
        self.begin()
        self.orch().next_tasks()
        with self.assertRaises(ValidationError) as caught:
            self.orch().restore_tool("a", "Write", "needed")
        self.assertEqual(caught.exception.code, "task_not_running")

    def test_the_report_shows_the_selection_and_its_misses_in_both_languages(self) -> None:
        self.running()
        self.orch().restore_tool("a", "WebFetch", "the changelog is online")
        built = self.orch().report("en")
        section = built["tasks"][0]["tool_selection"]
        self.assertEqual(section["offered"], FULL)
        self.assertEqual(section["dropped"], ["Write", "WebSearch"])
        self.assertEqual((section["source"], section["miss_count"]), ("local-policy", 1))
        self.assertEqual(section["misses"][0]["tool"], "WebFetch")
        estimate = section["estimated_definition_tokens"]
        self.assertEqual(estimate["label"], "estimated definition tokens (approximate)")
        self.assertGreater(estimate["offered"], estimate["selected"])
        english = report_markdown.render_markdown(built, "en")
        self.assertIn("Estimated definition tokens (approximate)", english)
        self.assertIn("Tool-selection misses:** 1", english)
        self.assertIn("WebFetch", english)
        portuguese = report_markdown.render_markdown(self.orch().report("pt-BR"), "pt-BR")
        self.assertIn("Tokens de definição estimados (aproximados)", portuguese)
        self.assertIn("Falhas da seleção de ferramentas:** 1", portuguese)
        for text in (english, portuguese):
            self.assertNotIn("saving", text.lower())
            self.assertNotIn("economia", text.lower())


class ProviderTests(ToolsCase):
    selection = "provider"

    def test_provider_mode_with_the_local_provider_uses_the_local_policy(self) -> None:
        self.begin()
        self.orch().next_tasks()
        chosen = self.record().tool_selection
        assert chosen is not None
        self.assertEqual((chosen.source, chosen.selected), ("local-policy", FLOOR))

    def test_provider_mode_asks_jev_when_it_is_the_configured_provider(self) -> None:
        self.use_fake_jev = True
        answers = {"FAKE_JEV_TOOL_ANSWERS": json.dumps({"WebSearch": 0.0, "Write": 0.1})}
        with mock.patch.dict(os.environ, answers):
            self.begin()
            contract = self.contract()
        self.assertEqual(contract.permissions, (*FLOOR, "WebFetch"))
        chosen = self.record().tool_selection
        assert chosen is not None
        self.assertEqual(chosen.source, "jev")

    def test_a_failing_jev_falls_back_and_the_task_still_gets_its_contract(self) -> None:
        self.use_fake_jev = True
        with mock.patch.dict(os.environ, {"FAKE_JEV_MODE": "error"}):
            self.begin()
            contract = self.contract()
        self.assertEqual(contract.permissions, FLOOR)
        chosen = self.record().tool_selection
        assert chosen is not None
        self.assertEqual(chosen.source, "local-policy")
        self.assertIn("JEV was unavailable", chosen.reasons[0])


class LocalModeIgnoresTheProviderTests(ToolsCase):
    selection = "local"

    def test_local_mode_never_calls_the_configured_provider(self) -> None:
        self.use_fake_jev = True
        copy = self.root / "questions-copy.json"
        with mock.patch.dict(os.environ, {"FAKE_JEV_QUESTIONS_COPY": str(copy)}):
            self.begin()
            copy.unlink(missing_ok=True)
            self.orch().next_tasks()
        self.assertFalse(copy.exists())
        chosen = self.record().tool_selection
        assert chosen is not None
        self.assertEqual(chosen.source, "local-policy")
