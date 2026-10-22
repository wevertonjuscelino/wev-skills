"""Helpers for the end-to-end scenarios: an isolated HOME tree, a command runner that never
sees or prints the JEV key, the report lines, and a minimal MCP client."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wev_skills.security.redact import redact

ROOT = Path(__file__).resolve().parents[2]
SECRET_VAR = "TYPESAFE_API_KEY"
MAX_REPLY = 64 * 1024 * 1024  # rea's tools/list alone is a few MB on one line
TAIL = 2000


@dataclass(frozen=True)
class Done:
    exit: int
    output: str


class Tree:
    """A temporary directory holding HOME and the three XDG roots, so nothing is written to the
    real account."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wev-e2e-")
        self.root = Path(self._tmp.name).resolve()
        self.home = self._dir("home")
        self.config = self._dir("config")
        self.data = self._dir("data")
        self.state = self._dir("state")

    def _dir(self, name: str) -> Path:
        path = self.root / name
        path.mkdir()
        return path

    def env(self) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k != SECRET_VAR}
        return {
            **base,
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.data),
            "XDG_STATE_HOME": str(self.state),
        }

    def listing(self) -> frozenset[str]:
        return frozenset(str(p.relative_to(self.home)) for p in self.home.rglob("*"))

    def cleanup(self) -> None:
        self._tmp.cleanup()


def scrub(text: str, tree: Tree | None = None) -> str:
    """Redact secrets and replace machine paths, so a report can be committed."""
    out = redact(text).replace(str(ROOT), "<clone>")
    if tree is not None:
        out = out.replace(str(tree.root), "<tmp>")
    return out.replace(str(Path.home()), "<real-home>")


def run(
    argv: Sequence[str], timeout: float, env: Mapping[str, str], cwd: Path | None = None
) -> Done:
    """Run argv without a shell, no stdin, stdout and stderr together, the key removed."""
    clean = {k: v for k, v in env.items() if k != SECRET_VAR}
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean,
            cwd=cwd,
            check=False,
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return Done(-1, f"timed out after {timeout:.0f}s\n{partial}")
    return Done(done.returncode, done.stdout + done.stderr)


def report_line(
    scenario: str, name: str, cmd: str, code: int | None, result: str, detail: str = ""
) -> None:
    """Append one JSON line to the file the runner named in WEV_E2E_REPORT (if it did)."""
    path = os.environ.get("WEV_E2E_REPORT")
    if not path:
        return
    line = {
        "scenario": scenario,
        "check": name,
        "command": cmd,
        "exit": code,
        "result": result,
        "detail": detail[-TAIL:],
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


def _pump(stream: Any, lines: queue.Queue[str | None]) -> None:
    try:
        while True:
            line = stream.readline()
            lines.put(line or None)
            if not line:
                return
    except OSError, ValueError:
        lines.put(None)


def _reply(lines: queue.Queue[str | None], wanted: int, deadline: float) -> dict[str, Any]:
    while True:
        try:
            line = lines.get(timeout=max(deadline - time.monotonic(), 0.001))
        except queue.Empty:
            raise TimeoutError("no answer from the MCP server in time") from None
        if not line or len(line) > MAX_REPLY:
            raise ValueError("the MCP server closed or sent an oversized line")
        message = json.loads(line)
        if isinstance(message, dict) and message.get("id") == wanted:
            if not isinstance(message.get("result"), dict):
                raise ValueError(f"MCP error reply: {line[:200]}")
            return dict(message["result"])


def mcp_tool_count(argv: Sequence[str], env: Mapping[str, str], timeout: float) -> int:
    """Spawn argv, send `initialize` then `tools/list`, return how many tools came back, and
    kill the whole process group. Raises when the server does not answer or sends junk."""
    proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
        list(argv),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={k: v for k, v in env.items() if k != SECRET_VAR},
        start_new_session=True,
    )
    assert proc.stdin is not None and proc.stdout is not None  # noqa: S101 - PIPEs
    lines: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True).start()
    deadline = time.monotonic() + timeout
    init: dict[str, Any] = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "wev-e2e", "version": "0"},
    }
    result: dict[str, Any] = {}
    try:
        for message in (
            {"id": 1, "method": "initialize", "params": init},
            {"method": "notifications/initialized"},
            {"id": 2, "method": "tools/list"},
        ):
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
            proc.stdin.flush()
            if message.get("id"):
                result = _reply(lines, int(str(message["id"])), deadline)
        tools = result.get("tools")
        return len(tools) if isinstance(tools, list) else 0
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError, PermissionError:
            proc.kill()
        proc.wait()
        proc.stdin.close()
        proc.stdout.close()
