"""The registry of third-party sources: three fixed entries, nothing the user can add."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wev_skills import i18n
from wev_skills.core.errors import ValidationError


@dataclass(frozen=True)
class Source:
    name: str
    kind: Literal["npm", "github"]
    package: str
    health: Literal["mcp", "skills", "wev"]
    changelog: str  # format string with {version}


SOURCES: tuple[Source, ...] = (
    Source(
        "rea",
        "npm",
        "rea-agents",
        "mcp",
        "https://github.com/morluto/rea/releases/tag/rea-agents-{version}",
    ),
    Source(
        "agent-skills",
        "github",
        "addyosmani/agent-skills",
        "skills",
        "https://github.com/addyosmani/agent-skills/releases/tag/{version}",
    ),
    Source(
        "wev-skills",
        "github",
        "wevertonjuscelino/wev-skills",
        "wev",
        "https://github.com/wevertonjuscelino/wev-skills/releases/tag/{version}",
    ),
)


def source(name: str) -> Source:
    for item in SOURCES:
        if item.name == name:
            return item
    raise ValidationError("unknown_source", i18n.t("skills.error.unknown_source", name=name))
