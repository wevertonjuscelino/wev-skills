"""Make recorded text safe to show: no control characters, no escape sequences, one line.

Objectives, task titles, summaries, blockers and command text come from plan files,
repository files and command output. They are data. Before the brief or the report shows
them they pass through ``clean_text``, and the block that holds them is fenced with
``security.untrusted.wrap``. Cleaning removes ways to hide or restyle text in a terminal;
it does not make instruction-like wording harmless, which is why the fence says what it is.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

FIELD_MAX_CHARS = 400
ELLIPSIS = "..."
_ANSI = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI: colors, cursor movement
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC: titles, hyperlinks
    r"|\x1b[P^_X][^\x1b]*(?:\x1b\\)?"  # DCS, PM, APC, SOS strings
    r"|\x1b[@-Z\\-_]"  # two-character escapes
)
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_LINE_BREAKS = "\n\r\t\v\f\u0085  "


def _visible(char: str) -> str:
    if char in _LINE_BREAKS:
        return " "
    return "" if unicodedata.category(char) in _HIDDEN_CATEGORIES else char


def clean_text(text: object, limit: int = FIELD_MAX_CHARS) -> str:
    """``text`` as one line of visible characters, cut to ``limit`` with a visible marker."""
    without_escapes = _ANSI.sub("", str(text))
    flat = " ".join("".join(_visible(char) for char in without_escapes).split())
    if limit <= 0 or len(flat) <= limit:
        return flat
    return flat[: max(0, limit - len(ELLIPSIS))].rstrip() + ELLIPSIS


def clean_data(value: Any, limit: int = FIELD_MAX_CHARS) -> Any:
    """A copy of JSON-like ``value`` with every string cleaned (keys are left as they are)."""
    if isinstance(value, str):
        return clean_text(value, limit)
    if isinstance(value, Mapping):
        return {key: clean_data(item, limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_data(item, limit) for item in value]
    return value
