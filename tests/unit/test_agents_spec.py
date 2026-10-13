from __future__ import annotations

import dataclasses
import json
import unittest

from tests.unit._agent_helpers import data, make
from wev_skills.agents.spec import AgentSpec, LocalText, validate_data
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import AgentLike


class SpecValidationTests(unittest.TestCase):
    def test_minimal_spec_is_valid(self) -> None:
        self.assertEqual(validate_data(data("a")), [])

    def test_unknown_field_is_rejected_with_pointer(self) -> None:
        errors = validate_data(data("a", speciality=["x"]))
        self.assertTrue(any(e.startswith("/speciality") for e in errors), errors)

    def test_nested_unknown_field_is_rejected(self) -> None:
        errors = validate_data(data("a", permissions={"may_mutates": True}))
        self.assertTrue(any("/permissions/may_mutates" in e for e in errors), errors)

    def test_id_must_be_kebab_case_up_to_64_chars(self) -> None:
        for bad in ("Agent", "-a", "a-", "a--b", "a_b", "", "a" * 65, "a b", "../x"):
            with self.subTest(bad=bad):
                self.assertNotEqual(validate_data(data(bad)), [])
        self.assertEqual(validate_data(data("a" * 64)), [])
        self.assertEqual(validate_data(data("a1-b2")), [])

    def test_schema_version_must_be_one(self) -> None:
        self.assertNotEqual(validate_data(data("a", schema_version=2)), [])

    def test_localized_object_requires_english(self) -> None:
        self.assertNotEqual(validate_data(data("a", name={"pt-BR": "x"})), [])
        self.assertEqual(validate_data(data("a", name={"en": "x", "pt-BR": "y"})), [])
        self.assertNotEqual(validate_data(data("a", name={"en": "x", "fr": "y"})), [])

    def test_enums_and_bounds(self) -> None:
        bad = [
            {"model_policy": {"min_tier": "gold"}},
            {"permissions": {"modes": ["auto"]}},
            {"permissions": {"modes": []}},
            {"permissions": {"max_risk": "extreme"}},
            {"escalation": {"on_failure": "panic"}},
            {"max_attempts": 0},
            {"timeout_seconds": 0},
            {"tools": {"allow": ["Read", "Read"]}},
            {"tools": {"allow": ["Read,Write"]}},
        ]
        for extra in bad:
            with self.subTest(extra=extra):
                self.assertNotEqual(validate_data(data("a", **extra)), [])

    def test_cross_field_checks(self) -> None:
        self.assertNotEqual(validate_data(data("a", extends="a")), [])
        self.assertNotEqual(validate_data(data("a", escalation={"to": "a"})), [])
        self.assertNotEqual(
            validate_data(data("a", model_policy={"min_tier": "premium", "max_tier": "economy"})),
            [],
        )

    def test_a_trailing_newline_does_not_pass_a_pattern(self) -> None:
        bad = [
            ("/id", data("abc\n")),
            ("/extends", data("a", extends="base\n")),
            ("/escalation/to", data("a", escalation={"to": "boss\n"})),
            ("/model", data("a", model="premium\n")),
            ("/tools/allow/1", data("a", tools={"allow": ["Grep", "Read\n"]})),
            ("/tools/deny/0", data("a", tools={"deny": ["Bash\n"]})),
            ("/skills/0", data("a", skills=["tdd\n"])),
        ]
        for pointer, doc in bad:
            with self.subTest(pointer=pointer):
                errors = validate_data(doc)
                self.assertTrue(any(e.startswith(f"{pointer}:") for e in errors), errors)
        with self.assertRaises(ValidationError):
            AgentSpec.from_dict(data("abc\n"))

    def test_budget_and_timeout_must_be_finite_and_sane(self) -> None:
        huge = json.loads('{"max_units": 1e999}')
        for budget in (
            huge,
            {"max_units": float("nan")},
            {"max_units": 10**400},
            {"max_units": 1e9},
        ):
            with self.subTest(budget=budget):
                errors = validate_data(data("a", budget=budget))
                self.assertTrue(any(e.startswith("/budget/max_units:") for e in errors), errors)
        for timeout in (float("inf"), float("nan"), 10**400):
            with self.subTest(timeout=timeout):
                errors = validate_data(data("a", timeout_seconds=timeout))
                self.assertTrue(any(e.startswith("/timeout_seconds:") for e in errors), errors)
        self.assertEqual(
            validate_data(data("a", budget={"max_units": 40}, timeout_seconds=3600)), []
        )
        with self.assertRaises(ValidationError):
            AgentSpec.from_dict(data("inf", budget=huge))


class SpecModelTests(unittest.TestCase):
    def test_round_trip_preserves_document(self) -> None:
        doc = data(
            "a",
            description={"en": "d", "pt-BR": "dd"},
            specialties=["s"],
            responsibilities=["plain", {"en": "r", "pt-BR": "rr"}],
            tools={"allow": ["Read"], "deny": ["Write"]},
            permissions={"modes": ["plan"], "max_risk": "low", "may_mutate": False},
            escalation={"on_failure": "escalate", "to": "b"},
            budget={"max_units": 5},
        )
        self.assertEqual(AgentSpec.from_dict(doc).to_dict(), doc)

    def test_from_dict_rejects_invalid_document_with_errors_in_details(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            AgentSpec.from_dict(data("Bad"))
        self.assertIn("/id", ctx.exception.details["errors"][0])

    def test_localized_falls_back_to_english_per_field(self) -> None:
        spec = make(
            "a",
            name={"en": "Name", "pt-BR": "Nome"},
            description="Only english",
            responsibilities=[{"en": "do", "pt-BR": "faça"}, "plain"],
        )
        pt = spec.localized("pt-BR")
        self.assertEqual((pt.name, pt.description), ("Nome", "Only english"))
        self.assertEqual(pt.responsibilities, ("faça", "plain"))
        self.assertEqual(spec.localized("en").name, "Name")

    def test_satisfies_agent_like_port(self) -> None:
        spec = make("a", specialties=["x"])
        self.assertIsInstance(spec, AgentLike)
        self.assertEqual(
            (spec.id, str(spec.description), list(spec.specialties)), ("a", "The a agent.", ["x"])
        )

    def test_spec_is_frozen(self) -> None:
        with self.assertRaises(dataclasses.FrozenInstanceError):
            make("a").id = "b"  # type: ignore[misc]

    def test_local_text_equality_includes_translations(self) -> None:
        self.assertNotEqual(LocalText("x", {"pt-BR": "y"}), LocalText("x"))
        self.assertEqual(LocalText("x"), "x")
        self.assertEqual(
            LocalText.parse({"en": "x", "pt-BR": "y"}).to_json(), {"en": "x", "pt-BR": "y"}
        )


if __name__ == "__main__":
    unittest.main()
