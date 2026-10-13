"""Fence what the CLI prints about a repository's contents as untrusted data.

Discovery reads check commands and file names out of the repository. The agent that calls
the CLI must read them as data, so the CLI prints them inside the same fence used for
command output and remote capture instead of as bare JSON strings.
"""

from __future__ import annotations

from typing import Any

from wev_skills.security import untrusted

DISCOVERY_SOURCE = "repository discovery"
DISCOVERY_KEY = "discovery"


def _line(check: dict[str, Any]) -> str:
    return f"{check.get('command', '')}  [{check.get('source', '')}, {check.get('kind', '')}]"


def fence_discovery(payload: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``payload`` whose ``discovery`` holds one fenced text instead of raw checks."""
    found = payload.get(DISCOVERY_KEY)
    if not isinstance(found, dict):
        return payload
    checks = [item for item in found.get("checks", []) if isinstance(item, dict)]
    text = untrusted.wrap("\n".join(_line(item) for item in checks), DISCOVERY_SOURCE)
    fenced = {"untrusted": True, "source": DISCOVERY_SOURCE, "count": len(checks), "text": text}
    return {**payload, DISCOVERY_KEY: fenced}
