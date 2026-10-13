from __future__ import annotations

import json
import re
import unittest

from wev_skills import i18n
from wev_skills.evaluation import harness, report
from wev_skills.evaluation.configs import load_configs
from wev_skills.evaluation.metrics import EVIDENCE_LABEL, EvalReport
from wev_skills.evaluation.tasks import CONFIGS_FILE, EVALS_DIR, TASKS_SUBDIR, load_tasks

BASELINE_JSON = EVALS_DIR / "reports" / "scripted-baseline.json"
BASELINE_MARKDOWN = EVALS_DIR / "reports" / "scripted-baseline.md"
LANGUAGES = ("en", "pt-BR")
FORBIDDEN = re.compile(r"improv|melhor|speed-?up|faster|better|%", re.IGNORECASE)


def shipped_report() -> EvalReport:
    return harness.run(load_tasks(EVALS_DIR / TASKS_SUBDIR), load_configs(EVALS_DIR / CONFIGS_FILE))


class NoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = shipped_report()

    def test_notice_states_the_four_limits_in_both_languages(self) -> None:
        english = report.notice("en")
        for fragment in ("scripted agent", "harness mechanics only", "simulated", "not evidence"):
            self.assertIn(fragment, english)
        portuguese = report.notice("pt-BR")
        expected = (
            "agente roteirizado",
            "mecânica do harness",
            "simuladas",
            "não são evidência",
        )
        for fragment in expected:
            self.assertIn(fragment, portuguese)

    def test_notice_says_what_is_exercised_for_real_and_what_is_scripted(self) -> None:
        english = report.notice("en")
        real = english[
            english.index("Exercised for real") : english.index("Scripted or reimplemented")
        ]
        for component in (
            "context manager",
            "execution guard",
            "model router",
            "local decision policy",
        ):
            self.assertIn(component, real)
        scripted = english[english.index("Scripted or reimplemented") :]
        for behavior in ("retries", "scheduling", "No command is executed", "verification engine"):
            self.assertIn(behavior, scripted)
        portuguese = report.notice("pt-BR")
        for fragment in (
            "Exercitados de verdade",
            "Roteirizados ou reimplementados",
            "agendamento",
        ):
            self.assertIn(fragment, portuguese)

    def test_json_begins_with_the_notice_field_in_both_languages(self) -> None:
        for lang in LANGUAGES:
            with self.subTest(lang):
                text = report.render_json(self.result, lang)
                document = json.loads(text)
                self.assertEqual(list(document)[:2], ["notice", "language"])
                self.assertEqual(document["notice"], report.notice(lang))
                self.assertEqual(document["language"], lang)
                self.assertEqual(document["evidence_label"], EVIDENCE_LABEL)
                self.assertEqual(document["agent"], "scripted")
                self.assertTrue(text.endswith("\n"))

    def test_markdown_begins_with_the_notice_in_both_languages(self) -> None:
        for lang in LANGUAGES:
            with self.subTest(lang):
                text = report.render_markdown(self.result, lang)
                self.assertEqual(text.splitlines()[0], f"> {report.notice(lang)}")
                self.assertIn(EVIDENCE_LABEL, text)
        self.assertNotEqual(
            report.render_markdown(self.result, "en"), report.render_markdown(self.result, "pt-BR")
        )

    def test_language_changes_wording_but_not_results(self) -> None:
        english = json.loads(report.render_json(self.result, "en"))
        portuguese = json.loads(report.render_json(self.result, "pt-BR"))
        for document in (english, portuguese):
            del document["notice"], document["language"]
        self.assertEqual(english, portuguese)

    def test_ambient_language_is_used_when_none_is_given(self) -> None:
        with i18n.use_language("pt-BR"):
            self.assertEqual(json.loads(report.render_json(self.result))["language"], "pt-BR")


class ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = shipped_report()

    def test_no_improvement_claims_or_percentages_are_rendered(self) -> None:
        for lang in LANGUAGES:
            body = report.render_markdown(self.result, lang)
            self.assertIsNone(FORBIDDEN.search(body), (lang, FORBIDDEN.search(body)))
        keys = json.dumps(self.result.to_dict())
        self.assertIsNone(re.search(r"improv|delta|speedup|gain", keys))

    def test_aggregate_table_reports_raw_counts_and_rates(self) -> None:
        text = report.render_markdown(self.result, "en")
        baseline = next(a for a in self.result.aggregates if a.config_id == "baseline")
        row = next(line for line in text.splitlines() if line.startswith("| `baseline` | "))
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        head = [str(baseline.runs), str(baseline.successes), f"{baseline.success_rate:.4f}"]
        tail = [str(baseline.counts.cost_units), str(baseline.counts.duration_units)]
        self.assertEqual((cells[1:4], cells[-2:]), (head, tail))
        self.assertIn("Cost (simulated units)", text)
        self.assertIn("Duration (simulated units)", text)

    def test_markdown_has_a_section_for_every_task_and_config(self) -> None:
        text = report.render_markdown(self.result, "en")
        for task_id in self.result.task_ids:
            self.assertIn(f"### `{task_id}`", text)
        for config in self.result.configs:
            rows = text.count(f"| `{config.id}` |")
            self.assertEqual(rows, 3 + len(self.result.task_ids))

    def test_report_round_trips_through_its_dictionary(self) -> None:
        self.assertEqual(EvalReport.from_dict(self.result.to_dict()), self.result)

    def test_key_order_is_stable(self) -> None:
        first = report.render_json(self.result, "en")
        self.assertEqual(first, report.render_json(shipped_report(), "en"))
        run_keys = list(json.loads(first)["runs"][0])
        self.assertEqual(run_keys[:2], ["task_id", "config_id"])


class CommittedBaselineTests(unittest.TestCase):
    """The committed report must be exactly what the harness produces now."""

    def test_json_baseline_is_reproduced_byte_for_byte(self) -> None:
        produced = report.render_json(shipped_report(), "en").encode("utf-8")
        self.assertEqual(produced, BASELINE_JSON.read_bytes())

    def test_markdown_baseline_is_reproduced_byte_for_byte(self) -> None:
        produced = report.render_markdown(shipped_report(), "en").encode("utf-8")
        self.assertEqual(produced, BASELINE_MARKDOWN.read_bytes())


class CatalogTests(unittest.TestCase):
    def test_both_evaluation_catalogs_have_the_same_keys(self) -> None:
        keys = [
            set(json.loads((i18n.LOCALES_DIR / f"evaluation.{lang}.json").read_text("utf-8")))
            for lang in LANGUAGES
        ]
        self.assertEqual(keys[0], keys[1])
        self.assertIn("evaluation.notice", keys[0])


if __name__ == "__main__":
    unittest.main()
