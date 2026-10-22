#!/usr/bin/env python3
"""Stand-in for ``npx -y rea-agents@V mcp``: JSON-RPC over stdio, scripted by FAKE_MCP_MODE.

Modes: ok (default), empty-tools, garbage, hang, exit-non-zero. Not evidence about the real server.
"""

import json
import os
import sys
import time

mode = os.environ.get("FAKE_MCP_MODE", "ok")
if mode == "exit-non-zero":
    sys.exit(3)
if mode == "hang":
    time.sleep(600)
if mode == "garbage":
    print("this is not json", flush=True)
    time.sleep(5)
    sys.exit(0)


def reply(request_id: object, result: object) -> None:
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        reply(message["id"], {"protocolVersion": "2025-06-18", "capabilities": {}})
    elif method == "tools/list":
        tools = [] if mode == "empty-tools" else [{"name": "inspect", "description": "x"}]
        reply(message["id"], {"tools": tools})
        break
