"""Mask secrets before text is logged, stored or shown.

Pattern based: it catches well-known credential formats, assignments to
secret-looking names and the secret options of common command lines. A secret with
no recognizable shape and no telling name passes through, so redaction complements,
and never replaces, keeping secrets out of command lines and logs in the first place.

``redact`` works on free text, ``redact_argv`` on an argument vector (where token
boundaries are exact, so prefer it for commands) and ``redact_mapping`` on JSON-like
data. The rules live in ``redact_rules`` and ``redact_argv``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from wev_skills.security.redact_argv import apply_cli_rules, mask_argv
from wev_skills.security.redact_rules import (
    MARKER,
    SECRET_NAME,
    apply_text_rules,
    is_secret_name,
)

__all__ = ["MARKER", "MAX_DEPTH", "SECRET_NAME", "redact", "redact_argv", "redact_mapping"]

MAX_DEPTH = 20
ARGV_KEY = "argv"
"""A list under this key is a command line: it is masked as a whole, not token by token."""


def redact(text: str) -> str:
    """Return ``text`` with recognizable secrets replaced by ``[REDACTED]``.

    Idempotent, never raises, and leaves text without secrets unchanged. Runs in time
    linear in the length of the text.
    """
    content = text if isinstance(text, str) else str(text)
    return apply_cli_rules(apply_text_rules(content))


def _as_tokens(argv: object) -> tuple[str, ...]:
    """``argv`` as a tuple of strings; one token for a lone string, none if not iterable."""
    if isinstance(argv, (str, bytes)):
        return (str(argv),)
    if not isinstance(argv, Iterable):
        return ()
    return tuple(item if isinstance(item, str) else str(item) for item in argv)


def redact_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Return ``argv`` as a new tuple with the secrets in it replaced by ``[REDACTED]``.

    The vector is read as a whole first, so the value after ``--password``, after ``-p``
    for clients such as ``mysql`` or ``sshpass``, and the password of ``curl -u user:pass``
    are masked even though they have no shape of their own; then every token goes through
    ``redact``. Same length as ``argv``, idempotent, never raises, and ``argv`` is left
    as it was.
    """
    return tuple(redact(token) for token in mask_argv(_as_tokens(argv)))


def _redact_value(value: Any, depth: int) -> Any:
    if depth > MAX_DEPTH:
        return MARKER
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {key: _redact_item(key, item, depth) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, depth + 1) for item in value]
    return value


def _redact_item(key: object, item: Any, depth: int) -> Any:
    if isinstance(key, str) and is_secret_name(key):
        return MARKER
    if key == ARGV_KEY and isinstance(item, (list, tuple)):
        return list(redact_argv(item))
    return _redact_value(item, depth + 1)


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """New dict with secret-named keys masked and every string value redacted (recursively).

    A list stored under the key ``argv`` is read as one command line (``redact_argv``), so
    the value after ``--password`` is masked wherever an event or a record names an argv."""
    redacted: dict[str, Any] = _redact_value(mapping, 0)
    return redacted
