from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from wev_skills import cli, i18n
from wev_skills.adapters.claude_code import claude_md as cm


class ClaudeMdCommandCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / "Makefile").write_text("test:\n\t@echo ok\n")
        self.target = self.root / "CLAUDE.md"
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            i18n.use_language("en"),
        ):
            code = cli.main(["claude-md", *argv])
        return code, out.getvalue(), err.getvalue()


class InitTests(ClaudeMdCommandCase):
    def test_dry_run_prints_the_diff_and_writes_nothing(self) -> None:
        code, out, _ = self.run_cli("init", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("+# CLAUDE.md", out)
        self.assertIn("make test", out)
        self.assertIn("nothing was written", out)
        self.assertFalse(self.target.exists())

    def test_init_creates_the_file_and_discovers_commands(self) -> None:
        code, out, _ = self.run_cli("init")
        self.assertEqual(code, 0)
        self.assertIn("Written", out)
        text = self.target.read_text()
        self.assertIn("- `make test` (detected in `Makefile`)", text)
        self.assertIn(cm.START_MARKER, text)

    def test_init_in_portuguese(self) -> None:
        code, _, _ = self.run_cli("init", "--lang", "pt-BR")
        self.assertEqual(code, 0)
        self.assertIn("## Comandos", self.target.read_text())

    def test_init_on_user_content_preserves_it_and_is_idempotent(self) -> None:
        user = "# CLAUDE.md\r\n\r\nMy rules\r\n\r\n## Mine\r\n- keep me\r\n"
        self.target.write_bytes(user.encode())
        code, out, _ = self.run_cli("init")
        self.assertEqual(code, 0)
        self.assertIn(cm.START_MARKER, out)  # the insertion was shown
        after_first = self.target.read_bytes()
        text = after_first.decode()
        head, _, rest = text.partition(cm.START_MARKER)
        _, _, tail = rest.partition(cm.END_MARKER)
        kept = [line for line in (head + tail).split("\r\n") if line]
        self.assertEqual(kept, [line for line in user.split("\r\n") if line])
        self.assertTrue(text.startswith("# CLAUDE.md\r\n") and text.endswith("- keep me\r\n"))
        self.assertNotRegex(text, r"(?<!\r)\n")
        for _ in range(2):
            self.assertEqual(self.run_cli("init")[0], 0)
            self.assertEqual(self.run_cli("update")[0], 0)
            self.assertEqual(self.target.read_bytes(), after_first)

    def test_update_preserves_bytes_outside_markers(self) -> None:
        user = b"# CLAUDE.md\n\nbefore\n\n" + cm.START_MARKER.encode() + b"\nold\n"
        user += cm.END_MARKER.encode() + b"\n\nafter, no trailing newline"
        self.target.write_bytes(user)
        code, _, _ = self.run_cli("update")
        self.assertEqual(code, 0)
        data = self.target.read_bytes()
        self.assertTrue(data.startswith(b"# CLAUDE.md\n\nbefore\n\n" + cm.START_MARKER.encode()))
        self.assertTrue(data.endswith(cm.END_MARKER.encode() + b"\n\nafter, no trailing newline"))
        self.assertNotIn(b"old\n", data)

    def test_update_dry_run_writes_nothing(self) -> None:
        stale = cm.START_MARKER + "\nold\n" + cm.END_MARKER + "\n"
        self.target.write_text(stale)
        code, out, _ = self.run_cli("update", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("-old", out)
        self.assertEqual(self.target.read_text(), stale)

    def test_update_without_file_or_block_fails_with_usage_code(self) -> None:
        code, _, err = self.run_cli("update")
        self.assertEqual(code, 7)
        self.assertIn("claude_md_no_file", err)
        self.target.write_text("# CLAUDE.md\n")
        code, _, err = self.run_cli("update")
        self.assertEqual(code, 2)
        self.assertIn("claude_md_no_block", err)

    def test_broken_markers_refuse_and_leave_the_file_alone(self) -> None:
        broken = cm.START_MARKER + "\nx\n"
        self.target.write_text(broken)
        for command in ("init", "update"):
            code, _, err = self.run_cli(command)
            self.assertEqual(code, 2)
            self.assertIn("claude_md_markers", err)
        self.assertEqual(self.target.read_text(), broken)

    def test_symlink_target_is_refused(self) -> None:
        real = self.root / "real.md"
        real.write_text("# CLAUDE.md\n")
        self.target.symlink_to(real)
        code, _, err = self.run_cli("init")
        self.assertEqual(code, 3)
        self.assertIn("symbolic link", err)
        self.assertEqual(real.read_text(), "# CLAUDE.md\n")

    def test_dir_outside_the_repository_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            code, _, err = self.run_cli("init", "--dir", other)
            self.assertEqual(code, 3)
            self.assertIn("path_escape", err)
            self.assertFalse((Path(other) / "CLAUDE.md").exists())

    def test_dir_option_targets_a_subdirectory(self) -> None:
        sub = self.root / "pkg"
        sub.mkdir()
        code, _, _ = self.run_cli("init", "--dir", "pkg")
        self.assertEqual(code, 0)
        self.assertTrue((sub / "CLAUDE.md").exists())
        self.assertFalse(self.target.exists())


class CheckAndShowTests(ClaudeMdCommandCase):
    def test_check_exit_codes_follow_the_report(self) -> None:
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["exists"])
        self.run_cli("init")
        code, out, _ = self.run_cli("check")
        report = json.loads(out)
        self.assertEqual(code, 2)
        self.assertTrue(report["block_current"])
        self.assertEqual(report["sections_placeholder"], ["architecture", "rules"])

    def test_check_returns_zero_when_everything_is_in_place(self) -> None:
        self.run_cli("init")
        text = self.target.read_text()
        import re

        filled = re.sub(r"<!-- (?!wev-skills)[^>]*-->", "Real content.", text)
        self.target.write_text(filled)
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 0, out)
        self.assertTrue(json.loads(out)["ok"])

    def test_check_with_broken_markers_reports_json(self) -> None:
        self.target.write_text(cm.START_MARKER + "\n")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertTrue(json.loads(out)["marker_error"])

    def test_show_prints_the_block(self) -> None:
        code, out, _ = self.run_cli("show")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), cm.render_block("en"))
        code, out, _ = self.run_cli("show", "--lang", "pt-BR")
        self.assertIn("Pense antes de programar", out)


if __name__ == "__main__":
    unittest.main()
