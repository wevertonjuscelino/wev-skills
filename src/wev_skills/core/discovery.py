"""Discovery: which check commands a repository appears to define, without running anything.

File contents are data. Every suggested command comes from a fixed vocabulary; the only
text taken from a file is a ``package.json`` script name that matches a strict pattern.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wev_skills.core._codec import Serializable
from wev_skills.core.errors import PermissionDenied
from wev_skills.security.paths import resolve_within

MAX_FILE_BYTES = 1_000_000
KIND_TEST = "test"
KIND_LINT = "lint"
KIND_CHECK = "check"
_MAKE_TARGET = re.compile(r"^(test|lint|check)[ \t]*:(?!=)", re.MULTILINE)
_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,39}$")
_SCRIPT_KINDS = {"test": KIND_TEST, "lint": KIND_LINT, "check": KIND_CHECK, "typecheck": KIND_LINT}
_PYPROJECT_TOOLS = (
    ("[tool.pytest", "python3 -m pytest", KIND_TEST),
    ("[tool.ruff", "ruff check .", KIND_LINT),
    ("[tool.mypy", "mypy .", KIND_LINT),
)


@dataclass(frozen=True)
class CheckSuggestion(Serializable):
    """A command the repository seems to define. A suggestion, not a verified fact."""

    command: str
    source: str
    kind: str


def _read(root: Path, name: str) -> str | None:
    """Text of a regular file directly inside ``root``; ``None`` when absent or refused."""
    try:
        path = resolve_within(root, name)
    except PermissionDenied:
        return None
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _from_makefile(text: str, source: str) -> list[CheckSuggestion]:
    targets = dict.fromkeys(_MAKE_TARGET.findall(text))
    return [CheckSuggestion(f"make {target}", source, target) for target in targets]


def _from_package_json(text: str, source: str) -> list[CheckSuggestion]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []
    found = []
    for name, kind in _SCRIPT_KINDS.items():
        if isinstance(scripts.get(name), str) and _SCRIPT_NAME.match(name):
            command = "npm test" if name == "test" else f"npm run {name}"
            found.append(CheckSuggestion(command, source, kind))
    return found


def _from_pyproject(text: str, source: str) -> list[CheckSuggestion]:
    return [
        CheckSuggestion(command, source, kind)
        for marker, command, kind in _PYPROJECT_TOOLS
        if marker in text
    ]


def _from_cargo(text: str, source: str) -> list[CheckSuggestion]:
    return [CheckSuggestion("cargo test", source, KIND_TEST)]


def _from_go_mod(text: str, source: str) -> list[CheckSuggestion]:
    return [
        CheckSuggestion("go test ./...", source, KIND_TEST),
        CheckSuggestion("go vet ./...", source, KIND_LINT),
    ]


_SOURCES: tuple[tuple[str, Callable[[str, str], list[CheckSuggestion]]], ...] = (
    ("Makefile", _from_makefile),
    ("package.json", _from_package_json),
    ("pyproject.toml", _from_pyproject),
    ("Cargo.toml", _from_cargo),
    ("go.mod", _from_go_mod),
)


def discover_checks(root: str | Path) -> tuple[CheckSuggestion, ...]:
    """Suggestions in a fixed order (Makefile first), without duplicates."""
    base = Path(root)
    found: list[CheckSuggestion] = []
    for name, parse in _SOURCES:
        text = _read(base, name)
        if text is not None:
            found.extend(parse(text, name))
    unique = {suggestion.command: suggestion for suggestion in reversed(found)}
    return tuple(s for s in found if unique[s.command] is s)


def default_check(suggestions: tuple[CheckSuggestion, ...]) -> tuple[str, ...]:
    """The first test command found, used when a task names no check of its own."""
    tests = [s.command for s in suggestions if s.kind == KIND_TEST]
    return tuple(tests[:1])
