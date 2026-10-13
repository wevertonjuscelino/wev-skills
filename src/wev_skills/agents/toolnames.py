"""Tool names: one place that says which tool a pattern stands for.

``Write(*)``, ``Edit(src/**)`` and ``Bash(git status:*)`` are scoped forms of ``Write``,
``Edit`` and ``Bash``. Every permission rule (the ``may_mutate`` rule, deny lists, the tool
ceiling, the lean profile) judges a pattern by that base tool, so a scope can narrow what a
tool does but never make it count as a different, unrestricted tool.
"""

from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatchcase

MUTATING_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
"""Tools that change files; an agent needs ``permissions.may_mutate`` to be offered one."""
_SCOPE_OPEN = "("
_WILDCARD = "*"


def base_tool(name: str) -> str:
    """The tool a pattern stands for: ``Bash(git status:*)`` is a form of ``Bash``."""
    return name.split(_SCOPE_OPEN, 1)[0].strip()


def is_mutating(name: str) -> bool:
    """True when ``name`` is, or may match, a tool that changes files.

    A wildcard in the base name (``E*``) counts when it matches a mutating tool.
    """
    base = base_tool(name)
    if base in MUTATING_TOOLS:
        return True
    return _WILDCARD in base and any(fnmatchcase(tool, base) for tool in MUTATING_TOOLS)


def covers(entries: Iterable[str], name: str) -> bool:
    """True when ``entries`` lists ``name`` itself or its unscoped base tool.

    ``Bash`` covers every ``Bash(...)`` form. A scoped entry covers only itself: it is
    narrower than the base tool, so it says nothing about the tool's other forms.
    """
    listed = {entry.strip() for entry in entries}
    return name.strip() in listed or base_tool(name) in listed
