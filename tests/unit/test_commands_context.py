from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from wev_skills import cli, i18n


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def item(item_id: str, kind: str, tokens: int) -> dict[str, object]:
    return {"id": item_id, "kind": kind, "text": item_id[0] * (tokens * 4)}


class ContextCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.archive = self.tmp / "archive"
        self.items_file = self.tmp / "items.json"

    def write_items(self, payload: object) -> None:
        self.items_file.write_text(json.dumps(payload), encoding="utf-8")

    def compact(self, *extra: str) -> tuple[int, str, str]:
        return run_main("context", "compact", "--items-file", str(self.items_file), *extra)

    def test_compact_elides_archives_and_reports(self) -> None:
        items = [item("req", "requirement", 300)]
        items += [item(f"t{i}", "tool_output", 1000) for i in range(5)]
        self.write_items(items)
        code, out, _ = self.compact("--budget", "6000", "--archive-dir", str(self.archive))
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["report"]["elided_ids"], ["t0", "t1"])
        self.assertEqual(data["report"]["tokens_before"], 5300)
        self.assertFalse(data["report"]["over_budget"])
        self.assertEqual([i["id"] for i in data["items"]], ["req", "t0", "t1", "t2", "t3", "t4"])
        self.assertTrue(data["items"][1]["elided"])
        self.assertEqual(data["items"][0]["text"], "r" * 1200)
        self.assertLess(data["usage"], 0.6)

        code, out, _ = run_main("context", "recall", "--archive-dir", str(self.archive), "t0")
        self.assertEqual((code, json.loads(out)), (0, {"id": "t0", "text": "t" * 4000}))

    def test_compact_accepts_object_with_items_and_uses_config_budget(self) -> None:
        self.write_items({"items": [item("n1", "note", 10)]})
        code, out, _ = self.compact()
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["usage"], 10 / 100000)
        self.assertEqual(data["report"]["elided_ids"], [])

    def test_compact_reports_skipped_summarization_and_over_budget(self) -> None:
        self.write_items([item("n1", "note", 500), item("n2", "note", 500)])
        code, out, _ = self.compact("--budget", "100")
        report = json.loads(out)["report"]
        self.assertEqual(code, 0)
        self.assertTrue(report["over_budget"])
        self.assertEqual(report["stage2_skipped_reason"], i18n.t("context.stage2.no_summarizer"))

    def test_compact_rejects_bad_input(self) -> None:
        code, _, err = self.compact()
        self.assertEqual((code, json.loads(err)["error"]["code"]), (7, "file_not_found"))
        for payload in ("{nope", '"text"', "[1]", '{"items": "x"}'):
            self.items_file.write_text(payload, encoding="utf-8")
            code, _, err = self.compact()
            self.assertEqual((code, json.loads(err)["error"]["code"]), (2, "invalid_items_file"))
        self.write_items([{"id": "../x", "kind": "note", "text": "t"}])
        code, _, err = self.compact()
        self.assertEqual((code, json.loads(err)["error"]["code"]), (2, "invalid_item_id"))
        self.write_items([item("n1", "note", 1)])
        code, _, err = self.compact("--budget", "0")
        self.assertEqual((code, json.loads(err)["error"]["code"]), (2, "invalid_context"))

    def test_recall_errors(self) -> None:
        self.archive.mkdir()
        (self.tmp / "secret.txt").write_text("outside", encoding="utf-8")
        code, _, err = run_main("context", "recall", "--archive-dir", str(self.archive), "nope")
        self.assertEqual((code, json.loads(err)["error"]["code"]), (7, "archive_not_found"))
        code, _, err = run_main(
            "context", "recall", "--archive-dir", str(self.archive), "../secret"
        )
        self.assertEqual((code, json.loads(err)["error"]["code"]), (2, "invalid_item_id"))

    def test_help_is_translated(self) -> None:
        code, out, _ = run_main("--lang", "pt-BR", "context", "--help")
        self.assertEqual(code, 0)
        self.assertIn("Compacta os itens", out)


if __name__ == "__main__":
    unittest.main()
