import json
import unittest

from wev_skills.core.wiring import REPO_ROOT


class McpManifestTests(unittest.TestCase):
    def test_root_mcp_json_registers_only_rea_through_wev(self) -> None:
        data = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(list(data), ["mcpServers"])
        self.assertEqual(list(data["mcpServers"]), ["rea"])
        server = data["mcpServers"]["rea"]
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], "${CLAUDE_PLUGIN_ROOT}/bin/wev")
        self.assertEqual(server["args"], ["rea", "serve"])
