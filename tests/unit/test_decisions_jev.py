from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest import mock

from wev_skills import i18n
from wev_skills.config import LimitsConfig
from wev_skills.core.contracts import Complexity, RawCommandResult, RiskLevel, TaskSignals
from wev_skills.core.ports import SubprocessRunner
from wev_skills.decisions import jev as jev_module
from wev_skills.decisions.jev import JevProvider, JevUnavailable, parse_answers
from wev_skills.decisions.local import LocalPolicyProvider

FAKE = str(Path(__file__).resolve().parents[1] / "fixtures" / "fake_jev.py")
SECRET = "sk-secret-123"


def redact(text: str) -> str:
    return text.replace(SECRET, "[REDACTED]")


def provider(command: object = None, timeout: float = 20.0) -> JevProvider:
    return JevProvider(
        SubprocessRunner(),
        LocalPolicyProvider(LimitsConfig()),
        command=command if command is not None else (sys.executable, FAKE),  # type: ignore[arg-type]
        timeout_seconds=timeout,
        redactor=redact,
    )


class JevCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_mode(self, mode: str, signals: TaskSignals | None = None, **env: str):  # type: ignore[no-untyped-def]
        sig = signals or TaskSignals(objective="add a feature")
        with mock.patch.dict(os.environ, {"FAKE_JEV_MODE": mode, **env}):
            return provider().classify_task(sig)

    def assertFellBack(self, c, why: str) -> None:  # type: ignore[no-untyped-def]
        self.assertEqual(c.source, "local-policy")
        self.assertIn("JEV was unavailable", c.reasons[0])
        self.assertIn(why, c.reasons[0])


class SuccessTests(JevCase):
    def test_recorded_real_response_end_to_end(self) -> None:
        c = self.run_mode("ok")
        self.assertEqual(c.source, "jev")
        self.assertEqual(c.complexity, Complexity.TRIVIAL)
        self.assertEqual(c.risk, RiskLevel.LOW)
        self.assertFalse(c.parallelizable)
        self.assertEqual(c.uncertainty, 0.0)

    def test_fake_ok_mode_serves_the_fixture_verbatim(self) -> None:
        fixture = Path(FAKE).with_name("jev_ask_response_2026-10-13.json")
        parsed = parse_answers(fixture.read_text(encoding="utf-8"))
        self.assertEqual(parsed.complexity.value, Complexity.TRIVIAL)
        self.assertEqual(parsed.risk.value, RiskLevel.LOW)
        self.assertFalse(parsed.parallelizable.value)

    def test_score_index_is_zero_based_in_order(self) -> None:
        self.assertEqual(self.run_mode("complex").complexity, Complexity.COMPLEX)

    def test_noul_at_or_above_threshold_is_yes(self) -> None:
        self.assertTrue(self.run_mode("parallel-yes").parallelizable)

    def test_risk_floor_never_lowers(self) -> None:
        c = self.run_mode("ok", TaskSignals(objective="x", destructive=True))
        self.assertEqual(c.source, "jev")
        self.assertEqual(c.risk, RiskLevel.HIGH)
        self.assertTrue(any("higher level was kept" in r for r in c.reasons))

    def test_jev_may_raise_risk_without_floor_reason(self) -> None:
        c = self.run_mode("high-risk")
        self.assertEqual(c.risk, RiskLevel.HIGH)
        self.assertFalse(any("higher level was kept" in r for r in c.reasons))


class ConfidenceTests(JevCase):
    def test_low_confidence_uses_local_values_with_reasons(self) -> None:
        signals = TaskSignals(objective="x", files_touched_estimate=2, has_tests=True)
        c = self.run_mode("low-confidence", signals)
        local = LocalPolicyProvider(LimitsConfig()).classify_task(signals)
        self.assertEqual(c.source, "jev")
        self.assertEqual(c.complexity, local.complexity)
        self.assertNotEqual(c.complexity, Complexity.COMPLEX)
        self.assertEqual(c.risk, local.risk)
        self.assertEqual(sum("was not trusted" in r for r in c.reasons), 2)

    def test_uncertain_noul_uses_local_value(self) -> None:
        c = self.run_mode("uncertain-noul", TaskSignals(objective="x", independent_subtasks=3))
        self.assertTrue(c.parallelizable)
        self.assertTrue(any("parallelizable was not trusted" in r for r in c.reasons))

    def test_uncertainty_rises_with_lowest_trusted_confidence(self) -> None:
        c = self.run_mode("mid-confidence")
        self.assertAlmostEqual(c.uncertainty, 0.2)
        self.assertEqual(c.complexity, Complexity.MODERATE)

    def test_uncertainty_never_drops_below_local(self) -> None:
        c = self.run_mode("ok", TaskSignals(objective="x", has_tests=False))
        self.assertAlmostEqual(c.uncertainty, 0.2)


class FallbackTests(JevCase):
    def test_exit_one(self) -> None:
        self.assertFellBack(self.run_mode("error"), "exit code 1")

    def test_invalid_json(self) -> None:
        self.assertFellBack(self.run_mode("garbage"), "invalid JSON")

    def test_unparseable_shape_and_missing_answer(self) -> None:
        self.assertFellBack(self.run_mode("badshape"), "unparseable")
        self.assertFellBack(self.run_mode("missing-answer"), "missing answer")

    def test_invalid_values_fall_back(self) -> None:
        for mode in (
            "bad-index",
            "negative-index",
            "unknown-choice",
            "wrong-types",
            "bool-score",
            "bool-noul",
            "noul-out-of-range",
            "bad-confidence",
        ):
            with self.subTest(mode=mode):
                self.assertFellBack(self.run_mode(mode), "unparseable")

    def test_timeout(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_JEV_MODE": "slow"}):
            c = provider(timeout=1.0).classify_task(TaskSignals(objective="x"))
        self.assertFellBack(c, "timed out")

    def test_missing_binary(self) -> None:
        c = provider(command="definitely-not-a-real-binary-xyz").classify_task(
            TaskSignals(objective="x")
        )
        self.assertFellBack(c, "binary not found")

    def test_runner_raising_oserror(self) -> None:
        class Boom:
            def run(
                self,
                argv: Sequence[str],
                cwd: str | None,
                timeout: float | None,
                env: Mapping[str, str] | None,
            ) -> RawCommandResult:
                raise OSError("nope")

        p = JevProvider(Boom(), LocalPolicyProvider(LimitsConfig()), redactor=redact)
        self.assertFellBack(p.classify_task(TaskSignals(objective="x")), "binary not found")

    def test_fallback_keeps_local_risk(self) -> None:
        c = self.run_mode("error", TaskSignals(objective="x", destructive=True))
        self.assertEqual(c.risk, RiskLevel.HIGH)


class PrivacyTests(JevCase):
    def test_redactor_applied_to_state_file(self) -> None:
        copy = os.path.join(self.tmp.name, "state.txt")
        self.run_mode("ok", TaskSignals(objective=f"use key {SECRET}"), FAKE_JEV_STATE_COPY=copy)
        seen = Path(copy).read_text(encoding="utf-8")
        self.assertIn("[REDACTED]", seen)
        self.assertNotIn(SECRET, seen)

    def test_state_not_in_reasons_and_temp_files_removed(self) -> None:
        argv_copy = os.path.join(self.tmp.name, "argv.json")
        c = self.run_mode(
            "ok", TaskSignals(objective="very private objective"), FAKE_JEV_ARGV_COPY=argv_copy
        )
        self.assertFalse(any("private objective" in r for r in c.reasons))
        argv = json.loads(Path(argv_copy).read_text(encoding="utf-8"))
        self.assertEqual(argv[0], "ask")
        for flag in ("--questions", "--state-file"):
            self.assertFalse(os.path.exists(argv[argv.index(flag) + 1]))

    def test_questions_file_follows_cli_format(self) -> None:
        copy = os.path.join(self.tmp.name, "q.json")
        self.run_mode("ok", FAKE_JEV_QUESTIONS_COPY=copy)
        q = json.loads(Path(copy).read_text(encoding="utf-8"))
        self.assertEqual(q["complexity"]["type"], "score")
        self.assertEqual(len(q["complexity"]["criteria"]), 4)
        self.assertEqual(q["risk"]["type"], "choice")
        self.assertEqual(set(q["risk"]["criteria"]), {"low", "medium", "high"})
        self.assertEqual(q["parallelizable"]["type"], "noul")

    def test_redactor_is_required(self) -> None:
        with self.assertRaises(TypeError):
            JevProvider(SubprocessRunner(), LocalPolicyProvider(LimitsConfig()))  # type: ignore[call-arg]


class DelegationAndParsingTests(unittest.TestCase):
    def test_other_methods_delegate_to_local(self) -> None:
        p = provider()
        c = LocalPolicyProvider(LimitsConfig()).classify_task(TaskSignals(objective="x"))
        from wev_skills.core.contracts import Mode

        self.assertEqual(
            p.select_strategy(c, Mode.AUTO),
            LocalPolicyProvider(LimitsConfig()).select_strategy(c, Mode.AUTO),
        )
        self.assertEqual(p.should_escalate([]).action.value, "continue")

    def test_parse_answers_rejects_guessed_formats(self) -> None:
        guessed = (
            '{"complexity": 2, "risk": "low", "parallelizable": true}',
            '{"answers": {}}',
            (
                '{"complexity": {"answer": 1}, "risk": {"value": "low"},'
                ' "parallelizable": {"answer": true}}'
            ),
            "[1, 2]",
        )
        for bad in guessed:
            with self.subTest(bad=bad), self.assertRaises(JevUnavailable):
                parse_answers(bad)

    def test_noul_boundaries(self) -> None:
        def parse(v: str):  # type: ignore[no-untyped-def]
            doc = json.loads(Path(FAKE).with_name("jev_ask_response_2026-10-13.json").read_text())
            doc["parallelizable"]["noul"] = json.loads(v)
            return parse_answers(json.dumps(doc)).parallelizable

        self.assertTrue(parse("0.5").value)
        self.assertTrue(parse("0.35").trusted)
        self.assertTrue(parse("0.65").trusted)
        self.assertFalse(parse("0.5").trusted)
        self.assertFalse(parse("0.4999").value)


class LocalizedReasonTests(JevCase):
    """The reasons that explain a fallback or a distrusted answer follow the language."""

    def reasons_in(self, lang: str, mode: str, signals: TaskSignals | None = None) -> list[str]:
        with i18n.use_language(lang):
            return list(self.run_mode(mode, signals).reasons)

    def test_distrusted_answers_are_explained_in_portuguese(self) -> None:
        signals = TaskSignals(objective="x", files_touched_estimate=2, has_tests=True)
        reasons = self.reasons_in("pt-BR", "low-confidence", signals)
        distrusted = [r for r in reasons if "não foi considerada confiável" in r]
        self.assertEqual(len(distrusted), 2)
        self.assertFalse(any("was not trusted" in r for r in reasons))

    def test_distrusted_answers_stay_in_english_by_default(self) -> None:
        signals = TaskSignals(objective="x", files_touched_estimate=2, has_tests=True)
        reasons = self.reasons_in("en", "low-confidence", signals)
        self.assertEqual(sum("was not trusted" in r for r in reasons), 2)

    def test_fallback_causes_are_translated(self) -> None:
        cases = {
            "error": "código de saída 1",
            "garbage": "saída JSON inválida",
            "badshape": "ilegível",
            "missing-answer": "resposta ausente",
            "bad-index": "resposta ilegível",
        }
        for mode, expected in cases.items():
            with self.subTest(mode=mode):
                first = self.reasons_in("pt-BR", mode)[0]
                self.assertIn("indisponível", first)
                self.assertIn(expected, first)
                self.assertNotIn("JEV was unavailable", first)

    def test_no_english_literal_reasons_remain_in_the_adapter(self) -> None:
        source = Path(jev_module.__file__).read_text(encoding="utf-8")
        phrases = ("was not trusted", "timed out", "binary not found", "invalid JSON output")
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, source)


if __name__ == "__main__":
    unittest.main()
