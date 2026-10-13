from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.claude_code import readme_check as rc
from wev_skills.core.errors import WevError

GOOD = "# Title\n\nOne sentence.\n\n## Part\n\nText.\n"


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".git").mkdir()
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)

    def rules(self, text: str) -> list[str]:
        found = rc.check_document(text, "README.md", self.root, self.root)
        return [finding.rule for finding in found]

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TitleTests(RepoCase):
    def test_a_good_document_has_no_findings(self) -> None:
        self.assertEqual([], self.rules(GOOD))

    def test_no_first_level_heading(self) -> None:
        self.assertIn("title_count", self.rules("## Only\n"))

    def test_two_first_level_headings(self) -> None:
        self.assertEqual(["title_count"], self.rules("# One\n\n# Two\n"))

    def test_text_before_the_title(self) -> None:
        found = rc.check_document("Intro\n\n# T\n", "README.md", self.root, self.root)
        self.assertEqual([("title_first", 1)], [(f.rule, f.line) for f in found])

    def test_an_image_block_may_precede_the_title(self) -> None:
        text = (
            '<p align="center">\n  <img src="https://x.org/a.png">\n</p>\n\n'
            "![l](https://x.org/l.png)\n\n# T\n"
        )
        self.assertEqual([], self.rules(text))

    def test_hash_lines_in_code_do_not_count(self) -> None:
        self.assertEqual([], self.rules("# T\n\n```sh\n# comment\n```\n"))


class ForbiddenSectionTests(RepoCase):
    def test_english_and_portuguese_names(self) -> None:
        for name in (
            "License",
            "Licence",
            "Contributing",
            "Changelog",
            "Code of Conduct",
            "Security",
        ):
            with self.subTest(name=name):
                self.assertIn("forbidden_section", self.rules(f"# T\n\n## {name}\n"))
        for name in (
            "Licença",
            "Contribuindo",
            "Como contribuir",
            "Registro de alterações",
            "Código de conduta",
            "Segurança",
        ):
            with self.subTest(name=name):
                self.assertIn("forbidden_section", self.rules(f"# T\n\n### {name}\n"))

    def test_a_link_to_the_file_inside_another_section_is_fine(self) -> None:
        self.write("LICENSE", "MIT")
        self.assertEqual([], self.rules("# T\n\n## Project files\n\nSee [LICENSE](LICENSE).\n"))

    def test_a_longer_heading_is_not_forbidden(self) -> None:
        self.assertEqual([], self.rules("# T\n\n## License checks of the engine\n"))


class EmojiTests(RepoCase):
    def test_unicode_emoji(self) -> None:
        for char in ("\U0001f680", "✅", "⚠️", "⭐"):
            with self.subTest(char=char):
                self.assertIn("emoji", self.rules(f"# T\n\nGo {char}\n"))

    def test_shortcode(self) -> None:
        self.assertIn("emoji", self.rules("# T\n\nDone :rocket: now\n"))
        self.assertIn("emoji", self.rules("# T\n\nDone :+1: now\n"))

    def test_arrows_times_and_ports_are_not_emoji(self) -> None:
        text = "# T\n\nA → B at 12:30:45 on host:8080:ok and http://h:80/p\n"
        self.assertEqual([], self.rules(text))

    def test_shortcode_inside_code_is_ignored(self) -> None:
        self.assertEqual([], self.rules("# T\n\n`:rocket:`\n\n```text\n:rocket:\n```\n"))


class LinkTests(RepoCase):
    def test_existing_and_missing_targets(self) -> None:
        self.write("docs/a.md", "x")
        ok = "# T\n\n[a](docs/a.md#part) ![i](docs/a.md)\n"
        self.assertEqual([], self.rules(ok))
        found = rc.check_document("# T\n\n\n[a](docs/none.md)\n", "README.md", self.root, self.root)
        self.assertEqual([("link_missing", 4)], [(f.rule, f.line) for f in found])

    def test_external_anchor_and_mailto_are_skipped(self) -> None:
        text = "# T\n\n[a](https://x.org) [b](#t) [c](mailto:a@b.org) [d](//x.org/y)\n"
        self.assertEqual([], self.rules(text))

    def test_reference_definitions_and_html_images(self) -> None:
        text = '# T\n\n[a][1]\n\n[1]: nowhere.md\n\n<img src="gone.png" alt="x">\n'
        self.assertEqual(["link_missing", "link_missing"], self.rules(text))

    def test_links_in_code_are_ignored(self) -> None:
        self.assertEqual([], self.rules("# T\n\n`[a](no.md)`\n\n```md\n[a](no.md)\n```\n"))

    def test_parent_traversal_is_refused_even_when_the_target_exists(self) -> None:
        outside = self.root.parent / "outside-readme-test.md"
        outside.write_text("x")
        self.addCleanup(outside.unlink)
        self.assertEqual(
            ["link_outside_root"], self.rules("# T\n\n[a](../outside-readme-test.md)\n")
        )
        self.assertEqual(["link_outside_root"], self.rules("# T\n\n[a](../../outside)\n"))

    def test_absolute_paths_are_refused(self) -> None:
        self.assertEqual(["link_outside_root"], self.rules("# T\n\n[a](/etc/passwd)\n"))
        self.assertEqual(["link_outside_root"], self.rules(f"# T\n\n[a]({self.root}/x)\n"))

    def test_a_symlink_pointing_outside_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "secret.md").write_text("x")
            (self.root / "link.md").symlink_to(Path(other) / "secret.md")
            (self.root / "dir").symlink_to(other)
            self.assertEqual(["link_outside_root"], self.rules("# T\n\n[a](link.md)\n"))
            self.assertEqual(["link_outside_root"], self.rules("# T\n\n[a](dir/secret.md)\n"))

    def test_a_symlink_inside_the_root_is_fine(self) -> None:
        self.write("real.md", "x")
        (self.root / "alias.md").symlink_to(self.root / "real.md")
        self.assertEqual([], self.rules("# T\n\n[a](alias.md)\n"))

    def test_odd_targets_never_raise(self) -> None:
        text = "# T\n\n[a](%00x) [b](a%2F..%2F..%2Fx) [c](" + "a/" * 3000 + "x)\n"
        self.assertTrue(set(self.rules(text)) <= {"link_missing", "link_outside_root"})

    def test_links_resolve_from_the_readme_directory(self) -> None:
        self.write("docs/a.md", "x")
        self.write("docs/b.md", "x")
        found = rc.check_document(
            "# T\n\n[a](b.md) [c](a.md)\n", "docs/x.md", self.root, self.root / "docs"
        )
        self.assertEqual((), found)


class AdmonitionTests(RepoCase):
    def test_the_five_kinds_are_valid(self) -> None:
        for kind in ("NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"):
            with self.subTest(kind=kind):
                self.assertEqual([], self.rules(f"# T\n\n> [!{kind}]\n> Text.\n"))

    def test_an_unknown_kind(self) -> None:
        self.assertEqual(["admonition_kind"], self.rules("# T\n\n> [!INFO]\n> Text.\n"))

    def test_bad_syntax(self) -> None:
        for body in (
            "> [!note]\n> Text.\n",
            "> [!NOTE] inline text\n> Text.\n",
            "> [! NOTE]\n> Text.\n",
            "> Text first\n> [!NOTE]\n> more\n",
            "> [!NOTE]\n\nParagraph outside.\n",
            ">[!NOTE]\n> Text.\n",
        ):
            with self.subTest(body=body):
                self.assertEqual(["admonition_syntax"], self.rules(f"# T\n\n{body}"))

    def test_code_is_ignored(self) -> None:
        self.assertEqual([], self.rules("# T\n\n```md\n> [!INFO]\n```\n"))


class FenceTests(RepoCase):
    def test_unclosed_fence(self) -> None:
        found = rc.check_document("# T\n\n```sh\nls\n", "README.md", self.root, self.root)
        self.assertEqual([("fence_unclosed", 3)], [(f.rule, f.line) for f in found])

    def test_missing_language(self) -> None:
        found = rc.check_document("# T\n\n```\nls\n```\n", "README.md", self.root, self.root)
        self.assertEqual([("fence_language", 3)], [(f.rule, f.line) for f in found])

    def test_tilde_and_longer_fences(self) -> None:
        self.assertEqual([], self.rules("# T\n\n````md\n```\n````\n\n~~~sh\nls\n~~~\n"))

    def test_a_shorter_closing_fence_does_not_close(self) -> None:
        self.assertIn("fence_unclosed", self.rules("# T\n\n````md\n```\n"))


class PlaceholderTests(RepoCase):
    def test_each_placeholder(self) -> None:
        for text in (
            "TODO write this",
            "to be decided: TBD",
            "Lorem ipsum dolor",
            "clone your-org/repo",
            "https://github.com/your-username/x",
            "git clone https://example.com/team/repo.git",
        ):
            with self.subTest(text=text):
                self.assertIn("placeholder", self.rules(f"# T\n\n{text}\n"))

    def test_words_that_merely_contain_the_letters(self) -> None:
        self.assertEqual([], self.rules("# T\n\nThe todos and the tbdx tables.\n"))


class LengthTests(RepoCase):
    def test_warning_above_the_threshold(self) -> None:
        long_text = "# T\n" + "line\n" * rc.MAX_RECOMMENDED_LINES
        self.assertEqual(
            ["readme_long"], [f.rule for f in rc.length_warnings(long_text, "README.md")]
        )
        self.assertEqual((), rc.length_warnings(GOOD, "README.md"))


class TwinTests(RepoCase):
    EN = (
        "# T\n\nPortuguese version: [README.pt-BR.md](README.pt-BR.md).\n\n## A\n\n```sh\nls\n```\n"
    )
    PT = "# T\n\nVersão em inglês: [README.md](README.md).\n\n## A\n\n```sh\nls\n```\n"

    def twins(self, en: str, pt: str) -> list[str]:
        return [f.rule for f in rc.check_twins(en, pt, ("README.md", "README.pt-BR.md"))]

    def test_matching_twins(self) -> None:
        self.assertEqual([], self.twins(self.EN, self.PT))

    def test_heading_counts(self) -> None:
        self.assertEqual(["twin_headings"], self.twins(self.EN + "\n## B\n", self.PT))

    def test_cross_link_in_the_first_lines(self) -> None:
        self.assertIn(
            "twin_link", self.twins(self.EN, self.PT.replace("[README.md](README.md)", "x"))
        )
        late = "# T\n" + "\n" * 30 + "[README.md](README.md)\n\n## A\n\n```sh\nls\n```\n"
        self.assertIn("twin_link", self.twins(self.EN, late))

    def test_code_blocks_must_match(self) -> None:
        self.assertEqual(["twin_code"], self.twins(self.EN, self.PT.replace("ls", "ls -l")))
        self.assertEqual(
            ["twin_code"], self.twins(self.EN, self.PT.replace("```sh\nls\n```\n", ""))
        )


class CreditsTests(RepoCase):
    def test_credits_must_be_the_last_second_level_heading(self) -> None:
        ok = "# T\n\n## A\n\n## Credits\n\nx\n"
        self.assertEqual([], [f.rule for f in rc.check_credits(ok, "README.md")])
        bad = "# T\n\n## Credits\n\n## After\n"
        found = rc.check_credits(bad, "README.md")
        self.assertEqual([("credits_last", 3)], [(f.rule, f.line) for f in found])

    def test_portuguese_heading(self) -> None:
        self.assertEqual((), rc.check_credits("# T\n\n## A\n\n## Créditos\n", "README.pt-BR.md"))

    def test_a_demanded_but_missing_heading(self) -> None:
        found = rc.check_credits("# T\n\n## A\n", "README.md", required=True)
        self.assertEqual(["credits_missing"], [f.rule for f in found])
        self.assertEqual((), rc.check_credits("# T\n\n## A\n", "README.md"))


class LogoTests(RepoCase):
    def test_nothing_is_said_without_a_logo(self) -> None:
        self.write("README.md", GOOD)
        report = rc.check_directory(self.root, self.root, twin=False, credits_last=False)
        self.assertIsNone(report.logo)
        self.assertEqual([], list(report.findings))

    def test_a_logo_outside_the_header_is_reported(self) -> None:
        self.write("README.md", GOOD)
        self.write("assets/logo.svg", "<svg/>")
        report = rc.check_directory(self.root, self.root, twin=False, credits_last=False)
        self.assertEqual("assets/logo.svg", report.logo["path"] if report.logo else None)
        self.assertEqual(["logo_unused"], [f.rule for f in report.findings])

    def test_a_logo_in_the_header_is_accepted(self) -> None:
        self.write(
            "README.md",
            '<p align="center"><img src="assets/logo.svg" alt="logo"></p>\n\n# T\n\n## A\n',
        )
        self.write("assets/logo.svg", "<svg/>")
        report = rc.check_directory(self.root, self.root, twin=False, credits_last=False)
        self.assertEqual([], list(report.findings))
        self.assertTrue(report.logo and report.logo["used"])

    def test_an_image_below_the_first_section_does_not_count(self) -> None:
        self.write("README.md", "# T\n\n## A\n\n![l](icon.png)\n")
        self.write("icon.png", "x")
        report = rc.check_directory(self.root, self.root, twin=False, credits_last=False)
        self.assertEqual(["logo_unused"], [f.rule for f in report.findings])


class DirectoryTests(RepoCase):
    def test_missing_readme(self) -> None:
        report = rc.check_directory(self.root, self.root)
        self.assertEqual(["readme_missing"], [f.rule for f in report.findings])
        self.assertFalse(report.ok)

    def test_twin_is_expected_when_the_portuguese_file_exists(self) -> None:
        self.write("README.md", "# T\n\nSee [README.pt-BR.md](README.pt-BR.md).\n\n## A\n")
        self.write("README.pt-BR.md", "# T\n\nVeja [README.md](README.md).\n\n## A\n\n## B\n")
        report = rc.check_directory(self.root, self.root)
        self.assertEqual(["twin_headings"], [f.rule for f in report.findings])
        self.assertEqual(["README.md", "README.pt-BR.md"], list(report.files))
        self.assertTrue(rc.check_directory(self.root, self.root, twin=False).ok)

    def test_a_required_twin_that_is_absent_is_a_finding(self) -> None:
        self.write("README.md", GOOD)
        report = rc.check_directory(self.root, self.root, twin=True)
        self.assertEqual(["twin_missing"], [f.rule for f in report.findings])

    def test_credits_are_checked_when_the_heading_exists(self) -> None:
        self.write("README.md", "# T\n\n## Credits\n\n## After\n")
        self.assertEqual(
            ["credits_last"], [f.rule for f in rc.check_directory(self.root, self.root).findings]
        )
        self.assertTrue(rc.check_directory(self.root, self.root, credits_last=False).ok)

    def test_credits_demanded_but_absent(self) -> None:
        self.write("README.md", GOOD)
        report = rc.check_directory(self.root, self.root, credits_last=True)
        self.assertEqual(["credits_missing"], [f.rule for f in report.findings])

    def test_findings_are_sorted_localized_and_serializable(self) -> None:
        self.write("README.md", "# T\n\n## License\n\n\U0001f680\n")
        report = rc.check_directory(self.root, self.root)
        data = report.to_dict()
        self.assertFalse(data["ok"])
        self.assertEqual(["forbidden_section", "emoji"], [f["rule"] for f in data["findings"]])
        self.assertNotIn("readme.finding", data["findings"][0]["message"])
        with i18n.use_language("pt-BR"):
            self.assertIn("seção", rc.check_directory(self.root, self.root).findings[0].message)

    def test_a_symlinked_readme_outside_the_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "README.md").write_text(GOOD)
            (self.root / "README.md").symlink_to(Path(other) / "README.md")
            with self.assertRaises(WevError):
                rc.check_directory(self.root, self.root)

    def test_bad_encoding_is_an_error(self) -> None:
        (self.root / "README.md").write_bytes(b"# T\n\xff\xfe\n")
        with self.assertRaises(rc.ReadmeError):
            rc.check_directory(self.root, self.root)

    def test_the_checker_never_writes(self) -> None:
        self.write("README.md", "# T\n\n## License\n")
        before = sorted(os.listdir(self.root))
        stamp = (self.root / "README.md").stat().st_mtime_ns
        rc.check_directory(self.root, self.root)
        self.assertEqual(before, sorted(os.listdir(self.root)))
        self.assertEqual(stamp, (self.root / "README.md").stat().st_mtime_ns)

    def test_the_directory_must_stay_inside_the_root(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(Exception) as caught:
                rc.resolve_directory(self.root, Path(other))
            self.assertEqual("path_escape", getattr(caught.exception, "code", ""))


if __name__ == "__main__":
    unittest.main()
