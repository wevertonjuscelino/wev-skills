"""Health checks for an installed third-party version. Nothing from the version dir is imported."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from wev_skills import __version__
from wev_skills.core.ports import Runner
from wev_skills.third_party.fetch import mcp_argv
from wev_skills.third_party.sources import Source

HEALTH_TIMEOUT = 60.0
MAX_LINE = 1024 * 1024
MAX_SKILL_BYTES = 1024 * 1024
PROTOCOL = "2025-06-18"


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    code: str
    detail: str


def _fail(code: str, detail: str = "") -> HealthReport:
    return HealthReport(False, code, detail)


def _reader(stream: IO[str], lines: queue.Queue[str | None]) -> None:
    try:
        while True:
            line = stream.readline(MAX_LINE + 1)
            lines.put(line or None)
            if not line:
                return
    except OSError, ValueError:
        lines.put(None)


class _BadJsonRpc(Exception):
    pass


class _Timeout(Exception):
    pass


def _read_reply(lines: queue.Queue[str | None], request_id: int, deadline: float) -> Any:
    while True:
        try:
            line = lines.get(timeout=max(deadline - time.monotonic(), 0.001))
        except queue.Empty:
            raise _Timeout from None
        if not line or len(line) > MAX_LINE:
            raise _BadJsonRpc
        try:
            message = json.loads(line)
        except ValueError:
            raise _BadJsonRpc from None
        if not isinstance(message, dict):
            raise _BadJsonRpc
        if "id" not in message:
            continue  # a notification from the server
        if message["id"] != request_id or not isinstance(message.get("result"), dict):
            raise _BadJsonRpc
        return message["result"]


def _send(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    assert proc.stdin is not None  # noqa: S101 - opened with PIPE
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", **payload}) + "\n")
    proc.stdin.flush()


def _tool_names(result: Any) -> list[str]:
    tools = result.get("tools")
    if not isinstance(tools, list) or not tools:
        raise _NoTools
    names = [t.get("name") if isinstance(t, dict) else None for t in tools]
    if not all(isinstance(n, str) for n in names):
        raise _BadJsonRpc
    return [n for n in names if isinstance(n, str)]


class _NoTools(Exception):
    pass


def _converse(proc: subprocess.Popen[str], deadline: float) -> list[str]:
    assert proc.stdout is not None  # noqa: S101 - opened with PIPE
    lines: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    info = {"name": "wev-skills", "version": __version__}
    _send(
        proc,
        {
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": info},
        },
    )
    _read_reply(lines, 1, deadline)
    _send(proc, {"method": "notifications/initialized"})
    _send(proc, {"id": 2, "method": "tools/list"})
    return _tool_names(_read_reply(lines, 2, deadline))


def _health_mcp(version: str, npx: str) -> HealthReport:
    argv = [npx, *mcp_argv(version)[1:]]
    deadline = time.monotonic() + HEALTH_TIMEOUT
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            shell=False,
        )
    except OSError as exc:
        return _fail("spawn_failed", type(exc).__name__)
    try:
        names = _converse(proc, deadline)
    except _Timeout:
        return _fail("timeout")
    except _NoTools:
        return _fail("no_tools")
    except _BadJsonRpc, OSError:
        return _fail("bad_jsonrpc")
    finally:
        proc.kill()
        proc.wait()
        for pipe in (proc.stdin, proc.stdout):
            if pipe:
                pipe.close()
    return HealthReport(True, "ok", f"{len(names)} tools")


def _frontmatter(path: Path) -> dict[str, str] | None:
    with path.open("rb") as handle:
        raw = handle.read(MAX_SKILL_BYTES + 1)
    if len(raw) > MAX_SKILL_BYTES:
        return None
    lines = raw.decode("utf-8", errors="replace").split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        return None
    meta: dict[str, str] = {}
    for line in lines[1:]:
        line = line.rstrip("\r")
        if line == "---":
            return meta
        key, sep, value = line.partition(":")
        if sep and key and key == key.lstrip():
            meta[key] = value.strip().strip("\"'")
    return None


def _skill_ok(path: Path, base: Path) -> bool:
    if not path.resolve().is_relative_to(base.resolve()):
        return False
    meta = _frontmatter(path)
    if meta is None:
        return False
    return meta.get("name") == path.parent.name and bool(meta.get("description"))


def _health_skills(base: Path) -> HealthReport:
    files = sorted(base.glob("skills/*/SKILL.md")) if base.is_dir() else []
    if not files:
        return _fail("no_skills")
    for path in files:
        try:
            good = _skill_ok(path, base)
        except OSError:
            good = False
        if not good:
            return _fail(f"bad_skill:{path.parent.name}")
    return HealthReport(True, "ok", f"{len(files)} skills")


def _health_wev(base: Path, version: str, runner: Runner, python: str) -> HealthReport:
    result = runner.run([python, str(base / "bin" / "wev"), "version"], None, HEALTH_TIMEOUT, None)
    if result.timed_out:
        return _fail("timeout")
    if result.exit_code != 0:
        return _fail("spawn_failed", f"exit {result.exit_code}")
    try:
        printed = json.loads(result.stdout).get("version")
    except ValueError, AttributeError:
        printed = None
    if printed != version.removeprefix("v"):
        return _fail("version_mismatch", f"printed {str(printed)[:40]!r}")
    return HealthReport(True, "ok", str(printed))


def health(
    source: Source,
    version: str,
    home: Path,
    runner: Runner,
    *,
    npx: str = "npx",
    python: str = sys.executable,
) -> HealthReport:
    base = home / source.name / version
    if source.health == "mcp":
        return _health_mcp(version, npx)
    if source.health == "skills":
        return _health_skills(base)
    return _health_wev(base, version, runner, python)
