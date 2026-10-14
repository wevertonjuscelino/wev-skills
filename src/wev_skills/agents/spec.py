"""Agent spec model (architecture section 4.3): a frozen mirror of ``agent.schema.json``."""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from wev_skills import i18n, schema
from wev_skills.agents.experience import Lesson
from wev_skills.config import TIER_NAMES
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import GuardAction, Mode, RiskLevel
from wev_skills.core.errors import ValidationError

SCHEMA_VERSION = 1
DEFAULT_LANG = "en"
MAX_BUDGET_UNITS = 10_000
"""Upper bound of ``budget.max_units``; the exporter turns the budget into ``maxTurns``."""
MAX_TIMEOUT_SECONDS = 7 * 24 * 3600


class LocalText(str):
    """Free text that may carry translations. It is the English string itself (a ``str``),
    plus ``get(lang)`` which falls back to English."""

    _translations: tuple[tuple[str, str], ...]

    def __new__(cls, en: str, translations: Mapping[str, str] | None = None) -> LocalText:
        obj = super().__new__(cls, en)
        pairs = {k: v for k, v in (translations or {}).items() if k != DEFAULT_LANG}
        obj._translations = tuple(sorted(pairs.items()))
        return obj

    @classmethod
    def parse(cls, value: str | Mapping[str, str]) -> LocalText:
        if isinstance(value, str):
            return cls(value)
        return cls(value[DEFAULT_LANG], value)

    @property
    def translations(self) -> Mapping[str, str]:
        return dict(self._translations)

    def get(self, lang: str | None = None) -> str:
        return str(self.translations.get(lang or DEFAULT_LANG, self))

    def has(self, lang: str) -> bool:
        return lang == DEFAULT_LANG or lang in self.translations

    def to_json(self) -> str | dict[str, str]:
        if not self._translations:
            return str(self)
        return {DEFAULT_LANG: str(self), **self.translations}

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LocalText):
            return str.__eq__(self, other) and self._translations == other._translations
        return str.__eq__(self, other)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    __hash__ = str.__hash__


class _Sparse(Serializable):
    """Serializable whose ``to_dict`` omits unset (None) fields."""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in super().to_dict().items() if v is not None}


@dataclass(frozen=True)
class ModelPolicy(_Sparse):
    min_tier: str | None = None
    max_tier: str | None = None
    escalate_on_failure: bool | None = None


@dataclass(frozen=True)
class Tools(_Sparse):
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()


@dataclass(frozen=True)
class Permissions(_Sparse):
    modes: tuple[Mode, ...] | None = None
    max_risk: RiskLevel | None = None
    may_mutate: bool | None = None
    may_use_remote: bool | None = None
    ceiling: bool | None = None
    """True: descendants may narrow these permissions but never widen them, nor unset this."""


@dataclass(frozen=True)
class Budget(_Sparse):
    max_units: float | None = None


@dataclass(frozen=True)
class Escalation(_Sparse):
    on_failure: GuardAction | None = None
    to: str | None = None


TEXT_FIELDS = ("name", "description", "instructions", "output_format")
TEXT_LIST_FIELDS = ("responsibilities", "success_criteria", "stop_conditions")
_NESTED: dict[str, type[_Sparse]] = {
    "model_policy": ModelPolicy,
    "tools": Tools,
    "permissions": Permissions,
    "budget": Budget,
    "escalation": Escalation,
}
_TUPLE_FIELDS = ("specialties", "skills", "required_checks")
EXPERIENCE_KEY = "experience"
_SCALAR_FIELDS = ("schema_version", "id", "extends", "model", "timeout_seconds", "max_attempts")


@dataclass(frozen=True)
class LocalizedAgent:
    """An agent's free text resolved to a single language."""

    id: str
    lang: str
    name: str
    description: str
    instructions: str
    output_format: str
    responsibilities: tuple[str, ...]
    success_criteria: tuple[str, ...]
    stop_conditions: tuple[str, ...]


@dataclass(frozen=True)
class AgentSpec:
    """One agent persona. Satisfies the ``AgentLike`` port (``id``, ``description``,
    ``specialties``). Unset optional fields are None; ``AgentFactory.resolve`` fills defaults."""

    id: str
    name: LocalText
    description: LocalText
    schema_version: int = SCHEMA_VERSION
    specialties: tuple[str, ...] = ()
    instructions: LocalText | None = None
    responsibilities: tuple[LocalText, ...] = ()
    extends: str | None = None
    model: str | None = None
    model_policy: ModelPolicy | None = None
    tools: Tools | None = None
    skills: tuple[str, ...] = ()
    permissions: Permissions | None = None
    budget: Budget | None = None
    timeout_seconds: float | None = None
    max_attempts: int | None = None
    success_criteria: tuple[LocalText, ...] = ()
    escalation: Escalation | None = None
    required_checks: tuple[str, ...] = ()
    output_format: LocalText | None = None
    stop_conditions: tuple[LocalText, ...] = ()
    experience: tuple[Lesson, ...] = ()
    """Reviewed lessons (``agents.experience``): advisory text, never inherited."""

    @classmethod
    def from_dict(cls, data: Any) -> AgentSpec:
        """Strict constructor: the document must pass ``validate_data`` first."""
        errors = validate_data(data)
        if errors:
            raise ValidationError(
                "schema_validation_failed",
                i18n.t("agents.error.invalid_spec", errors="; ".join(errors)),
                {"errors": errors},
            )
        kwargs: dict[str, Any] = {k: data[k] for k in _SCALAR_FIELDS if k in data}
        for key in TEXT_FIELDS:
            if key in data:
                kwargs[key] = LocalText.parse(data[key])
        for key in TEXT_LIST_FIELDS:
            kwargs[key] = tuple(LocalText.parse(v) for v in data.get(key, ()))
        for key in _TUPLE_FIELDS:
            kwargs[key] = tuple(data.get(key, ()))
        for key, klass in _NESTED.items():
            if key in data:
                kwargs[key] = klass.from_dict(data[key], _path=f"/{key}")
        lessons = enumerate(data.get(EXPERIENCE_KEY, ()))
        kwargs[EXPERIENCE_KEY] = tuple(
            Lesson.from_dict(item, _path=f"/{EXPERIENCE_KEY}/{i}") for i, item in lessons
        )
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if value is None or (isinstance(value, tuple) and not value):
                continue
            out[f.name] = _encode_field(value)
        return out

    def localized(self, lang: str | None = None) -> LocalizedAgent:
        """Free text in ``lang`` (``en`` or ``pt-BR``), falling back to English per field."""
        code = i18n.resolve_language(lang)

        def pick(text: LocalText | None) -> str:
            return "" if text is None else text.get(code)

        return LocalizedAgent(
            id=self.id,
            lang=code,
            name=pick(self.name),
            description=pick(self.description),
            instructions=pick(self.instructions),
            output_format=pick(self.output_format),
            responsibilities=tuple(pick(t) for t in self.responsibilities),
            success_criteria=tuple(pick(t) for t in self.success_criteria),
            stop_conditions=tuple(pick(t) for t in self.stop_conditions),
        )

    def localizable_texts(self) -> list[LocalText]:
        """Every free-text value of the spec, for completeness checks."""
        single = [getattr(self, k) for k in TEXT_FIELDS if getattr(self, k) is not None]
        lists = [t for k in TEXT_LIST_FIELDS for t in getattr(self, k)]
        return [*single, *lists]


def _encode_field(value: Any) -> Any:
    if isinstance(value, LocalText):
        return value.to_json()
    if isinstance(value, tuple):
        return [_encode_field(item) for item in value]
    if isinstance(value, Serializable):
        return value.to_dict()
    return value


@lru_cache(maxsize=1)
def _agent_schema() -> dict[str, Any]:
    return schema.load("agent")


def validate_data(data: Any) -> list[str]:
    """Schema errors (JSON-pointer paths) plus cross-field checks; empty when valid."""
    errors = schema.validate(data, _agent_schema())
    if errors:
        return errors
    return _cross_field_errors(data)


def _cross_field_errors(data: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("extends") == data["id"]:
        errors.append(f"/extends: {i18n.t('agents.error.self_extends')}")
    target = data.get("escalation", {}).get("to")
    if target is not None and target == data["id"]:
        errors.append(f"/escalation/to: {i18n.t('agents.error.self_escalation')}")
    policy = data.get("model_policy", {})
    if tier_order_violation(policy.get("min_tier"), policy.get("max_tier")):
        errors.append(f"/model_policy: {i18n.t('agents.error.tier_order')}")
    ids = [item["id"] for item in data.get(EXPERIENCE_KEY, ())]
    if len(ids) != len(set(ids)):
        errors.append(f"/{EXPERIENCE_KEY}: {i18n.t('agents.error.duplicate_lesson')}")
    return [*errors, *_pattern_errors(data), *_number_errors(data)]


def _pattern_errors(data: Mapping[str, Any]) -> list[str]:
    """Names that do not match their schema pattern from the first to the last character.

    The schema validator searches, and ``$`` also matches before a final newline, so
    ``"abc\\n"`` passes it. Names end up in file names and YAML, hence the full match here.
    """
    definitions, properties = _agent_schema()["$defs"], _agent_schema()["properties"]
    agent_id, tool = definitions["agent_id"]["pattern"], definitions["tool_name"]["pattern"]
    tools = data.get("tools", {})
    checks: list[tuple[str, str, Any]] = [
        ("/id", agent_id, data["id"]),
        ("/extends", agent_id, data.get("extends")),
        ("/escalation/to", agent_id, data.get("escalation", {}).get("to")),
        ("/model", properties["model"]["pattern"], data.get("model")),
    ]
    for key in ("allow", "deny"):
        checks += [(f"/tools/{key}/{i}", tool, v) for i, v in enumerate(tools.get(key, ()))]
    skill = properties["skills"]["items"]["pattern"]
    checks += [(f"/skills/{i}", skill, v) for i, v in enumerate(data.get("skills", ()))]
    return [
        f"{where}: {i18n.t('agents.error.pattern', pattern=pattern)}"
        for where, pattern, value in checks
        if value is not None and re.fullmatch(pattern, value) is None
    ]


def number_in_range(value: float, maximum: float) -> bool:
    """True for a finite number not above ``maximum`` (``inf``, ``nan`` and huge ints fail)."""
    try:
        return math.isfinite(value) and value <= maximum
    except OverflowError:
        return False


def _number_errors(data: Mapping[str, Any]) -> list[str]:
    limits = (
        ("/budget/max_units", data.get("budget", {}).get("max_units"), MAX_BUDGET_UNITS),
        ("/timeout_seconds", data.get("timeout_seconds"), MAX_TIMEOUT_SECONDS),
    )
    return [
        f"{where}: {i18n.t('agents.error.number_range', maximum=maximum)}"
        for where, value, maximum in limits
        if value is not None and not number_in_range(value, maximum)
    ]


def tier_order_violation(low: str | None, high: str | None) -> bool:
    if low is None or high is None:
        return False
    return TIER_NAMES.index(low) > TIER_NAMES.index(high)
