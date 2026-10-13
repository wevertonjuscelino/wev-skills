from __future__ import annotations

import unittest

from wev_skills.config import RemoteConfig, RemoteHost
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.remote.inventory import Inventory, is_production, validate_alias

VALID = ("staging-1", "db.internal", "host_2", "A1", "1host", ".hidden", "a")
INVALID = (
    "",
    "-oProxyCommand=evil",
    "-",
    "user@host",
    "host:22",
    "a/b",
    "a b",
    "a\tb",
    "host\n",
    "host;id",
    "host$(id)",
    "host`id`",
    "host|id",
    "host&",
    "ho'st",
    'ho"st',
    "host\\",
    "h*",
    "héost",
    "a" * 254,
)


class ValidateAliasTests(unittest.TestCase):
    def test_accepts_plain_host_names(self) -> None:
        for alias in VALID:
            with self.subTest(alias=alias):
                self.assertEqual(validate_alias(alias), alias)

    def test_rejects_anything_ssh_or_a_shell_could_reinterpret(self) -> None:
        for alias in INVALID:
            with self.subTest(alias=alias), self.assertRaises(ValidationError) as ctx:
                validate_alias(alias)
            self.assertEqual(ctx.exception.code, "remote_invalid_alias")

    def test_rejects_non_strings(self) -> None:
        for alias in (None, 5, ["a"], b"host"):
            with self.subTest(alias=alias), self.assertRaises(ValidationError):
                validate_alias(alias)


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.staging = RemoteHost("staging-1", "staging", True)
        self.prod = RemoteHost("prod-1", "production")
        self.inventory = Inventory((self.staging, self.prod))

    def test_get_returns_the_listed_host(self) -> None:
        self.assertIs(self.inventory.get("staging-1"), self.staging)
        self.assertEqual(self.inventory.aliases(), ("staging-1", "prod-1"))
        self.assertEqual(self.inventory.hosts(), (self.staging, self.prod))

    def test_unlisted_alias_is_refused_not_guessed(self) -> None:
        for alias in ("staging-2", "STAGING-1", "staging-1 ", "", "-oProxyCommand=x", None):
            with self.subTest(alias=alias), self.assertRaises(PermissionDenied) as ctx:
                self.inventory.get(alias)  # type: ignore[arg-type]
            self.assertEqual(ctx.exception.code, "remote_host_not_listed")

    def test_errors_show_the_alias_without_literal_quotes(self) -> None:
        with self.assertRaises(PermissionDenied) as unlisted:
            self.inventory.get("staging-2")
        self.assertEqual(unlisted.exception.details["alias"], "staging-2")
        with self.assertRaises(ValidationError) as invalid:
            validate_alias("bad alias\n")
        self.assertEqual(invalid.exception.details["alias"], "bad alias\\n")
        with self.assertRaises(PermissionDenied) as wrong_type:
            self.inventory.get(None)  # type: ignore[arg-type]
        self.assertEqual(wrong_type.exception.details["alias"], "<NoneType>")
        with self.assertRaises(ValidationError) as long:
            validate_alias("a" * 500)
        self.assertEqual(len(long.exception.details["alias"]), 80)

    def test_empty_inventory_refuses_everything(self) -> None:
        with self.assertRaises(PermissionDenied):
            Inventory(()).get("staging-1")

    def test_invalid_configured_alias_is_rejected_at_construction(self) -> None:
        for alias in ("-bad", "user@host", "a b"):
            with self.subTest(alias=alias), self.assertRaises(ValidationError):
                Inventory((RemoteHost(alias),))

    def test_duplicate_alias_is_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            Inventory((RemoteHost("a"), RemoteHost("a", "production")))
        self.assertEqual(ctx.exception.code, "remote_duplicate_alias")

    def test_from_config(self) -> None:
        inventory = Inventory.from_config(RemoteConfig((self.staging,)))
        self.assertEqual(inventory.aliases(), ("staging-1",))

    def test_production_label_is_case_insensitive(self) -> None:
        self.assertTrue(is_production(self.prod))
        self.assertTrue(is_production(RemoteHost("p", " Production ")))
        self.assertTrue(is_production(RemoteHost("p", "prod")))
        self.assertFalse(is_production(self.staging))
        self.assertFalse(is_production(RemoteHost("p")))


if __name__ == "__main__":
    unittest.main()
