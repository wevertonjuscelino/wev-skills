from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from wev_skills import cli, i18n

GOOD_EN = "# T\n\nPortuguese version: [README.pt-BR.md](README.pt-BR.md).\n\n## A\n\n## Credits\n"
GOOD_PT = "# T\n\nVersão em inglês: [README.md](README.md).\n\n## A\n\n## Créditos\n"


class ReadmeCommandCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".git").mkdir()
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)

    def run_cli(self, *argv: str, lang: str = "en") -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            i18n.use_language(lang),
        ):
            code = cli.main(["--lang", lang, "readme", *argv])
        return code, out.getvalue(), err.getvalue()

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class CheckTests(ReadmeCommandCase):
    def test_clean_pair_exits_zero_with_a_json_report(self) -> None:
        self.write("README.md", GOOD_EN)
        self.write("README.pt-BR.md", GOOD_PT)
        code, out, _ = self.run_cli("check")
        report = json.loads(out)
        self.assertEqual(code, 0, out)
        self.assertTrue(report["ok"])
        self.assertTrue(report["twin_checked"])
        self.assertEqual(report["files"], ["README.md", "README.pt-BR.md"])

    def test_findings_exit_two_and_carry_rule_line_and_message(self) -> None:
        self.write("README.md", "# T\n\n## License\n")
        code, out, _ = self.run_cli("check")
        report = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(report["findings"][0]["rule"], "forbidden_section")
        self.assertEqual(report["findings"][0]["line"], 3)
        self.assertIn("dedicated file", report["findings"][0]["message"])

    def test_messages_follow_the_language(self) -> None:
        self.write("README.md", "# T\n\n## License\n")
        _, out, _ = self.run_cli("check", lang="pt-BR")
        self.assertIn("arquivo próprio", json.loads(out)["findings"][0]["message"])

    def test_missing_readme_is_a_finding(self) -> None:
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["findings"][0]["rule"], "readme_missing")

    def test_no_twin_skips_the_comparison(self) -> None:
        self.write("README.md", GOOD_EN)
        self.write("README.pt-BR.md", GOOD_PT + "\n## Extra\n")
        self.assertEqual(self.run_cli("check")[0], 2)
        code, out, _ = self.run_cli("check", "--no-twin")
        self.assertEqual(code, 2, "the Portuguese file still breaks the credits rule")
        self.assertFalse(json.loads(out)["twin_checked"])

    def test_credits_flags(self) -> None:
        self.write("README.md", "# T\n\n## A\n")
        self.assertEqual(self.run_cli("check")[0], 0)
        code, out, _ = self.run_cli("check", "--credits-last")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["findings"][0]["rule"], "credits_missing")
        self.write("README.md", "# T\n\n## Credits\n\n## After\n")
        self.assertEqual(self.run_cli("check")[0], 2)
        self.assertEqual(self.run_cli("check", "--no-credits-last")[0], 0)

    def test_dir_option_targets_a_subdirectory(self) -> None:
        self.write(
            "pkg/README.md",
            GOOD_EN.replace("Portuguese version: [README.pt-BR.md](README.pt-BR.md).", ""),
        )
        code, _, _ = self.run_cli("check", "--dir", "pkg")
        self.assertEqual(code, 0)

    def test_dir_outside_the_repository_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            code, _, err = self.run_cli("check", "--dir", other)
            self.assertEqual(code, 3)
            self.assertIn("path_escape", err)

    def test_missing_dir(self) -> None:
        code, _, err = self.run_cli("check", "--dir", "nowhere")
        self.assertEqual(code, 7)
        self.assertIn("readme_no_dir", err)

    def test_the_command_writes_nothing(self) -> None:
        self.write("README.md", "# T\n\n## License\n")
        before = sorted(p.name for p in self.root.iterdir())
        self.run_cli("check")
        self.assertEqual(before, sorted(p.name for p in self.root.iterdir()))


if __name__ == "__main__":
    unittest.main()
