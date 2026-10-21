"""The OpenCode guard plugin file. Task 5 owns the real body; this one is a placeholder.

The first line marks it so an installer can refuse to install a placeholder.
"""

from __future__ import annotations

import json
from pathlib import Path

PLACEHOLDER_MARK = "// wev-placeholder"
PLUGIN_TEMPLATE = (
    PLACEHOLDER_MARK
    + """
// wev guard path: __WEV_PATH__
export const WevGuard = async () => {
  console.log("wev guard plugin not installed yet");
  return {};
};
"""
)


def render_plugin(wev_path: Path) -> str:
    return PLUGIN_TEMPLATE.replace("__WEV_PATH__", json.dumps(str(wev_path)))
