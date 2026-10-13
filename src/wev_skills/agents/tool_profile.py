"""Tool profiles: how much of an agent's allow list is offered to it (hypotheses H5 and H9).

``structured`` (the default) offers the agent's full allow list. It is the default because
tools that are permission-checked one by one are easier to govern than a shell that can do
everything. ``lean`` offers an agent that may change files only the shell plus the minimal
read and edit tools it already had. It is an option the harness-design paper motivates for
strong models, on cost grounds only, and it was not measured on Claude models: nothing here
claims it is cheaper or better. ``auto`` picks ``lean`` for the premium tier and
``structured`` otherwise.

A profile only ever removes entries from ``allow``. It never adds a tool, never touches the
deny list and never changes permissions, so it cannot loosen what an agent may do.
"""

from __future__ import annotations

from dataclasses import replace

from wev_skills import i18n
from wev_skills.agents.spec import Permissions, Tools
from wev_skills.agents.toolnames import base_tool
from wev_skills.config import AUTO, TIER_NAMES, TOOL_PROFILES, ModelsConfig
from wev_skills.core.errors import ValidationError

STRUCTURED = "structured"
LEAN = "lean"
LEAN_TIER = "premium"
SHELL_TOOL = "Bash"
LEAN_TOOLS = frozenset({SHELL_TOOL, "Read", "Edit"})
"""The lean surface: the shell, one tool to read a file and one to edit it."""
FALLBACK_TIER = "standard"


def tier_of(model: str | None, models: ModelsConfig) -> str:
    """The tier ``model`` stands for: the tier name itself, the tier that lists the model id,
    or ``standard`` when the model is unset or unknown."""
    if model in TIER_NAMES:
        return str(model)
    for name in TIER_NAMES:
        if model and model in models.tier(name):
            return name
    return FALLBACK_TIER


def resolve_profile(profile: str, tier: str) -> str:
    """``structured`` or ``lean`` for a configured profile and the executor's tier."""
    if profile not in TOOL_PROFILES:
        message = i18n.t("agents.error.tool_profile", profile=profile)
        raise ValidationError("unknown_tool_profile", message, {"profile": profile})
    if profile == AUTO:
        return LEAN if tier == LEAN_TIER else STRUCTURED
    return profile


def apply_profile(
    tools: Tools | None, permissions: Permissions | None, profile: str
) -> Tools | None:
    """``tools`` under a resolved ``profile`` (a new object; the argument is not changed).

    ``lean`` applies only to an agent that may change files and has the shell allowed:
    without a shell there is nothing to lean on, and a read-only agent keeps its surface.
    """
    if profile != LEAN or tools is None:
        return tools
    may_mutate = permissions is not None and bool(permissions.may_mutate)
    has_shell = any(base_tool(tool) == SHELL_TOOL for tool in tools.allow)
    if not may_mutate or not has_shell:
        return tools
    return replace(tools, allow=tuple(t for t in tools.allow if base_tool(t) in LEAN_TOOLS))
