from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.claude_code import claude_md as cm
from wev_skills.core.discovery import CheckSuggestion
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError

MAKE_TEST = CheckSuggestion("make test", "Makefile", "test")
HEADER = f"# CLAUDE.md\n\n{cm.INTRO_LINE}\n"
START = cm.START_MARKER
END = cm.END_MARKER


def outside(text: str) -> tuple[str, str]:
    """Text before the start marker and after the end marker."""
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    return head, tail


def squeeze(text: str) -> list[str]:
    return [line for line in text.replace("\r\n", "\n").split("\n") if line.strip()]


class RenderTests(unittest.TestCase):
    def test_both_languages_have_the_same_section_count_and_attribution(self) -> None:
        en, pt = cm.render_block("en"), cm.render_block("pt-BR")
        for block in (en, pt):
            self.assertTrue(block.startswith(START + "\n"))
            self.assertTrue(block.endswith(END))
            self.assertIn("forrestchang", block)
            self.assertIn("https://github.com/multica-ai/andrej-karpathy-skills", block)
            self.assertIn("MIT", block)
        self.assertEqual(len(re.findall(r"^### ", en, re.M)), 5)
        self.assertEqual(len(re.findall(r"^### ", pt, re.M)), 5)
        self.assertIn("Evidence before claims", en)
        self.assertNotEqual(en, pt)

    def test_rendering_does_not_depend_on_the_active_language(self) -> None:
        with i18n.use_language("pt-BR"):
            self.assertIn("Think before coding", cm.render_block("en"))

    def test_markers_appear_once(self) -> None:
        block = cm.render_block("en")
        self.assertEqual(block.count(START), 1)
        self.assertEqual(block.count(END), 1)


class InitTests(unittest.TestCase):
    def test_new_file_has_header_block_and_skeleton(self) -> None:
        plan = cm.plan_init(None, "en", (MAKE_TEST,))
        self.assertTrue(plan.changed)
        self.assertEqual(plan.before, "")
        self.assertTrue(plan.after.startswith(HEADER))
        self.assertIn(cm.render_block("en"), plan.after)
        for heading in ("## Commands", "## Architecture", "## Project rules"):
            self.assertIn(heading, plan.after)
        self.assertIn("- `make test` (detected in `Makefile`)", plan.after)
        self.assertEqual(plan.after.count("<!--") - 2, 2)  # two placeholders besides markers
        self.assertTrue(plan.after.endswith("\n"))
        self.assertIn("+# CLAUDE.md", plan.diff)

    def test_new_file_without_discovery_has_three_placeholders(self) -> None:
        plan = cm.plan_init(None, "en", ())
        self.assertEqual(plan.after.count("<!--") - 2, 3)

    def test_new_file_is_localized(self) -> None:
        plan = cm.plan_init(None, "pt-BR", (MAKE_TEST,))
        self.assertIn("## Comandos", plan.after)
        self.assertIn("detectado em `Makefile`", plan.after)
        self.assertIn("## Regras do projeto", plan.after)
        self.assertTrue(plan.after.startswith(HEADER))

    def test_header_only_file_gets_block_after_header(self) -> None:
        plan = cm.plan_init("# CLAUDE.md\n", "en", ())
        head, tail = outside(plan.after)
        self.assertEqual(head, "# CLAUDE.md\n\n")
        self.assertEqual(tail.strip(), "")
        self.assertNotIn("## Commands", plan.after)

    def test_header_without_trailing_newline_keeps_that_property(self) -> None:
        plan = cm.plan_init("# CLAUDE.md", "en", ())
        self.assertTrue(plan.after.endswith(END))

    def test_rich_file_keeps_every_user_line_in_order(self) -> None:
        user = HEADER + "\n## Commands\n\n- `make test`\n\n## Notes\n\nKeep it short.\n"
        plan = cm.plan_init(user, "en", (MAKE_TEST,))
        head, tail = outside(plan.after)
        self.assertEqual(squeeze(head + tail), squeeze(user))
        self.assertTrue(head.startswith(HEADER))
        self.assertTrue(plan.after.endswith("Keep it short.\n"))
        self.assertNotIn("## Architecture", plan.after)

    def test_file_without_header_gets_block_on_top(self) -> None:
        user = "Some notes\n\n## Mine\n"
        plan = cm.plan_init(user, "en", ())
        self.assertTrue(plan.after.startswith(START))
        head, tail = outside(plan.after)
        self.assertEqual(head, "")
        self.assertEqual(squeeze(tail), squeeze(user))

    def test_existing_block_behaves_as_update(self) -> None:
        current = cm.plan_init(None, "en", ()).after
        plan = cm.plan_init(current, "en", (MAKE_TEST,))
        self.assertFalse(plan.changed)
        self.assertEqual(plan.after, current)
        self.assertEqual(plan.diff, "")

    def test_empty_file_is_treated_as_having_no_header(self) -> None:
        plan = cm.plan_init("", "en", ())
        self.assertTrue(plan.after.startswith(START))

    def test_arguments_are_not_mutated(self) -> None:
        discovered = (MAKE_TEST,)
        cm.plan_init(None, "en", discovered)
        self.assertEqual(discovered, (MAKE_TEST,))


class UpdateTests(unittest.TestCase):
    def stale(self, eol: str = "\n") -> str:
        user_before = "# CLAUDE.md" + eol + eol + "mine before" + eol + eol
        user_after = eol + "## Mine" + eol + eol + "mine after" + eol
        return user_before + START + eol + "old text" + eol + END + user_after

    def test_stale_block_is_replaced_and_outside_text_is_identical(self) -> None:
        text = self.stale()
        plan = cm.plan_update(text, "en")
        self.assertTrue(plan.changed)
        self.assertIn("Think before coding", plan.after)
        self.assertNotIn("old text", plan.after)
        self.assertEqual(outside(plan.after), outside(text))
        self.assertIn("-old text", plan.diff)

    def test_current_block_reports_unchanged(self) -> None:
        text = cm.plan_init("# CLAUDE.md\n", "en", ()).after
        plan = cm.plan_update(text, "en")
        self.assertFalse(plan.changed)
        self.assertEqual(plan.after, text)

    def test_other_language_block_is_replaced_when_language_differs(self) -> None:
        text = cm.plan_init("# CLAUDE.md\n", "en", ()).after
        plan = cm.plan_update(text, "pt-BR")
        self.assertTrue(plan.changed)
        self.assertIn("Pense antes de programar", plan.after)
        self.assertEqual(outside(plan.after), outside(text))

    def test_crlf_file_keeps_crlf_everywhere(self) -> None:
        text = self.stale("\r\n")
        plan = cm.plan_update(text, "en")
        self.assertEqual(outside(plan.after), outside(text))
        self.assertNotRegex(plan.after, r"(?<!\r)\n")

    def test_crlf_current_block_is_unchanged(self) -> None:
        crlf = cm.plan_update(self.stale("\r\n"), "en").after
        self.assertFalse(cm.plan_update(crlf, "en").changed)

    def test_crlf_init_insert_uses_crlf(self) -> None:
        plan = cm.plan_init("# CLAUDE.md\r\n\r\nmine\r\n", "en", ())
        self.assertNotRegex(plan.after, r"(?<!\r)\n")
        self.assertTrue(plan.after.endswith("mine\r\n"))

    def test_no_trailing_newline_is_preserved(self) -> None:
        text = START + "\nold\n" + END + "\n\ntail without newline"
        plan = cm.plan_update(text, "en")
        self.assertTrue(plan.after.endswith("tail without newline"))
        self.assertEqual(outside(plan.after), outside(text))

    def test_missing_block_is_an_error(self) -> None:
        with self.assertRaises(ValidationError):
            cm.plan_update("# CLAUDE.md\n", "en")
        with self.assertRaises(NotFound):
            cm.plan_update(None, "en")

    def test_repeated_runs_are_idempotent(self) -> None:
        first = cm.plan_init(HEADER + "\nmine\n", "en", ()).after
        second = cm.plan_update(first, "en")
        third = cm.plan_init(second.after, "en", ())
        self.assertFalse(second.changed)
        self.assertFalse(third.changed)
        self.assertEqual(third.after, first)


class MarkerErrorTests(unittest.TestCase):
    def test_duplicate_and_unbalanced_markers_are_refused(self) -> None:
        block = cm.render_block("en")
        cases = {
            "two blocks": block + "\n" + block,
            "start only": START + "\nx\n",
            "end only": "x\n" + END + "\n",
            "reversed": END + "\nx\n" + START + "\n",
            "two starts": START + "\n" + START + "\n" + END + "\n",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(ValidationError) as caught:
                    cm.plan_update(text, "en")
                self.assertEqual(caught.exception.code, "claude_md_markers")
                with self.assertRaises(ValidationError):
                    cm.plan_init(text, "en", ())

    def test_check_reports_marker_error_instead_of_raising(self) -> None:
        report = cm.check("# CLAUDE.md\n" + START + "\n", ())
        self.assertIsNotNone(report.marker_error)
        self.assertFalse(report.ok)


class CheckTests(unittest.TestCase):
    def full(self) -> str:
        return cm.plan_init(None, "en", (MAKE_TEST,)).after

    def test_missing_file(self) -> None:
        report = cm.check(None, (MAKE_TEST,))
        self.assertFalse(report.exists)
        self.assertFalse(report.ok)

    def test_fresh_init_has_placeholders_only_in_two_sections(self) -> None:
        report = cm.check(self.full(), (MAKE_TEST,))
        self.assertTrue(report.exists and report.has_header and report.has_block)
        self.assertTrue(report.block_current)
        self.assertEqual(report.sections_missing, ())
        self.assertEqual(report.sections_placeholder, ("architecture", "rules"))
        self.assertEqual(report.undocumented_commands, ())
        self.assertFalse(report.ok)

    def test_filled_file_is_ok(self) -> None:
        text = self.full()
        text = re.sub(r"<!-- (?!wev-skills)[^>]*-->", "Real content.", text)
        report = cm.check(text, (MAKE_TEST,))
        self.assertEqual(report.sections_placeholder, ())
        self.assertTrue(report.ok, report)

    def test_missing_header_block_and_sections(self) -> None:
        report = cm.check("just text\n", ())
        self.assertFalse(report.has_header)
        self.assertFalse(report.has_block)
        self.assertFalse(report.block_current)
        self.assertEqual(report.sections_missing, ("commands", "architecture", "rules"))

    def test_stale_block(self) -> None:
        report = cm.check(START + "\nold\n" + END + "\n", ())
        self.assertTrue(report.has_block)
        self.assertFalse(report.block_current)

    def test_portuguese_headings_count_as_present(self) -> None:
        text = cm.plan_init(None, "pt-BR", ()).after
        self.assertEqual(cm.check(text, ()).sections_missing, ())

    def test_undocumented_commands_are_listed(self) -> None:
        other = CheckSuggestion("npm test", "package.json", "test")
        report = cm.check(self.full(), (MAKE_TEST, other))
        self.assertEqual(report.undocumented_commands, ("npm test",))

    def test_line_count_warning_uses_the_named_threshold(self) -> None:
        self.assertEqual(cm.MAX_RECOMMENDED_LINES, 200)
        base = self.full()
        short = cm.check(base, ())
        self.assertFalse(short.line_warning)
        long_text = base + "x\n" * cm.MAX_RECOMMENDED_LINES
        report = cm.check(long_text, ())
        self.assertTrue(report.line_warning)
        self.assertEqual(report.lines, len(long_text.splitlines()))
        self.assertTrue(report.warnings)

    def test_report_is_json_ready(self) -> None:
        data = cm.check(self.full(), ()).to_dict()
        self.assertIn("sections_placeholder", data)
        self.assertIsInstance(data["ok"], bool)


class FileTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".git").mkdir()

    def test_find_repo_root_walks_up_and_falls_back(self) -> None:
        deep = self.root / "a" / "b"
        deep.mkdir(parents=True)
        self.assertEqual(cm.find_repo_root(deep), self.root)
        with tempfile.TemporaryDirectory() as bare:
            self.assertEqual(cm.find_repo_root(Path(bare)), Path(bare).resolve())

    def test_git_file_counts_as_a_git_entry(self) -> None:
        (self.root / ".git").rmdir()
        (self.root / ".git").write_text("gitdir: elsewhere\n")
        sub = self.root / "s"
        sub.mkdir()
        self.assertEqual(cm.find_repo_root(sub), self.root)

    def test_resolve_target_inside_root(self) -> None:
        sub = self.root / "pkg"
        sub.mkdir()
        self.assertEqual(cm.resolve_target(self.root, sub), sub / "CLAUDE.md")

    def test_path_escape_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other, self.assertRaises(PermissionDenied):
            cm.resolve_target(self.root, Path(other))

    def test_symlinked_directory_escaping_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            link = self.root / "link"
            link.symlink_to(other)
            with self.assertRaises(PermissionDenied):
                cm.resolve_target(self.root, link)

    def test_missing_directory_is_not_found(self) -> None:
        with self.assertRaises(Exception) as caught:
            cm.resolve_target(self.root, self.root / "nope")
        self.assertEqual(getattr(caught.exception, "code", ""), "claude_md_no_dir")

    def test_symlink_target_is_refused_for_read_and_write(self) -> None:
        real = self.root / "real.md"
        real.write_text("# CLAUDE.md\n")
        target = self.root / "CLAUDE.md"
        target.symlink_to(real)
        with self.assertRaises(PermissionDenied):
            cm.resolve_target(self.root, self.root)
        with self.assertRaises(PermissionDenied):
            cm.read_existing(target)
        self.assertEqual(real.read_text(), "# CLAUDE.md\n")

    def test_read_existing_keeps_crlf_bytes(self) -> None:
        target = self.root / "CLAUDE.md"
        target.write_bytes(b"a\r\nb")
        self.assertEqual(cm.read_existing(target), "a\r\nb")
        self.assertIsNone(cm.read_existing(self.root / "none.md"))

    def test_invalid_utf8_is_refused(self) -> None:
        target = self.root / "CLAUDE.md"
        target.write_bytes(b"\xff\xfe")
        with self.assertRaises(ValidationError):
            cm.read_existing(target)

    def test_apply_writes_only_when_changed_and_keeps_mode(self) -> None:
        target = self.root / "CLAUDE.md"
        target.write_bytes(b"# CLAUDE.md\r\n")
        os.chmod(target, 0o644)
        plan = cm.plan_init(cm.read_existing(target), "en", (), path=str(target))
        self.assertTrue(cm.apply(plan, target))
        data = target.read_bytes()
        self.assertTrue(data.startswith(b"# CLAUDE.md\r\n"))
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        before = target.stat().st_mtime_ns
        again = cm.plan_update(cm.read_existing(target), "en", path=str(target))
        self.assertFalse(cm.apply(again, target))
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_new_file_gets_readable_mode(self) -> None:
        target = self.root / "CLAUDE.md"
        cm.apply(cm.plan_init(None, "en", ()), target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_apply_refuses_a_target_not_named_claude_md(self) -> None:
        plan = cm.plan_init(None, "en", ())
        with self.assertRaises(PermissionDenied):
            cm.apply(plan, self.root / "OTHER.md")
        self.assertFalse((self.root / "OTHER.md").exists())


if __name__ == "__main__":
    unittest.main()
