"""Type-driven (de)serialization shared by every frozen contract dataclass."""

from __future__ import annotations

import dataclasses
import types
import typing
from enum import Enum
from typing import Any, ClassVar, TypeVar

from wev_skills.core.errors import ValidationError

T = TypeVar("T", bound="Serializable")


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Serializable):
        return value.to_dict()
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


def _fail(path: str, expected: str, value: Any) -> ValidationError:
    return ValidationError(
        "invalid_value",
        f"{path}: expected {expected}, got {type(value).__name__}",
        {"path": path},
    )


def _decode_scalar(tp: Any, value: Any, path: str) -> Any:
    if tp is bool:
        if not isinstance(value, bool):
            raise _fail(path, "bool", value)
        return value
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _fail(path, "int", value)
        return value
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _fail(path, "number", value)
        return float(value)
    if tp is str:
        if not isinstance(value, str):
            raise _fail(path, "str", value)
        return value
    return value


def _decode(tp: Any, value: Any, path: str) -> Any:
    origin = typing.get_origin(tp)
    if origin is typing.Union or origin is types.UnionType:
        args = [arg for arg in typing.get_args(tp) if arg is not type(None)]
        if value is None:
            if len(args) < len(typing.get_args(tp)):
                return None
            raise _fail(path, "non-null value", value)
        return _decode(args[0], value, path)
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise _fail(path, "list", value)
        item_type = typing.get_args(tp)[0]
        return tuple(_decode(item_type, item, f"{path}/{i}") for i, item in enumerate(value))
    if isinstance(tp, type) and issubclass(tp, Enum):
        try:
            return tp(value)
        except ValueError as exc:
            allowed = [member.value for member in tp]
            raise ValidationError(
                "invalid_enum", f"{path}: {value!r} is not one of {allowed}", {"path": path}
            ) from exc
    if isinstance(tp, type) and issubclass(tp, Serializable):
        if not isinstance(value, dict):
            raise _fail(path, "object", value)
        return tp.from_dict(value, _path=path)
    return _decode_scalar(tp, value, path)


class Serializable:
    """Mixin for frozen dataclasses: ``to_dict`` and a strict ``from_dict``."""

    # Every user is a dataclass; declaring the attribute makes it a DataclassInstance for typing.
    __dataclass_fields__: ClassVar[dict[str, dataclasses.Field[Any]]]

    def to_dict(self) -> dict[str, Any]:
        fields = dataclasses.fields(self)
        return {f.name: _encode(getattr(self, f.name)) for f in fields}

    @classmethod
    def from_dict(cls: type[T], data: Any, _path: str = "") -> T:
        if not isinstance(data, dict):
            raise _fail(_path or "/", "object", data)
        fields = dataclasses.fields(cls)
        known = {f.name for f in fields}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValidationError(
                "unknown_keys",
                f"{_path or '/'}: unknown keys {unknown} for {cls.__name__}",
                {"path": _path or "/", "unknown": unknown},
            )
        hints = typing.get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        for f in fields:
            field_path = f"{_path}/{f.name}"
            if f.name in data:
                kwargs[f.name] = _decode(hints[f.name], data[f.name], field_path)
            elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                raise ValidationError(
                    "missing_field",
                    f"{field_path}: required field missing",
                    {"path": field_path},
                )
        return cls(**kwargs)
