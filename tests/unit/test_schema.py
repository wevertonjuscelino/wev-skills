from __future__ import annotations

import unittest
from typing import Any

from wev_skills import schema
from wev_skills.core.errors import NotFound, ValidationError


class SchemaKeywordTests(unittest.TestCase):
    def ok(self, instance: Any, sch: dict[str, Any]) -> None:
        self.assertEqual(schema.validate(instance, sch), [])

    def bad(self, instance: Any, sch: dict[str, Any], prefix: str) -> list[str]:
        errs = schema.validate(instance, sch)
        self.assertTrue(errs, f"expected errors for {instance!r}")
        self.assertTrue(errs[0].startswith(prefix), errs)
        return errs

    def test_type(self) -> None:
        cases = {
            "string": ("a", 1),
            "integer": (1, 1.5),
            "number": (1.5, "1"),
            "boolean": (True, 0),
            "array": ([], {}),
            "object": ({}, []),
            "null": (None, 0),
        }
        for name, (good, wrong) in cases.items():
            with self.subTest(type=name):
                self.ok(good, {"type": name})
                self.bad(wrong, {"type": name}, "/")

    def test_bool_is_not_integer_or_number(self) -> None:
        self.bad(True, {"type": "integer"}, "/")
        self.bad(True, {"type": "number"}, "/")

    def test_type_list(self) -> None:
        self.ok(None, {"type": ["string", "null"]})
        self.bad(3, {"type": ["string", "null"]}, "/")

    def test_enum_and_const(self) -> None:
        self.ok("a", {"enum": ["a", "b"]})
        self.bad("c", {"enum": ["a", "b"]}, "/")
        self.bad(1, {"enum": [True]}, "/")
        self.ok(5, {"const": 5})
        self.bad(6, {"const": 5}, "/")

    def test_required_and_properties(self) -> None:
        sch = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
        self.ok({"a": 1}, sch)
        self.bad({}, sch, "/: missing required property 'a'")
        self.bad({"a": "x"}, sch, "/a")

    def test_additional_properties_false_and_schema(self) -> None:
        self.ok({"a": 1, "z": 1}, {"properties": {"a": {}}})
        self.bad({"z": 1}, {"properties": {"a": {}}, "additionalProperties": False}, "/z")
        sch = {"additionalProperties": {"type": "integer"}}
        self.ok({"x": 1}, sch)
        self.bad({"x": "s"}, sch, "/x")

    def test_items_with_nested_json_pointer(self) -> None:
        xs = {"type": "array", "items": {"type": "integer"}}
        sch = {"type": "object", "properties": {"xs": xs}}
        errs = self.bad({"xs": [1, "a"]}, sch, "/xs/1")
        self.assertEqual(len(errs), 1)

    def test_pointer_escapes_special_characters(self) -> None:
        sch = {"additionalProperties": False}
        self.bad({"a/b~c": 1}, sch, "/a~1b~0c")

    def test_min_max_items(self) -> None:
        sch = {"minItems": 1, "maxItems": 2}
        self.ok([1], sch)
        self.bad([], sch, "/")
        self.bad([1, 2, 3], sch, "/")

    def test_unique_items(self) -> None:
        self.ok([1, 2], {"uniqueItems": True})
        self.bad([1, 1], {"uniqueItems": True}, "/1")
        self.ok([1, True], {"uniqueItems": True})
        self.bad([{"a": [1]}, {"a": [1]}], {"uniqueItems": True}, "/1")

    def test_string_length_and_pattern(self) -> None:
        self.ok("abc", {"minLength": 2, "maxLength": 3, "pattern": "^a"})
        self.bad("a", {"minLength": 2}, "/")
        self.bad("abcd", {"maxLength": 3}, "/")
        self.bad("xbc", {"pattern": "^a"}, "/")

    def test_minimum_maximum_are_inclusive(self) -> None:
        sch = {"minimum": 1, "maximum": 3}
        self.ok(1, sch)
        self.ok(3, sch)
        self.bad(0, sch, "/")
        self.bad(3.5, sch, "/")

    def test_ref_into_defs(self) -> None:
        sch = {"$defs": {"n": {"type": "integer"}}, "properties": {"a": {"$ref": "#/$defs/n"}}}
        self.ok({"a": 1}, sch)
        self.bad({"a": "x"}, sch, "/a")

    def test_bad_refs_raise(self) -> None:
        for ref in ("#/definitions/x", "http://x/y", "#/$defs/missing"):
            with self.subTest(ref=ref), self.assertRaises(ValidationError):
                schema.validate(1, {"$ref": ref, "$defs": {}})

    def test_annotation_keywords_are_ignored(self) -> None:
        annotated = {"$schema": "x", "title": "t", "description": "d", "default": 1}
        self.ok(1, {**annotated, "type": "integer"})

    def test_unsupported_keyword_raises_instead_of_being_ignored(self) -> None:
        for keyword in ("oneOf", "format", "multipleOf", "patternProperties"):
            with self.subTest(keyword=keyword), self.assertRaises(ValidationError) as ctx:
                schema.validate(1, {keyword: []})
            self.assertEqual(ctx.exception.code, "unsupported_schema_keyword")

    def test_unsupported_keyword_in_nested_schema_raises(self) -> None:
        with self.assertRaises(ValidationError):
            schema.validate({"a": 1}, {"properties": {"a": {"allOf": []}}})

    def test_validate_or_raise_carries_error_list(self) -> None:
        schema.validate_or_raise(1, {"type": "integer"})
        with self.assertRaises(ValidationError) as ctx:
            schema.validate_or_raise("x", {"type": "integer"}, "thing")
        self.assertEqual(len(ctx.exception.details["errors"]), 1)
        self.assertIn("thing", ctx.exception.message)


class SchemaLoadTests(unittest.TestCase):
    def test_load_known_schemas(self) -> None:
        for name in ("plan", "config"):
            self.assertEqual(schema.load(name)["type"], "object")

    def test_load_returns_independent_copies(self) -> None:
        first = schema.load("plan")
        first["type"] = "mutated"
        self.assertEqual(schema.load("plan")["type"], "object")

    def test_load_unknown_and_unsafe_names(self) -> None:
        with self.assertRaises(NotFound):
            schema.load("nope")
        with self.assertRaises(ValidationError):
            schema.load("../config")


if __name__ == "__main__":
    unittest.main()
