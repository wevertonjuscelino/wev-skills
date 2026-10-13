"""Tool selection through JEV, against the fake ``jev`` executable (never the real one)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.unit._agent_helpers import make
from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import HarnessSettings, LimitsConfig
from wev_skills.core.contracts import PlanTask, ToolSelection
from wev_skills.core.ports import SubprocessRunner
from wev_skills.decisions import jev_tools
from wev_skills.decisions.jev import JevProvider
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.tools.registry import ToolRegistry, ToolSpec

FAKE = str(Path(__file__).resolve().parents[1] / "fixtures" / "fake_jev.py")
TOOLS = ToolRegistry.default().list()
FULL = ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebFetch", "WebSearch"]
DOER = {"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": True}
SECRET = "sk-secret-123"


def redact(text: str) -> str:
    return text.replace(SECRET, "[REDACTED]")


def agent(allow: list[str] | None = None, deny: list[str] | None = None) -> AgentSpec:
    tools = {"allow": allow if allow is not None else FULL, "deny": deny or []}
    return make("worker", tools=tools, permissions=DOER)


def task(**fields: Any) -> PlanTask:
    base = {"id": "t", "title": "Tidy the parser", "objective": "Tidy the parser module"}
    return PlanTask.from_dict({**base, **fields})


class JevToolsCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)

    def provider(self, profile: str = "structured", command: Any = None) -> JevProvider:
        local = LocalPolicyProvider(LimitsConfig(), HarnessSettings(tool_profile=profile))
        chosen = command if command is not None else (sys.executable, FAKE)
        return JevProvider(SubprocessRunner(), local, chosen, 20.0, redactor=redact)

    def select(
        self,
        plan_task: PlanTask | None = None,
        worker: AgentSpec | None = None,
        profile: str = "structured",
        tier: str = "standard",
        answers: dict[str, float] | None = None,
        tools: Any = TOOLS,
        **env: str,
    ) -> ToolSelection:
        copies = {
            "FAKE_JEV_STATE_COPY": str(self.dir / "state.txt"),
            "FAKE_JEV_QUESTIONS_COPY": str(self.dir / "questions.json"),
            "FAKE_JEV_TOOL_ANSWERS": json.dumps(answers or {}),
        }
        with mock.patch.dict(os.environ, {**copies, **env}):
            return self.provider(profile).select_tools(
                plan_task or task(), worker or agent(), tools, tier
            )

    def questions(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads((self.dir / "questions.json").read_text("utf-8"))
        return loaded

    def state(self) -> str:
        return (self.dir / "state.txt").read_text("utf-8")

    def asked(self) -> bool:
        return (self.dir / "questions.json").exists()

    def assertFellBack(self, chosen: ToolSelection, why: str) -> None:
        self.assertEqual(chosen.source, "local-policy")
        self.assertIn(why, chosen.reasons[0])
        self.assertEqual(chosen.selected, ("Read", "Grep", "Glob", "Edit"))


class SuccessTests(JevToolsCase):
    def test_a_tool_at_or_below_the_threshold_is_dropped_and_others_kept(self) -> None:
        answers = {"Write": 0.2, "Bash": 0.05, "WebFetch": 0.21, "WebSearch": 0.9}
        chosen = self.select(answers=answers)
        self.assertEqual(chosen.source, "jev")
        self.assertEqual(chosen.selected, ("Read", "Grep", "Glob", "Edit", "WebFetch", "WebSearch"))
        self.assertEqual(chosen.dropped, ("Write", "Bash"))
        self.assertTrue(any(r.startswith("Write dropped") and "0.2" in r for r in chosen.reasons))
        self.assertTrue(any(r.startswith("WebFetch kept") for r in chosen.reasons))

    def test_an_unsure_answer_keeps_the_tool(self) -> None:
        chosen = self.select(answers={"Write": 0.5, "Bash": 0.3})
        self.assertIn("Write", chosen.selected)
        self.assertIn("Bash", chosen.selected)

    def test_the_floor_is_never_asked_about_and_never_dropped(self) -> None:
        answers = dict.fromkeys(FULL, 0.0)
        chosen = self.select(task(checks=["make test"]), answers=answers)
        self.assertEqual(
            sorted(self.questions()), ["tool_WebFetch", "tool_WebSearch", "tool_Write"]
        )
        self.assertEqual(chosen.selected, ("Read", "Grep", "Glob", "Edit", "Bash"))
        self.assertTrue(any("not asked about" in r and "Read" in r for r in chosen.reasons))

    def test_one_noul_question_per_tool_with_the_registry_description(self) -> None:
        self.select()
        question = self.questions()["tool_WebFetch"]
        self.assertEqual(question["type"], "noul")
        self.assertIn("Does this task need the WebFetch tool", question["instructions"])
        self.assertTrue(question["instructions"].endswith("Fetch a URL (read-only)?"))
        self.assertNotIn("profile", self.questions())

    def test_denied_tools_are_neither_asked_about_nor_selected(self) -> None:
        chosen = self.select(worker=agent(deny=["Bash", "WebSearch"]))
        self.assertNotIn("tool_Bash", self.questions())
        self.assertNotIn("Bash", chosen.selected)
        self.assertNotIn("Bash", chosen.offered)

    def test_scoped_entries_are_asked_once_by_base_name(self) -> None:
        worker = agent(["Read", "Bash(git:*)", "Bash(make:*)"])
        chosen = self.select(worker=worker, answers={"Bash": 0.0})
        self.assertEqual(list(self.questions()), ["tool_Bash"])
        self.assertEqual(chosen.dropped, ("Bash(git:*)", "Bash(make:*)"))

    def test_the_state_is_the_task_text_only_and_goes_through_the_redactor(self) -> None:
        secret_task = task(
            objective=f"Rotate the key {SECRET} in the parser",
            acceptance_criteria=["The parser test passes"],
            files=["src/private/parser.py"],
        )
        self.select(secret_task)
        state = self.state()
        self.assertNotIn(SECRET, state)
        self.assertIn("[REDACTED]", state)
        self.assertIn("Tidy the parser", state)
        self.assertIn("The parser test passes", state)
        self.assertNotIn("src/private/parser.py", state)

    def test_nothing_to_ask_makes_no_call(self) -> None:
        chosen = self.select(worker=agent(["Read", "Grep", "Edit"]))
        self.assertFalse(self.asked())
        self.assertEqual(chosen.source, "local-policy")
        self.assertIn("nothing to ask", chosen.reasons[0])


class ProfileTests(JevToolsCase):
    def test_the_profile_is_asked_only_when_the_setting_is_auto(self) -> None:
        self.select(profile="auto")
        question = self.questions()["profile"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(sorted(question["criteria"]), ["lean", "structured"])
        self.assertIn("shell", question["criteria"]["lean"])

    def test_a_confident_choice_sets_the_profile(self) -> None:
        chosen = self.select(task(checks=["make test"]), profile="auto", FAKE_JEV_PROFILE="lean")
        self.assertEqual((chosen.profile, chosen.selected), ("lean", ("Read", "Edit", "Bash")))

    def test_a_choice_below_the_trust_threshold_keeps_the_local_profile(self) -> None:
        env = {"FAKE_JEV_PROFILE": "lean", "FAKE_JEV_PROFILE_CONFIDENCE": "0.59"}
        chosen = self.select(profile="auto", **env)
        self.assertEqual((chosen.source, chosen.profile), ("jev", "structured"))
        self.assertTrue(any("not trusted" in r for r in chosen.reasons))
        premium = self.select(profile="auto", tier="premium", FAKE_JEV_PROFILE_CONFIDENCE="0.1")
        self.assertEqual(premium.profile, "lean")


class FallbackTests(JevToolsCase):
    def test_each_failure_mode_falls_back_to_the_local_selection(self) -> None:
        cases = {
            "error": "exit code 1",
            "garbage": "invalid JSON output",
            "tools-badshape": "unparseable answer",
            "tools-missing": "missing answer",
            "tools-not-object": "not an object",
        }
        for mode, why in cases.items():
            with self.subTest(mode=mode):
                chosen = self.select(FAKE_JEV_MODE=mode)
                self.assertFellBack(chosen, why)
                self.assertIn("JEV was unavailable", chosen.reasons[0])

    def test_a_wrong_profile_answer_falls_back(self) -> None:
        chosen = self.select(profile="auto", FAKE_JEV_MODE="tools-bad-profile")
        self.assertFellBack(chosen, "unparseable answer")

    def test_a_missing_binary_falls_back(self) -> None:
        provider = self.provider(command="/nonexistent/jev-binary")
        chosen = provider.select_tools(task(), agent(), TOOLS, "standard")
        self.assertFellBack(chosen, "binary not found")

    def test_a_timeout_falls_back(self) -> None:
        local = LocalPolicyProvider(LimitsConfig())
        slow = JevProvider(SubprocessRunner(), local, (sys.executable, FAKE), 0.5, redactor=redact)
        with mock.patch.dict(os.environ, {"FAKE_JEV_MODE": "slow"}):
            chosen = slow.select_tools(task(), agent(), TOOLS, "standard")
        self.assertFellBack(chosen, "timed out")

    def test_fallback_reasons_follow_the_language(self) -> None:
        with i18n.use_language("pt-BR"):
            chosen = self.select(FAKE_JEV_MODE="error")
        self.assertIn("indisponível", chosen.reasons[0])

    def test_more_tools_than_the_cap_fall_back_without_a_call(self) -> None:
        extra = [f"mcp__srv__tool{i}" for i in range(jev_tools.MAX_TOOL_QUESTIONS + 1)]
        chosen = self.select(worker=agent(["Read", "Edit", *extra]))
        self.assertFalse(self.asked())
        self.assertEqual(chosen.source, "local-policy")
        self.assertIn("more than the limit", chosen.reasons[0])
        self.assertEqual(chosen.selected, ("Read", "Edit"))

    def test_exactly_the_cap_is_asked(self) -> None:
        extra = [f"mcp__srv__tool{i}" for i in range(jev_tools.MAX_TOOL_QUESTIONS)]
        chosen = self.select(worker=agent(["Read", "Edit", *extra]))
        self.assertEqual(len(self.questions()), jev_tools.MAX_TOOL_QUESTIONS)
        self.assertEqual(chosen.source, "jev")

    def test_a_tool_without_a_registry_entry_is_asked_without_a_description(self) -> None:
        self.select(worker=agent(["Read", "Lookup"]), tools=(ToolSpec("Other"),))
        self.assertEqual(
            self.questions()["tool_Lookup"]["instructions"], "Does this task need the Lookup tool?"
        )

    def test_the_drop_threshold_is_the_documented_constant(self) -> None:
        self.assertEqual(jev_tools.DROP_THRESHOLD, 0.2)


if __name__ == "__main__":
    unittest.main()
