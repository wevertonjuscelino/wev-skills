"""The ``language`` key of a configuration file takes part in language resolution.

Order: ``--lang``, ``WEV_LANG``, ``language`` set explicitly in a config file (or pinned by
the run), ``LANG`` starting with ``pt``, English.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from wev_skills import cli, i18n
from wev_skills.adapters.claude_code import hooks
from wev_skills.config import SOURCE_DEFAULTS, explicit_language

PT_BRIEF = "Objetivo: Do it"
EN_BRIEF = "Objective: Do it"


class ResolveOrderTests(unittest.TestCase):
    def env(self, **values: str) -> Any:
        return mock.patch.dict(os.environ, values, clear=True)

    def test_config_language_beats_lang_but_not_wev_lang(self) -> None:
        with self.env(LANG="en_US"), i18n.use_config_language("pt-BR"):
            self.assertEqual(i18n.resolve_language(), "pt-BR")
        with self.env(LANG="pt_BR"), i18n.use_config_language("en"):
            self.assertEqual(i18n.resolve_language(), "en")
        with self.env(WEV_LANG="en"), i18n.use_config_language("pt-BR"):
            self.assertEqual(i18n.resolve_language(), "en")

    def test_flag_and_explicit_argument_beat_the_config(self) -> None:
        with self.env(), i18n.use_config_language("pt-BR"):
            with i18n.use_language("en"):
                self.assertEqual(i18n.resolve_language(), "en")
            self.assertEqual(i18n.resolve_language("en"), "en")

    def test_without_a_config_language_the_old_order_holds(self) -> None:
        with self.env(LANG="pt_BR"), i18n.use_config_language(None):
            self.assertEqual(i18n.resolve_language(), "pt-BR")


class ExplicitLanguageTests(unittest.TestCase):
    def test_only_a_file_that_sets_the_key_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            setting, silent = Path(tmp, "a.json"), Path(tmp, "b.json")
            setting.write_text('{"language": "pt-BR"}', encoding="utf-8")
            silent.write_text("{}", encoding="utf-8")
            self.assertEqual(explicit_language(str(setting)), "pt-BR")
            self.assertIsNone(explicit_language(str(silent)))
            self.assertIsNone(explicit_language(str(Path(tmp, "missing.json"))))
        self.assertIsNone(explicit_language(SOURCE_DEFAULTS))


class CliLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve() / "repo"
        (self.work / ".git").mkdir(parents=True)
        (self.work / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in ("WEV_LANG", "LANG"):
            os.environ.pop(name, None)

    def config(self, **fields: Any) -> None:
        (self.work / "wev.config.json").write_text(json.dumps(fields), encoding="utf-8")

    def wev(self, *argv: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def start(self) -> None:
        code, _ = self.wev("run", "start", "--objective", "Do it", "--files", "1")
        self.assertEqual(code, 0)

    def brief(self, *argv: str) -> str:
        code, text = self.wev(*argv, "run", "brief")
        self.assertEqual(code, 0)
        return text

    def test_the_repository_config_language_is_used(self) -> None:
        self.config(language="pt-BR")
        self.start()
        self.assertIn(PT_BRIEF, self.brief())

    def test_flag_beats_config(self) -> None:
        self.config(language="pt-BR")
        self.start()
        self.assertIn(EN_BRIEF, self.brief("--lang", "en"))

    def test_wev_lang_beats_config(self) -> None:
        self.config(language="pt-BR")
        self.start()
        os.environ["WEV_LANG"] = "en"
        self.assertIn(EN_BRIEF, self.brief())

    def test_config_beats_lang_even_when_it_says_english(self) -> None:
        self.config(language="en")
        self.start()
        os.environ["LANG"] = "pt_BR.UTF-8"
        self.assertIn(EN_BRIEF, self.brief())

    def test_the_built_in_default_does_not_beat_lang(self) -> None:
        self.config(limits={"max_attempts": 4})
        self.start()
        os.environ["LANG"] = "pt_BR.UTF-8"
        self.assertIn(PT_BRIEF, self.brief())

    def test_error_messages_use_the_config_language_before_a_run(self) -> None:
        self.config(language="pt-BR")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(["run", "status"])
        self.assertIn("execução", json.loads(err.getvalue())["error"]["message"])

    def test_a_run_keeps_the_language_it_pinned(self) -> None:
        self.config(language="pt-BR")
        self.start()
        self.config(language="en")
        self.assertIn(PT_BRIEF, self.brief())

    def test_the_report_follows_the_pinned_language(self) -> None:
        self.config(language="pt-BR")
        self.start()
        self.config(language="en")
        _, text = self.wev("run", "report", "--format", "md")
        self.assertIn("Objetivo", text)

    def test_hook_output_follows_the_pinned_language(self) -> None:
        self.config(language="pt-BR")
        self.start()
        self.config(language="en")
        output = hooks.session_context({"cwd": str(self.work)})
        self.assertIn("este é o estado registrado", output)
        self.assertIn(PT_BRIEF, output)


if __name__ == "__main__":
    unittest.main()
