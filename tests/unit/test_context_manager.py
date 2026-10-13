from __future__ import annotations

import os
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from wev_skills import context, i18n
from wev_skills.context.manager import CompactionReport, ContextItem, ContextManager
from wev_skills.context.tokens import estimate_tokens
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError

BIG = 1000  # tokens per large item (4000 characters)


def text(tokens: int, char: str = "x") -> str:
    return char * (tokens * 4)


class RecordingSummarizer:
    def __init__(self, reply: str = "short summary") -> None:
        self.reply = reply
        self.calls: list[tuple[str, ...]] = []

    def summarize(self, texts: Sequence[str]) -> str:
        self.calls.append(tuple(texts))
        return self.reply


class FailingSummarizer:
    def summarize(self, texts: Sequence[str]) -> str:
        raise RuntimeError("provider down")


def fill(manager: ContextManager, *specs: tuple[str, str, int]) -> ContextManager:
    for item_id, kind, tokens in specs:
        manager = manager.add({"id": item_id, "kind": kind, "text": text(tokens, item_id[0])})
    return manager


def by_id(manager: ContextManager) -> dict[str, ContextItem]:
    return {item.id: item for item in manager.render()}


class TokenTests(unittest.TestCase):
    def test_estimate_is_chars_over_four_rounded_up(self) -> None:
        cases = (("", 0), ("a", 1), ("abcd", 1), ("abcde", 2), ("x" * 400, 100))
        for value, expected in cases:
            self.assertEqual(estimate_tokens(value), expected)

    def test_docstrings_state_the_limits(self) -> None:
        self.assertIn("not a tokenizer", estimate_tokens.__doc__ or "")
        self.assertIn("no control over", context.__doc__ or "")


class ConstructionTests(unittest.TestCase):
    def test_invalid_thresholds_and_budget_are_rejected(self) -> None:
        bad = (
            {"budget_tokens": 0},
            {"budget_tokens": -5},
            {"budget_tokens": True},
            {"budget_tokens": 10, "elide_at": 0.0},
            {"budget_tokens": 10, "elide_at": 0.9, "summarize_at": 0.9},
            {"budget_tokens": 10, "elide_at": 0.9, "summarize_at": 0.5},
            {"budget_tokens": 10, "summarize_at": 1.01},
            {"budget_tokens": 10, "keep_recent": -1},
            {"budget_tokens": 10, "min_elide_tokens": -1},
        )
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                ContextManager(**kwargs)  # type: ignore[arg-type]
        self.assertEqual(ContextManager(10, summarize_at=1.0).summarize_at, 1.0)

    def test_add_returns_a_new_manager_and_leaves_the_original(self) -> None:
        empty = ContextManager(100)
        one = empty.add({"id": "n1", "kind": "note", "text": "abcdefgh"})
        self.assertEqual(empty.render(), [])
        self.assertEqual(one.render()[0].tokens, 2)
        self.assertEqual(one.usage(), 0.02)

    def test_add_sets_sequence_and_ignores_caller_tokens(self) -> None:
        item = ContextItem("n1", "note", "abcd", tokens=999, created_seq=42)
        manager = ContextManager(100).add({"id": "n0", "kind": "note", "text": "a"}).add(item)
        self.assertEqual([i.created_seq for i in manager.render()], [0, 1])
        self.assertEqual(manager.render()[1].tokens, 1)
        self.assertEqual(item.tokens, 999)

    def test_requirements_decisions_and_evidence_are_pinned_whatever_the_flag(self) -> None:
        manager = ContextManager(100)
        for kind in ("requirement", "decision", "evidence"):
            manager = manager.add({"id": kind, "kind": kind, "text": "t", "pinned": False})
        manager = manager.add({"id": "n", "kind": "note", "text": "t"})
        manager = manager.add({"id": "p", "kind": "note", "text": "t", "pinned": True})
        pinned = {item.id: item.pinned for item in manager.render()}
        self.assertEqual(
            pinned, {"requirement": True, "decision": True, "evidence": True, "n": False, "p": True}
        )

    def test_add_rejects_bad_items(self) -> None:
        manager = ContextManager(100).add({"id": "a", "kind": "note", "text": "t"})
        bad = (
            {"id": "a", "kind": "note", "text": "dup"},
            {"id": "b", "kind": "gossip", "text": "t"},
            {"id": "../b", "kind": "note", "text": "t"},
            {"id": "b", "kind": "note"},
            {"id": "b", "kind": "note", "text": "t", "color": "red"},
        )
        for fields in bad:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                manager.add(fields)

    def test_add_generates_an_id_when_missing(self) -> None:
        manager = ContextManager(10).add({"kind": "note", "text": "t"})
        self.assertEqual(manager.render()[0].id, "item-0")


class ElisionTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.archive = Path(tmp.name) / "archive"

    def manager(self, budget: int = 10_000, **kwargs: object) -> ContextManager:
        return ContextManager(budget, archive_dir=self.archive, **kwargs)  # type: ignore[arg-type]

    def test_nothing_is_elided_below_the_threshold(self) -> None:
        manager = fill(self.manager(), *[(f"t{i}", "tool_output", 590) for i in range(10)])
        self.assertLess(manager.usage(), 0.6)
        compacted, report = manager.compact()
        self.assertEqual(compacted, manager)
        self.assertEqual(report, CompactionReport((), (), 5900, 5900, "", False))
        self.assertFalse(self.archive.exists())

    def test_elision_starts_exactly_at_the_threshold(self) -> None:
        manager = fill(self.manager(), *[(f"t{i}", "tool_output", 600) for i in range(10)])
        self.assertEqual(manager.usage(), 0.6)
        self.assertEqual(manager.compact()[1].elided_ids, ("t0",))

    def test_oldest_tool_outputs_are_elided_first_until_below_threshold(self) -> None:
        manager = fill(self.manager(), *[(f"t{i}", "tool_output", BIG) for i in range(8)])
        compacted, report = manager.compact()
        self.assertEqual(report.elided_ids, ("t0", "t1", "t2"))
        self.assertLess(compacted.usage(), 0.6)
        self.assertEqual((report.tokens_before, report.over_budget), (8000, False))
        self.assertEqual(report.tokens_after, compacted.total_tokens())
        items = by_id(compacted)
        self.assertTrue(all(items[i].elided for i in report.elided_ids))
        self.assertEqual(items["t3"].text, text(BIG, "t"))
        self.assertEqual([i.id for i in compacted.render()], [f"t{i}" for i in range(8)])
        self.assertEqual(by_id(manager)["t0"].text, text(BIG, "t"))

    def test_recent_small_and_pinned_tool_outputs_are_skipped(self) -> None:
        manager = self.manager(budget=4000, keep_recent=2)
        pinned = {"id": "pin", "kind": "tool_output", "text": text(BIG), "pinned": True}
        manager = manager.add(pinned)
        manager = fill(
            manager,
            ("small", "tool_output", 199),
            ("old", "tool_output", BIG),
            ("r1", "tool_output", BIG),
            ("r2", "tool_output", BIG),
        )
        compacted, report = manager.compact()
        self.assertEqual(report.elided_ids, ("old",))
        self.assertGreaterEqual(compacted.usage(), 0.6)
        self.assertTrue(report.over_budget is False and report.tokens_after < 4000)

    def test_non_tool_output_kinds_are_never_elided(self) -> None:
        kinds = ("requirement", "decision", "evidence", "error", "note")
        manager = fill(self.manager(budget=1000), *[(k, k, BIG) for k in kinds])
        compacted, report = manager.compact()
        self.assertEqual(report.elided_ids, ())
        self.assertEqual(compacted.render(), manager.render())
        self.assertTrue(report.over_budget)

    def test_stub_names_the_archive_ref_and_recall_round_trips(self) -> None:
        original = "line one\nlínea dos ✓\n" + text(BIG)
        manager = self.manager(budget=1000, keep_recent=0).add(
            {"id": "out-1", "kind": "tool_output", "text": original}
        )
        compacted, report = manager.compact()
        stub = by_id(compacted)["out-1"]
        ref = str(self.archive / "out-1.txt")
        self.assertEqual(report.elided_ids, ("out-1",))
        self.assertEqual(stub.ref, ref)
        self.assertIn(ref, stub.text)
        self.assertEqual(stub.tokens, estimate_tokens(stub.text))
        self.assertEqual(compacted.recall("out-1"), original)
        self.assertEqual(Path(ref).stat().st_mode & 0o777, 0o600)

    def test_without_archive_dir_stub_says_so_and_recall_raises(self) -> None:
        manager = fill(ContextManager(1000, keep_recent=0), ("t0", "tool_output", BIG))
        compacted, report = manager.compact()
        stub = by_id(compacted)["t0"]
        self.assertEqual((report.elided_ids, stub.ref, stub.elided), (("t0",), "", True))
        self.assertEqual(stub.text, i18n.t("context.stub.unarchived", id="t0", tokens=BIG))
        with self.assertRaises(NotFound):
            compacted.recall("t0")
        with self.assertRaises(ValidationError):
            compacted.recall("../t0")

    def test_recall_unknown_id_raises_not_found(self) -> None:
        with self.assertRaises(NotFound):
            self.manager().recall("never-archived")

    def test_recall_rejects_ids_that_escape_the_archive(self) -> None:
        self.archive.mkdir(parents=True)
        (self.archive.parent / "secret.txt").write_text("outside", encoding="utf-8")
        for bad in ("../secret", "..", "a/b", "/etc/passwd", "", ".hidden", "a\\b", "x\x00y"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.manager().recall(bad)
        os.symlink(self.archive.parent / "secret.txt", self.archive / "link.txt")
        with self.assertRaises(PermissionDenied):
            self.manager().recall("link")

    def test_archive_never_overwrites_a_different_original(self) -> None:
        self.archive.mkdir(parents=True)
        (self.archive / "t0.txt").write_text("an earlier original", encoding="utf-8")
        manager = fill(self.manager(budget=1000, keep_recent=0), ("t0", "tool_output", BIG))
        with self.assertRaises(ValidationError) as caught:
            manager.compact()
        self.assertEqual(caught.exception.code, "archive_conflict")
        kept = (self.archive / "t0.txt").read_text(encoding="utf-8")
        self.assertEqual(kept, "an earlier original")

    def test_compacting_twice_does_not_elide_the_same_item_again(self) -> None:
        manager = fill(self.manager(budget=1000, keep_recent=0), ("t0", "tool_output", BIG))
        once, _ = manager.compact()
        twice, report = once.add({"id": "n", "kind": "note", "text": text(700)}).compact()
        self.assertEqual(report.elided_ids, ())
        self.assertEqual(twice.recall("t0"), text(BIG, "t"))


class SummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.archive = Path(tmp.name)

    def loaded(self, summarizer: object, **kwargs: object) -> ContextManager:
        """Pinned kinds, an old and a new error, two notes and two tool outputs: 8000 tokens."""
        options = {"keep_recent": 1, **kwargs}
        manager = ContextManager(5000, summarizer=summarizer, **options)  # type: ignore[arg-type]
        manager = fill(
            manager,
            ("req", "requirement", BIG),
            ("dec", "decision", BIG),
            ("evi", "evidence", BIG),
            ("e-old", "error", BIG),
            ("n-old", "note", BIG),
            ("t-old", "tool_output", BIG),
            ("e-new", "error", 500),
            ("n-new", "note", 500),
        )
        manager = manager.add({"id": "n-pin", "kind": "note", "text": text(500), "pinned": True})
        return fill(manager, ("t-new", "tool_output", 500))

    def test_stage_two_is_skipped_without_a_summarizer_and_reported(self) -> None:
        manager = self.loaded(None)
        compacted, report = manager.compact()
        self.assertEqual(report.elided_ids, ("t-old",))
        self.assertEqual(report.summarized_ids, ())
        self.assertEqual(report.stage2_skipped_reason, i18n.t("context.stage2.no_summarizer"))
        self.assertTrue(report.over_budget)
        self.assertEqual(len(compacted.render()), len(manager.render()))

    def test_summarizer_receives_only_unpinned_non_recent_items(self) -> None:
        summarizer = RecordingSummarizer()
        compacted, report = self.loaded(summarizer).compact()
        stub = i18n.t("context.stub.unarchived", id="t-old", tokens=BIG)
        self.assertEqual(summarizer.calls, [(text(BIG, "e"), text(BIG, "n"), stub)])
        self.assertEqual(report.summarized_ids, ("e-old", "n-old", "t-old"))
        self.assertEqual(report.stage2_skipped_reason, "")
        ids = [item.id for item in compacted.render()]
        expected = ["req", "dec", "evi", "summary-10", "e-new", "n-new", "n-pin", "t-new"]
        self.assertEqual(ids, expected)
        summary = by_id(compacted)["summary-10"]
        self.assertEqual((summary.kind, summary.text), ("note", "short summary"))
        self.assertTrue(summary.summarized and not summary.pinned)
        self.assertEqual(report.tokens_after, compacted.total_tokens())

    def test_pinned_kinds_and_latest_error_survive_any_compaction(self) -> None:
        manager = self.loaded(RecordingSummarizer(), keep_recent=0, min_elide_tokens=0)
        tiny = ContextManager(
            10,
            elide_at=0.01,
            summarize_at=0.02,
            summarizer=manager.summarizer,
            keep_recent=0,
            min_elide_tokens=0,
            items=manager.items,
            next_seq=manager.next_seq,
        )
        compacted, report = tiny.compact()
        after, before = by_id(compacted), by_id(tiny)
        for item_id in ("req", "dec", "evi", "n-pin", "e-new"):
            self.assertEqual(after[item_id], before[item_id])
        self.assertTrue(report.over_budget)
        self.assertNotIn("n-new", after)
        again, _ = compacted.compact()
        for item_id in ("req", "dec", "evi", "n-pin", "e-new"):
            self.assertEqual(by_id(again)[item_id], before[item_id])

    def test_failing_summarizer_leaves_items_untouched_and_is_reported(self) -> None:
        manager = self.loaded(FailingSummarizer())
        elided_only, _ = self.loaded(None).compact()
        compacted, report = manager.compact()
        self.assertEqual(compacted.render(), elided_only.render())
        self.assertEqual(report.summarized_ids, ())
        self.assertEqual(
            report.stage2_skipped_reason,
            i18n.t("context.stage2.summarizer_failed", error="RuntimeError"),
        )
        self.assertTrue(report.over_budget)

    def test_empty_or_larger_summary_is_rejected_and_reported(self) -> None:
        for reply, key in (("  ", "summarizer_failed"), (text(4000), "summary_not_smaller")):
            compacted, report = self.loaded(RecordingSummarizer(reply)).compact()
            self.assertEqual(report.summarized_ids, ())
            self.assertIn("e-old", by_id(compacted))
            self.assertTrue(report.stage2_skipped_reason)
            if key == "summary_not_smaller":
                self.assertEqual(
                    report.stage2_skipped_reason, i18n.t("context.stage2.summary_not_smaller")
                )

    def test_stage_two_does_not_run_when_stage_one_was_enough(self) -> None:
        summarizer = RecordingSummarizer()
        manager = ContextManager(10_000, summarizer=summarizer, keep_recent=1)
        manager = fill(manager, *[(f"t{i}", "tool_output", BIG) for i in range(9)])
        self.assertGreaterEqual(manager.usage(), 0.85)
        compacted, report = manager.compact()
        self.assertEqual(summarizer.calls, [])
        self.assertEqual((report.summarized_ids, report.stage2_skipped_reason), ((), ""))
        self.assertLess(compacted.usage(), 0.6)

    def test_nothing_to_summarize_is_reported(self) -> None:
        summarizer = RecordingSummarizer()
        manager = fill(ContextManager(1000, summarizer=summarizer), ("req", "requirement", BIG))
        _, report = manager.compact()
        self.assertEqual(summarizer.calls, [])
        self.assertEqual(
            report.stage2_skipped_reason, i18n.t("context.stage2.nothing_to_summarize")
        )
        self.assertFalse(report.over_budget)

    def test_summarized_originals_are_archived_for_recall(self) -> None:
        compacted, report = self.loaded(RecordingSummarizer(), archive_dir=self.archive).compact()
        self.assertEqual(report.summarized_ids, ("e-old", "n-old", "t-old"))
        self.assertEqual(compacted.recall("n-old"), text(BIG, "n"))
        self.assertEqual(compacted.recall("t-old"), text(BIG, "t"))

    def test_report_serializes(self) -> None:
        report = CompactionReport(("a",), ("b",), 10, 5, "why", True)
        self.assertEqual(CompactionReport.from_dict(report.to_dict()), report)


if __name__ == "__main__":
    unittest.main()
