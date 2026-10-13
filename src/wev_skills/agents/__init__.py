"""Agent specs, registry and factory (architecture section 4.3)."""

from __future__ import annotations

from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.agents.spec import AgentSpec, LocalizedAgent, LocalText, validate_data

__all__ = [
    "AgentFactory",
    "AgentRegistry",
    "AgentSpec",
    "LocalText",
    "LocalizedAgent",
    "validate_data",
]
