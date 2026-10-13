"""JSON Schema subset validator (architecture section 4.1). Standard library only."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from wev_skills.core.errors import NotFound, ValidationError

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

_ASSERTIONS = frozenset(
    {
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
        "$ref",
    }
)
_ANNOTATIONS = frozenset(
    {"$schema", "$id", "$defs", "title", "description", "default", "examples", "$comment"}
)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load(name: str) -> dict[str, Any]:
    """Load ``schemas/<name>.schema.json`` (a fresh copy on every call)."""
    if not _NAME_RE.match(name):
        raise ValidationError("invalid_schema_name", f"invalid schema name: {name!r}")
    path = SCHEMA_DIR / f"{name}.schema.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise NotFound("schema_not_found", f"schema not found: {name}", {"name": name}) from exc
    loaded: dict[str, Any] = json.loads(text)
    return copy.deepcopy(loaded)


def validate(instance: Any, schema: dict[str, Any]) -> list[str]:
    """Return error strings (``"<json-pointer>: message"``); empty when valid."""
    errors: list[str] = []
    _check(instance, schema, schema, "", errors)
    return errors


def validate_or_raise(instance: Any, schema: dict[str, Any], what: str = "document") -> None:
    errors = validate(instance, schema)
    if errors:
        raise ValidationError(
            "schema_validation_failed",
            f"{what} failed schema validation ({len(errors)} error(s)): {errors[0]}",
            {"errors": errors},
        )


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _is_type(value: Any, name: str) -> bool:
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if name == "null":
        return value is None
    raise ValidationError("unsupported_schema_type", f"unsupported type name: {name!r}")


def _same(a: Any, b: Any) -> bool:
    """JSON equality that does not conflate True with 1."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return False
    return bool(a == b)


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise ValidationError("unsupported_ref", f"only local '#/$defs/<name>' refs: {ref!r}")
    target = root.get("$defs", {}).get(ref[len(prefix) :])
    if not isinstance(target, dict):
        raise ValidationError("unresolved_ref", f"unresolved $ref: {ref!r}")
    return target


def _check(
    value: Any, schema: dict[str, Any], root: dict[str, Any], path: str, errors: list[str]
) -> None:
    if not isinstance(schema, dict):
        raise ValidationError("invalid_schema", f"schema at {path or '/'} must be an object")
    unsupported = sorted(set(schema) - _ASSERTIONS - _ANNOTATIONS)
    if unsupported:
        raise ValidationError(
            "unsupported_schema_keyword",
            f"unsupported schema keyword(s) at {path or '/'}: {unsupported}",
            {"keywords": unsupported},
        )
    here = path or "/"
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), root, path, errors)
    if "type" in schema and not _type_ok(value, schema["type"]):
        errors.append(f"{here}: expected type {schema['type']}, got {_type_name(value)}")
        return
    if "enum" in schema and not any(_same(value, item) for item in schema["enum"]):
        errors.append(f"{here}: {value!r} is not one of {schema['enum']}")
    if "const" in schema and not _same(value, schema["const"]):
        errors.append(f"{here}: expected constant {schema['const']!r}")
    _check_scalar(value, schema, here, errors)
    if isinstance(value, list):
        _check_array(value, schema, root, path, errors)
    if isinstance(value, dict):
        _check_object(value, schema, root, path, errors)


def _type_ok(value: Any, declared: Any) -> bool:
    names = declared if isinstance(declared, list) else [declared]
    return any(_is_type(value, name) for name in names)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    return {str: "string", int: "integer", float: "number", list: "array", dict: "object"}.get(
        type(value), type(value).__name__
    )


def _check_scalar(value: Any, schema: dict[str, Any], here: str, errors: list[str]) -> None:
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{here}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{here}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{here}: does not match pattern {schema['pattern']!r}")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{here}: {value} is less than minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{here}: {value} is greater than maximum {schema['maximum']}")


def _check_array(
    value: list[Any], schema: dict[str, Any], root: dict[str, Any], path: str, errors: list[str]
) -> None:
    here = path or "/"
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{here}: fewer than minItems {schema['minItems']}")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{here}: more than maxItems {schema['maxItems']}")
    if schema.get("uniqueItems"):
        for i, item in enumerate(value):
            if any(_same(item, earlier) for earlier in value[:i]):
                errors.append(f"{path}/{i}: duplicate item violates uniqueItems")
    if "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], root, f"{path}/{i}", errors)


def _check_object(
    value: dict[str, Any],
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    here = path or "/"
    for key in schema.get("required", []):
        if key not in value:
            errors.append(f"{here}: missing required property '{key}'")
    props = schema.get("properties", {})
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        child = f"{path}/{_escape(key)}"
        if key in props:
            _check(item, props[key], root, child, errors)
        elif extra is False:
            errors.append(f"{child}: additional property not allowed")
        elif isinstance(extra, dict):
            _check(item, extra, root, child, errors)
