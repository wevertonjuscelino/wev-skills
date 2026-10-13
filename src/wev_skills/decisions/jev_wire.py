"""What every ``jev ask`` exchange shares: the failure type and strict answer parsing.

The answer shape was observed once (tests/fixtures/jev_ask_response_2026-10-13.json) and
the client does not define it, so every reader here validates types and ranges and raises
``JevUnavailable`` on any deviation; callers then fall back to the local policy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from wev_skills import i18n
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import ProviderError

EXIT_COMMAND_NOT_FOUND = 127
MIN_CONFIDENCE = 0.6
"""A ``score`` or ``choice`` answer below this confidence (or with none) is not trusted."""


class JevUnavailable(ProviderError):
    """Internal: JEV could not give a usable answer; the caller falls back to local."""


def unparseable(question: str) -> JevUnavailable:
    return JevUnavailable(
        "unparseable", i18n.t("decisions.jev.why.unparseable_answer", question=question)
    )


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_fraction(value: Any) -> bool:
    return is_number(value) and 0 <= value <= 1


def fields(raw: Any, question: str, kind: str, key: str) -> tuple[Any, Mapping[str, Any]]:
    """The answer's value under ``key``; the optional ``type`` must match ``kind``."""
    if not isinstance(raw, Mapping) or key not in raw:
        raise unparseable(question)
    if "type" in raw and raw["type"] != kind:
        raise unparseable(question)
    return raw[key], raw


def confidence(raw: Mapping[str, Any], question: str) -> float | None:
    if "confidence" not in raw:
        return None
    if not is_fraction(raw["confidence"]):
        raise unparseable(question)
    return float(raw["confidence"])


def trusted(value: float | None) -> bool:
    return value is not None and value >= MIN_CONFIDENCE


def load_answers(stdout: str, questions: tuple[str, ...]) -> Mapping[str, Any]:
    """The answers object of ``jev ask``, with every one of ``questions`` present."""
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise JevUnavailable("invalid_json", i18n.t("decisions.jev.why.invalid_json")) from exc
    if not isinstance(data, Mapping):
        raise JevUnavailable("unparseable", i18n.t("decisions.jev.why.not_object"))
    missing = [question for question in questions if question not in data]
    if missing:
        raise JevUnavailable(
            "unparseable", i18n.t("decisions.jev.why.missing_answer", question=missing[0])
        )
    return data


def check_exit(result: RawCommandResult) -> None:
    if result.timed_out:
        raise JevUnavailable("timed_out", i18n.t("decisions.jev.why.timed_out"))
    if result.exit_code == EXIT_COMMAND_NOT_FOUND:
        raise JevUnavailable("binary_missing", i18n.t("decisions.jev.why.binary_missing"))
    if result.exit_code != 0:
        raise JevUnavailable(
            "exit_code", i18n.t("decisions.jev.why.exit_code", code=result.exit_code)
        )
