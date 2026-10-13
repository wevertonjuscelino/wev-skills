"""Allow/deny patterns such as ``"git status"``, matched against parsed commands."""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Sequence

from wev_skills import i18n
from wev_skills.core.errors import ValidationError
from wev_skills.security.commands import Argv, expand, normalize


def pattern_tokens(pattern: str) -> Argv:
    """Tokens of an allow/deny pattern such as ``"git status"``; invalid patterns are an error."""
    try:
        tokens = tuple(shlex.split(pattern))
    except ValueError:
        tokens = ()
    if not tokens:
        message = i18n.t("security.error.bad_pattern", pattern=pattern)
        raise ValidationError("bad_pattern", message, {"pattern": pattern})
    return normalize(tokens)


def matches(argv: Sequence[str], pattern: str) -> bool:
    """True when ``pattern`` is a token-by-token prefix of ``argv`` (program by basename)."""
    wanted = pattern_tokens(pattern)
    return normalize(argv)[: len(wanted)] == wanted


def first_match(argvs: Iterable[Sequence[str]], patterns: Iterable[str]) -> str | None:
    """First pattern matching any of ``argvs`` (pass ``expand(...).commands`` for deny lists)."""
    candidates = [tuple(argv) for argv in argvs]
    for pattern in patterns:
        if any(matches(argv, pattern) for argv in candidates):
            return pattern
    return None


def is_allowed(argv: Sequence[str], allowed: Iterable[str], denied: Iterable[str] = ()) -> bool:
    """Allow-list match; a deny match (also behind wrappers) always wins."""
    if first_match(expand(tuple(argv)).commands, denied) is not None:
        return False
    return first_match([argv], allowed) is not None
