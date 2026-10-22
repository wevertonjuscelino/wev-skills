#!/usr/bin/env python3
"""Stand-in for ``npx -y rea-agents@V mcp``: JSON-RPC over stdio, scripted by NODE_FAKE_MCP_MODE.

(Variables start with NODE_ because the health check passes only a minimal environment.)
Modes: ok (default), empty-tools, garbage, hang, exit-non-zero, flood, grandchild, nested.
Not evidence about the real server.
"""

import json
import os
import sys
import time

mode = os.environ.get("NODE_FAKE_MCP_MODE", "ok")
if mode == "exit-non-zero":
    sys.exit(3)
if mode == "hang":
    time.sleep(600)
if mode == "garbage":
    print("this is not json", flush=True)
    time.sleep(5)
    sys.exit(0)


if mode == "nested":
    sys.stdin.readline()
    print("[" * 500000, flush=True)
    time.sleep(5)
    sys.exit(0)
if mode == "grandchild" and os.fork() == 0:
    # holds the inherited stdout and ignores stdin, like node under npx
    with open(os.environ["NODE_FAKE_MCP_PIDFILE"], "w") as handle:
        handle.write(str(os.getpid()))
        handle.flush()
    time.sleep(30)
    os._exit(0)


if mode == "grandchild":
    for _ in range(100):  # let the grandchild record its pid before answering
        pidfile = os.environ["NODE_FAKE_MCP_PIDFILE"]
        if os.path.exists(pidfile) and os.path.getsize(pidfile):
            break
        time.sleep(0.05)


def reply(request_id: object, result: object) -> None:
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        reply(message["id"], {"protocolVersion": "2025-06-18", "capabilities": {}})
        while mode == "flood":
            print('{"jsonrpc":"2.0","method":"notifications/message"}', flush=True)
    elif method == "tools/list":
        tools = [] if mode == "empty-tools" else [{"name": "inspect", "description": "x"}]
        reply(message["id"], {"tools": tools})
        if mode == "grandchild":
            time.sleep(30)
        break
