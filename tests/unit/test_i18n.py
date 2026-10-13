from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills import i18n
from wev_skills.core.errors import ValidationError

_FILE_RE = re.compile(r"^(?P<domain>.+)\.(?P<lang>en|pt-BR)\.json$")


class ResolveLanguageTests(unittest.TestCase):
    def env(self, **values: str):  # type: ignore[no-untyped-def]
        return mock.patch.dict(os.environ, values, clear=True)

    def test_default_is_english(self) -> None:
        with self.env():
            self.assertEqual(i18n.resolve_language(), "en")

    def test_lang_env_starting_with_pt(self) -> None:
        with self.env(LANG="pt_BR.UTF-8"):
            self.assertEqual(i18n.resolve_language(), "pt-BR")
        with self.env(LANG="en_US.UTF-8"):
            self.assertEqual(i18n.resolve_language(), "en")

    def test_wev_lang_beats_lang(self) -> None:
        with self.env(WEV_LANG="en", LANG="pt_BR.UTF-8"):
            self.assertEqual(i18n.resolve_language(), "en")
        with self.env(WEV_LANG="pt-BR", LANG="en_US"):
            self.assertEqual(i18n.resolve_language(), "pt-BR")

    def test_explicit_beats_env(self) -> None:
        with self.env(WEV_LANG="pt-BR"):
            self.assertEqual(i18n.resolve_language("en"), "en")

    def test_use_language_block_beats_env_but_not_explicit(self) -> None:
        with self.env(WEV_LANG="en"), i18n.use_language("pt-BR"):
            self.assertEqual(i18n.resolve_language(), "pt-BR")
            self.assertEqual(i18n.resolve_language("en"), "en")
        with self.env():
            self.assertEqual(i18n.resolve_language(), "en")

    def test_unsupported_language_raises(self) -> None:
        with self.assertRaises(ValidationError):
            i18n.resolve_language("fr")


class TranslateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "a.en.json").write_text(json.dumps({"x": "A {n}", "only_en": "english"}))
        (root / "a.pt-BR.json").write_text(json.dumps({"x": "A-pt {n}"}))
        (root / "b.en.json").write_text(json.dumps({"y": "from b"}))
        patcher = mock.patch.object(i18n, "LOCALES_DIR", root)
        patcher.start()
        self.addCleanup(patcher.stop)
        i18n.clear_cache()
        self.addCleanup(i18n.clear_cache)

    def test_translates_with_params(self) -> None:
        self.assertEqual(i18n.t("x", "en", n=3), "A 3")
        self.assertEqual(i18n.t("x", "pt-BR", n=3), "A-pt 3")

    def test_domains_are_merged(self) -> None:
        self.assertEqual(i18n.t("y", "en"), "from b")

    def test_missing_in_pt_falls_back_to_en(self) -> None:
        self.assertEqual(i18n.t("only_en", "pt-BR"), "english")
        self.assertEqual(i18n.t("y", "pt-BR"), "from b")

    def test_missing_everywhere_returns_key(self) -> None:
        self.assertEqual(i18n.t("no.such.key", "pt-BR"), "no.such.key")

    def test_missing_param_does_not_raise(self) -> None:
        self.assertEqual(i18n.t("x", "en"), "A {n}")


class ShippedCatalogTests(unittest.TestCase):
    def test_en_and_pt_br_have_identical_keys_for_every_domain(self) -> None:
        domains: dict[str, dict[str, set[str]]] = {}
        for path in i18n.LOCALES_DIR.glob("*.json"):
            match = _FILE_RE.match(path.name)
            self.assertIsNotNone(match, f"bad catalog file name: {path.name}")
            assert match is not None
            keys = set(json.loads(path.read_text(encoding="utf-8")))
            domains.setdefault(match["domain"], {})[match["lang"]] = keys
        self.assertIn("core", domains)
        for domain, langs in domains.items():
            self.assertEqual(set(langs), {"en", "pt-BR"}, f"{domain}: missing a language file")
            self.assertEqual(langs["en"], langs["pt-BR"], f"{domain}: key sets differ")

    def test_placeholders_match_between_languages(self) -> None:
        en = json.loads((i18n.LOCALES_DIR / "core.en.json").read_text(encoding="utf-8"))
        pt = json.loads((i18n.LOCALES_DIR / "core.pt-BR.json").read_text(encoding="utf-8"))
        for key, text in en.items():
            self.assertEqual(
                sorted(re.findall(r"\{\w+\}", text)), sorted(re.findall(r"\{\w+\}", pt[key])), key
            )

    def test_real_catalog_translates(self) -> None:
        self.assertIn("versão", i18n.t("meta.version.help", "pt-BR"))
        self.assertIn("version", i18n.t("meta.version.help", "en"))


if __name__ == "__main__":
    unittest.main()
