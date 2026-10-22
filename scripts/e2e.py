#!/usr/bin/env python3
"""Run end-to-end scenarios for real (network, the installer, third-party servers) and write
``evals/reports/e2e-<date>.md``. Each scenario is a ``unittest`` module ``tests.e2e.test_<name>``
that appends one JSON line per check to the file named in ``WEV_E2E_REPORT``.

Nothing runs before a ``yes`` typed on ``/dev/tty`` or ``WEV_E2E_CONFIRM=yes``.
Run from the repository root: ``PYTHONPATH=src python3 scripts/e2e.py [scenario ...]``.
Exit codes: 0 all passed or skipped, 1 a check failed, 2 not confirmed or bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, TextIO

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS: Mapping[str, str] = {
    "macos-core": "network only (npm registry, GitHub releases); no account",
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
    if done.returncode != 0 and not any(r["result"] == "failed" for r in rows):
        rows.append(_crash_row(name, module, done))
    if not rows:
        rows.append(_row(name, "scenario ran", module, 0, "skipped: the module reported no checks"))
    return rows


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


def _crash_row(name: str, module: str, done: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return _row(
        name, "scenario ran", f"python -m unittest {module}", done.returncode, "failed",
        (done.stdout + done.stderr)[-2000:],
    )  # fmt: skip


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(rows: Sequence[Mapping[str, Any]], root: Path, today: str) -> str:
    head = [
        "# End-to-end report",
        "",
        f"- Date: {today}",
        f"- Platform: {platform.platform()}",
        f"- Clone commit: {_clone_commit(root)}",
        f"- {LABEL}",
        "",
    ]
    body: list[str] = []
    for name in dict.fromkeys(str(r["scenario"]) for r in rows):
        body += [f"## {name}", "", "| Check | Command | Exit | Result |", "|---|---|---|---|"]
        for r in (r for r in rows if r["scenario"] == name):
            cells = (r["check"], f"`{r['command']}`", "" if r["exit"] is None else r["exit"])
            body.append("| " + " | ".join(_cell(c) for c in (*cells, r["result"])) + " |")
        body.append("")
    bad = [r for r in rows if r["result"] == "failed"]
    if bad:
        body += ["## Failures", ""]
        for r in bad:
            body += [f"### {r['scenario']}: {r['check']}", "", f"`{r['command']}`", ""]
            body += ["```", str(r["detail"]).rstrip(), "```", ""]
    return "\n".join([*head, *body])


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
    parser.add_argument("--allow-skips", action="store_true", help="skips never fail the run")
    parser.add_argument("--out-dir", type=Path, default=root / "evals" / "reports")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    chosen = args.scenario or list(scenarios)
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
    path.write_text(render(rows, root, date.today().isoformat()), encoding="utf-8")
    counts = {
        k: sum(r["result"].startswith(k) for r in rows) for k in ("passed", "failed", "skipped")
    }
    print(f"{counts}; report: {path}", file=out)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
