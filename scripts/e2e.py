#!/usr/bin/env python3
"""Run end-to-end scenarios for real (network, the installer, third-party servers) and write
``evals/reports/e2e-<date>.md``. Each scenario is a ``unittest`` module ``tests.e2e.test_<name>``
that appends one JSON line per check to the file named in ``WEV_E2E_REPORT``.

Nothing runs before a ``yes`` typed on ``/dev/tty`` or ``WEV_E2E_CONFIRM=yes``.
Run from the repository root: ``PYTHONPATH=src python3 scripts/e2e.py [scenario ...]``.
Exit codes: 0 all passed or skipped (a skip never fails the run), 1 a check failed,
2 not confirmed or bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from wev_skills.security.redact import redact

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS: Mapping[str, str] = {
    "macos-core": "network only (npm registry, GitHub releases); no account",
    "linux-core": "network + one docker build (minutes); no account",
    "macos-isolated": "network + one docker build (minutes); no account",
    "claude": "Claude Code account + tokens: uses your real Claude login in an isolated HOME",
    "codex": "Codex account + tokens: uses your real Codex login in an isolated HOME",
    "gemini": "you install the Gemini CLI first (not present today); a Gemini account + tokens",
    "opencode": "you install the OpenCode CLI first (not present today); no account",
    "jev": "one real jev ask call to api.typesafe.ai with a key you type yourself",
    "update-daily": "network (npm registry); no account",
}
LABEL = "macOS: tested with isolated HOME, not a clean machine"
OpenTty = Callable[[], TextIO | None]


def open_tty() -> TextIO | None:
    try:
        return open("/dev/tty", "r+", encoding="utf-8")  # noqa: SIM115 - closed by the caller
    except OSError:
        return None


def confirmed(env: Mapping[str, str], tty: OpenTty) -> bool | None:
    """True/False for an answer, None when there is no way to ask."""
    if env.get("WEV_E2E_CONFIRM") == "yes":
        return True
    handle = tty()
    if handle is None:
        return None
    with handle:
        handle.write("Type yes to run these scenarios for real: ")
        handle.flush()
        return handle.readline().strip() == "yes"


def _clone_commit(root: Path) -> str:
    def git(*args: str) -> str:
        done = subprocess.run(  # noqa: S603, S607 - fixed argv
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
        return done.stdout.strip()

    sha = git("rev-parse", "--short", "HEAD") or "unknown"
    return f"{sha} (working tree has uncommitted changes)" if git("status", "--porcelain") else sha


def run_scenario(name: str, package: str, root: Path) -> list[dict[str, Any]]:
    """Run one scenario module in a subprocess and return its check rows."""
    with tempfile.TemporaryDirectory(prefix="wev-e2e-report-") as tmp:
        report = Path(tmp) / "report.jsonl"
        module = f"{package}.test_{name.replace('-', '_')}"
        env = {
            **os.environ,
            "WEV_E2E": name,
            "WEV_E2E_REPORT": str(report),
            "PYTHONPATH": os.pathsep.join(
                [str(root / "src"), str(root), os.environ.get("PYTHONPATH", "")]
            ),
        }
        done = subprocess.run(  # noqa: S603 - fixed argv
            [sys.executable, "-m", "unittest", module],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        lines = report.read_text(encoding="utf-8").splitlines() if report.exists() else []
    rows: list[dict[str, Any]] = [json.loads(line) for line in lines if line.strip()]
    if done.returncode != 0 and _failures(done.stderr + done.stdout) > _failed(rows):
        rows.append(_crash_row(name, module, done, root))
    if not rows:
        rows.append(_row(name, "scenario ran", module, 0, "skipped: the module reported no checks"))
    return rows


def _failed(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(r["result"] == "failed" for r in rows)


def _failures(output: str) -> int:
    """failures + errors unittest reported; a run it could not summarise counts as one."""
    found = re.search(r"FAILED \((.*)\)", output)
    counts = re.findall(r"=(\d+)", found.group(1)) if found else []
    return sum(map(int, counts)) or 1


def scrub(text: str, root: Path) -> str:
    """Redact secrets and replace machine paths, so a report can be committed."""
    out = redact(text).replace(str(root), "<clone>")
    out = re.sub(r"\S*wev-e2e-\w+", "<tmp>", out)
    return out.replace(str(Path.home()), "<real-home>")


def _row(
    name: str, check: str, cmd: str, code: int | None, result: str, detail: str = ""
) -> dict[str, Any]:
    return {
        "scenario": name,
        "check": check,
        "command": cmd,
        "exit": code,
        "result": result,
        "detail": detail,
    }


def _crash_row(
    name: str, module: str, done: subprocess.CompletedProcess[str], root: Path
) -> dict[str, Any]:
    detail = scrub((done.stdout + done.stderr)[-2000:], root)
    cmd = f"python -m unittest {module}"
    return _row(name, "scenario ran", cmd, done.returncode, "failed", detail)


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _code(cmd: object) -> str:
    text = str(cmd)
    if not text:
        return ""
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def _section(name: str, rows: Sequence[Mapping[str, Any]]) -> list[str]:
    mine = [r for r in rows if r["scenario"] == name]
    out = [f"## {name}", "", "| Check | Command | Exit | Result |", "|---|---|---|---|"]
    for r in mine:
        cells = (r["check"], _code(r["command"]), "" if r["exit"] is None else r["exit"])
        out.append("| " + " | ".join(_cell(c) for c in (*cells, r["result"])) + " |")
    out.append("")
    for r in (r for r in mine if r["result"] == "failed"):
        out += [f"### Failed: {r['check']}", "", _code(r["command"]), ""]
        out += ["```", str(r["detail"]).rstrip(), "```", ""]
    return out


def _sections_of(text: str) -> dict[str, str]:
    """The `## <scenario>` sections of an earlier report, by name."""
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = found.setdefault(line[3:].strip(), [])
        if current is not None:
            current.append(line)
    return {name: "\n".join(lines) for name, lines in found.items()}


def render(rows: Sequence[Mapping[str, Any]], root: Path, today: str, earlier: str = "") -> str:
    """The report: a fresh header, the sections of `earlier` for scenarios not in `rows`, and
    a section for every scenario in `rows` (replacing the old one)."""
    head = [
        "# End-to-end report",
        "",
        f"- Date: {today}",
        f"- Platform: {platform.platform()}",
        f"- Clone commit: {_clone_commit(root)}",
        f"- {LABEL}",
        "",
    ]
    sections = _sections_of(earlier)
    for name in dict.fromkeys(str(r["scenario"]) for r in rows):
        sections[name] = "\n".join(_section(name, rows))
    return "\n".join(head) + "\n" + "\n".join(s.rstrip() + "\n" for s in sections.values())


def main(
    argv: Sequence[str] | None = None,
    *,
    scenarios: Mapping[str, str] = SCENARIOS,
    package: str = "tests.e2e",
    root: Path = ROOT,
    env: Mapping[str, str] | None = None,
    tty: OpenTty = open_tty,
    out: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Run end-to-end scenarios for real.")
    parser.add_argument(
        "scenario", nargs="*", help=f"one of: {', '.join(scenarios)} (default: all)"
    )
    parser.add_argument("--out-dir", type=Path, default=root / "evals" / "reports")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    chosen = " ".join(args.scenario).split() or list(scenarios)  # make passes E2E as one word
    unknown = [n for n in chosen if n not in scenarios]
    if unknown:
        print(f"unknown scenario: {', '.join(unknown)}", file=sys.stderr)
        return 2
    for name in chosen:
        print(f"{name}: {scenarios[name]}", file=out, flush=True)
    answer = confirmed(os.environ if env is None else env, tty)
    if not answer:
        why = "no terminal and WEV_E2E_CONFIRM is not yes" if answer is None else "not confirmed"
        print(f"Nothing was run: {why}.", file=sys.stderr)
        return 2
    rows = [row for name in chosen for row in run_scenario(name, package, root)]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"e2e-{date.today().isoformat()}.md"
    earlier = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(render(rows, root, date.today().isoformat(), earlier), encoding="utf-8")
    counts = {
        k: sum(r["result"].startswith(k) for r in rows) for k in ("passed", "failed", "skipped")
    }
    print(f"{counts}; report: {path}", file=out)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
