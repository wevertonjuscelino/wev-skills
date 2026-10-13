"""The lexical floor: what the objective says counts, whatever the flags and the provider say."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests.unit._agent_helpers import make
from wev_skills.config import LimitsConfig
from wev_skills.core.contracts import (
    AttemptRecord,
    Complexity,
    GuardAction,
    Mode,
    PlanTask,
    RiskLevel,
    TaskSignals,
    TaskStatus,
)
from wev_skills.core.ports import SubprocessRunner
from wev_skills.decisions import lexicon
from wev_skills.decisions.jev import JevProvider
from wev_skills.decisions.local import LocalPolicyProvider

FAKE = str(Path(__file__).resolve().parents[1] / "fixtures" / "fake_jev.py")


def policy(max_attempts: int = 3) -> LocalPolicyProvider:
    return LocalPolicyProvider(LimitsConfig(max_attempts=max_attempts))


def classify(objective: str, **flags: object):  # type: ignore[no-untyped-def]
    return policy().classify_task(TaskSignals(objective, files_touched_estimate=1, **flags))  # type: ignore[arg-type]


def failed(number: int, signature: str = "") -> AttemptRecord:
    return AttemptRecord("t", number, TaskStatus.FAILED, "m", signature)


class LexiconTests(unittest.TestCase):
    def signals(self, text: str) -> set[str]:
        return {hit.signal for hit in lexicon.scan(text)}

    def test_each_family_is_recognized_in_english_and_portuguese(self) -> None:
        cases = {
            "Fix the report in production": "touches_production",
            "Corrigir o relatório em produção": "touches_production",
            "Drop the legacy table": "destructive",
            "git push --force to main": "destructive",
            "run rm -rf build": "destructive",
            "Apagar os registros antigos": "destructive",
            "Deploy the build": "external_side_effects",
            "Publicar o pacote": "external_side_effects",
            "Tail logs on the server": "touches_remote",
            "Reiniciar o servidor": "touches_remote",
            "Rotate the API key": "touches_credentials",
            "Trocar a senha do banco": "touches_credentials",
            "Change the database schema": "changes_data_schema",
            "Alterar o esquema do banco de dados": "changes_data_schema",
        }
        for text, signal in cases.items():
            self.assertIn(signal, self.signals(text), text)

    def test_matching_is_by_whole_word_and_case_insensitive(self) -> None:
        self.assertEqual(self.signals("Add a dropdown and a product page"), set())
        self.assertEqual(self.signals("Improve the observer pattern"), set())
        self.assertIn("destructive", self.signals("DELETE old rows"))

    def test_plain_objectives_raise_nothing(self) -> None:
        for text in ("Add a greeting", "Fix typo in the README", "Refactor the date parser"):
            self.assertEqual(self.signals(text), set(), text)


class ClassificationFloorTests(unittest.TestCase):
    def test_objective_alone_raises_risk_and_names_the_matched_term(self) -> None:
        result = classify("Drop the legacy table in production")
        self.assertIs(result.risk, RiskLevel.HIGH)
        joined = " ".join(result.reasons)
        self.assertIn("'drop'", joined)
        self.assertIn("'production'", joined)

    def test_a_plain_objective_stays_low(self) -> None:
        self.assertIs(classify("Add a greeting").risk, RiskLevel.LOW)

    def test_flags_add_signals_but_cannot_clear_an_inferred_one(self) -> None:
        explicit = classify("Add a greeting", destructive=True)
        self.assertIs(explicit.risk, RiskLevel.HIGH)
        cleared = classify("Delete every user row", destructive=False, touches_production=False)
        self.assertIs(cleared.risk, RiskLevel.HIGH)

    def test_remote_credentials_and_schema_raise_to_at_least_medium(self) -> None:
        for text in ("Read logs over ssh", "Rotate the password", "Change the database schema"):
            self.assertIs(classify(text).risk, RiskLevel.MEDIUM, text)

    def test_strategy_is_computed_from_the_floored_values(self) -> None:
        provider = policy()
        strategy = provider.select_strategy(classify("Deploy to production"), Mode.AUTO)
        self.assertTrue(strategy.needs_approval)
        self.assertTrue(strategy.needs_independent_review)
        self.assertTrue(strategy.needs_plan)


class ExternalProviderFloorTests(unittest.TestCase):
    def jev(self, mode: str, signals: TaskSignals):  # type: ignore[no-untyped-def]
        provider = JevProvider(
            SubprocessRunner(),
            policy(),
            command=(sys.executable, FAKE),
            timeout_seconds=20.0,
            redactor=lambda text: text,
        )
        with mock.patch.dict(os.environ, {"FAKE_JEV_MODE": mode}):
            return provider, provider.classify_task(signals)

    def test_an_external_low_answer_cannot_remove_approval_or_review(self) -> None:
        signals = TaskSignals("Drop the users table in production", files_touched_estimate=1)
        provider, result = self.jev("ok", signals)
        self.assertEqual(result.source, "jev")
        self.assertIs(result.risk, RiskLevel.HIGH)
        strategy = provider.select_strategy(result, Mode.AUTO)
        self.assertTrue(strategy.needs_approval)
        self.assertTrue(strategy.needs_independent_review)

    def test_an_external_answer_cannot_lower_complexity(self) -> None:
        signals = TaskSignals("Rework the importer", files_touched_estimate=30, unknowns=5)
        provider, result = self.jev("ok", signals)
        self.assertIs(result.complexity, Complexity.COMPLEX)
        self.assertTrue(provider.select_strategy(result, Mode.AUTO).needs_independent_review)
        self.assertTrue(any("complexity" in reason.lower() for reason in result.reasons))

    def test_an_external_answer_may_raise_complexity_and_risk(self) -> None:
        signals = TaskSignals("Add a greeting", files_touched_estimate=1)
        self.assertIs(self.jev("complex", signals)[1].complexity, Complexity.COMPLEX)
        self.assertIs(self.jev("high-risk", signals)[1].risk, RiskLevel.HIGH)


class RoutingTests(unittest.TestCase):
    def agents(self):  # type: ignore[no-untyped-def]
        doer = {"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": True}
        reader = {"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": False}
        return [
            make("senior-engineer", specialties=["implementation", "debugging"], permissions=doer),
            make("code-reviewer", specialties=["code-review", "correctness"], permissions=reader),
            make(
                "security-auditor",
                specialties=["security", "vulnerabilities"],
                permissions=reader,
            ),
            make(
                "remote-ops",
                specialties=["remote", "ssh", "deployment"],
                permissions={**reader, "may_use_remote": True},
            ),
        ]

    def route(self, title: str, objective: str = "", read_only: bool = False) -> str:
        task = PlanTask("t", title, objective, read_only=read_only)
        return policy().route_agent(task, self.agents(), "senior-engineer")

    def test_read_only_security_review_goes_to_the_security_agent(self) -> None:
        self.assertEqual(
            self.route("Review the login code for security", "", True), "security-auditor"
        )
        self.assertEqual(
            self.route("Auditoria de segurança do módulo", "", True), "security-auditor"
        )

    def test_security_work_that_changes_files_is_not_sent_to_the_auditor_by_this_rule(self) -> None:
        chosen = self.route("Review and review again", "code-review of the patch", False)
        self.assertEqual(chosen, "code-reviewer")

    def test_remote_tasks_go_to_an_agent_allowed_to_use_remote_systems(self) -> None:
        self.assertEqual(self.route("Check disk usage on the server"), "remote-ops")
        self.assertEqual(self.route("Ver os logs no servidor"), "remote-ops")

    def test_without_a_remote_capable_agent_the_usual_scoring_applies(self) -> None:
        task = PlanTask("t", "Check the server implementation", "")
        chosen = policy().route_agent(task, self.agents()[:2], "senior-engineer")
        self.assertEqual(chosen, "senior-engineer")


class EscalationRuleTests(unittest.TestCase):
    """Escalation fires after half the attempts (rounded up) or on a repeated error,
    whichever comes first, so an escalated model always gets an attempt of its own."""

    def decide(self, limit: int, *records: AttemptRecord):  # type: ignore[no-untyped-def]
        return policy(limit).should_escalate(records)

    def test_no_failure_no_escalation(self) -> None:
        decision = self.decide(3)
        self.assertEqual((decision.escalate, decision.action), (False, GuardAction.CONTINUE))

    def test_half_the_attempts_escalates_while_attempts_remain(self) -> None:
        self.assertFalse(self.decide(3, failed(1, "a")).escalate)
        second = self.decide(3, failed(1, "a"), failed(2, "b"))
        self.assertEqual((second.escalate, second.action), (True, GuardAction.ESCALATE))
        self.assertTrue(self.decide(2, failed(1, "a")).escalate)
        self.assertFalse(self.decide(6, failed(1, "a"), failed(2, "b")).escalate)
        self.assertTrue(self.decide(6, failed(1, "a"), failed(2, "b"), failed(3, "c")).escalate)

    def test_a_repeated_error_signature_escalates_before_half(self) -> None:
        decision = self.decide(6, failed(1, "same"), failed(2, "same"))
        self.assertEqual((decision.escalate, decision.action), (True, GuardAction.ESCALATE))
        self.assertFalse(self.decide(6, failed(1), failed(2)).escalate)

    def test_exhausted_attempts_ask_a_human(self) -> None:
        decision = self.decide(3, failed(1, "a"), failed(2, "b"), failed(3, "c"))
        self.assertEqual((decision.escalate, decision.action), (True, GuardAction.ASK_HUMAN))

    def test_the_effective_limit_of_the_task_can_be_passed(self) -> None:
        provider = policy(6)
        decision = provider.should_escalate([failed(1, "a")], max_attempts=2)
        self.assertTrue(decision.escalate)


if __name__ == "__main__":
    unittest.main()
