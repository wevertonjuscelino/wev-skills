"""Pure intake transitions: at most three questions, with explicit assumptions."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, replace

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import ValidationError
from wev_skills.core.textsafe import clean_text
from wev_skills.security.redact import redact

REQUIRED = ("goal", "done", "scope", "kind")
FIELDS = (*REQUIRED, "constraints")
SOURCES = ("request", "answer", "assumption")
KINDS = ("feature", "bugfix", "investigation", "operations", "documentation", "refactor")
QUESTIONS_PER_ROUND = 3
MAX_TEXT = 2000


@dataclass(frozen=True)
class FieldValue(Serializable):
    field: str
    values: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class IntakeRecord(Serializable):
    request: str
    created_at: str
    fields: tuple[FieldValue, ...] = ()
    rounds_used: int = 0
    complete: bool = False


@dataclass(frozen=True)
class Question(Serializable):
    field: str
    question: str


@dataclass(frozen=True)
class QuestionRound(Serializable):
    questions: tuple[Question, ...]
    complete: bool
    rounds_exhausted: bool = False
    must_assume: tuple[str, ...] = ()


@dataclass(frozen=True)
class Brief(Serializable):
    goal: str
    done: tuple[str, ...]
    scope: str
    kind: str
    constraints: str
    assumptions: tuple[FieldValue, ...]
    intake_rounds: int


def _error(code: str, **details: object) -> ValidationError:
    return ValidationError(code, i18n.t(f"intake.error.{code}"), dict(details))


def _clean(text: str) -> str:
    return clean_text(redact(text), MAX_TEXT)


def start(request: str, created_at: str) -> IntakeRecord:
    if not isinstance(request, str) or not request.strip():
        raise _error("invalid_request")
    return IntakeRecord(_clean(request), created_at)


def missing(record: IntakeRecord) -> tuple[str, ...]:
    return tuple(name for name in REQUIRED if not value_of(record, name))


def value_of(record: IntakeRecord, field: str) -> tuple[str, ...]:
    return next((item.values for item in record.fields if item.field == field), ())


def set_field(
    record: IntakeRecord, field: str, values: tuple[str, ...], source: str
) -> IntakeRecord:
    if record.complete:
        raise _error("intake_finished")
    if field not in FIELDS or source not in SOURCES:
        raise _error("invalid_field")
    if not values and source == "assumption":
        default = "investigation" if field == "kind" else i18n.t(f"intake.default.{field}")
        values = (default,)
    cleaned = tuple(_clean(value) for value in values)
    if not cleaned or any(not text for text in cleaned):
        raise _error("invalid_field")
    if field != "done" and len(cleaned) != 1:
        raise _error("invalid_field")
    if field == "kind" and cleaned[0] not in KINDS:
        raise _error("invalid_field")
    item = FieldValue(field, cleaned, source)
    kept = tuple(existing for existing in record.fields if existing.field != field)
    return replace(record, fields=(*kept, item))


def next_round(record: IntakeRecord, max_rounds: int) -> tuple[IntakeRecord, QuestionRound]:
    if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or not 1 <= max_rounds <= 10:
        raise _error("invalid_round_limit")
    needed = missing(record)
    if not needed:
        return record, QuestionRound((), True)
    if record.rounds_used >= max_rounds:
        return record, QuestionRound((), False, True, needed)
    excerpt = clean_text(record.request, 160)
    questions = tuple(
        Question(name, i18n.t(f"intake.question.{name}", request=excerpt))
        for name in needed[:QUESTIONS_PER_ROUND]
    )
    return replace(record, rounds_used=record.rounds_used + 1), QuestionRound(questions, False)


def finish(record: IntakeRecord) -> tuple[IntakeRecord, Brief]:
    needed = missing(record)
    if needed:
        raise _error("intake_incomplete", missing=list(needed))
    values = {item.field: item.values for item in record.fields}
    brief = Brief(
        values["goal"][0],
        values["done"],
        values["scope"][0],
        values["kind"][0],
        values.get("constraints", ("",))[0],
        tuple(item for item in record.fields if item.source == "assumption"),
        record.rounds_used,
    )
    return replace(record, complete=True), brief


def run_start_command(brief: Brief, intake_id: str | None = None) -> str:
    tokens = ["wev", "run", "start", "--objective", brief.goal, "--from-intake"]
    if intake_id is not None:
        tokens.append(intake_id)
    if brief.kind == "operations":
        tokens.append("--external")
    if brief.assumptions:
        tokens.extend(["--unknowns", str(len(brief.assumptions))])
    return shlex.join(tokens)
