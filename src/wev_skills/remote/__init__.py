"""Optional remote module: authorized SSH hosts, tmux-backed runs, evidence-based status.

Three separate concerns: ``inventory`` (which hosts may be reached), ``transport``
(how one command reaches a host) and ``tmux`` (session lifecycle). Permission and
approval decisions are injected; none are made here.
"""

from __future__ import annotations

from wev_skills.remote.inventory import Inventory, validate_alias
from wev_skills.remote.session import (
    PreflightReport,
    RemoteRun,
    RemoteStatus,
    action_string,
    owner_token,
    session_name,
)
from wev_skills.remote.tmux import TmuxController
from wev_skills.remote.transport import SshTransport, Transport

__all__ = [
    "Inventory",
    "PreflightReport",
    "RemoteRun",
    "RemoteStatus",
    "SshTransport",
    "TmuxController",
    "Transport",
    "action_string",
    "owner_token",
    "session_name",
    "validate_alias",
]
