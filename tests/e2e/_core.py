"""The core checks (installer, rea, update, rollback, uninstall), written once and run against a
``Host``: this Mac in an isolated HOME (macos-core) or a Linux container (linux-core).

``CoreChecks`` is reached as ``_core.CoreChecks`` so that unittest does not collect it by itself.
"""

from __future__ import annotations

import json
import re
import shlex
import unittest
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

from tests.e2e._support import Done, Tree, report_line, scrub
from wev_skills import __version__

BROKEN = "0.0.0-wev-e2e-broken"
REGISTRY = "https://registry.npmjs.org/rea-agents"
LONG, SHORT = 900.0, 180.0
PLAIN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# npx creates these in HOME and the uninstaller does not own them (exact top-level names).
ALLOWED_LEFTOVERS = frozenset({".npm", ".cache"})
NO_LINKS = (".claude/skills", ".agents/skills")
F = TypeVar("F", bound=Callable[..., Any])


class Host(Protocol):
    """Where the checks run. `source` is the clone as the installer sees it."""

    source: str
    tree: Tree | None

    def run_wev(self, args: Sequence[str], timeout: float) -> Done: ...
    def run_install(self, args: Sequence[str], timeout: float) -> Done: ...
    def tool_count(self, timeout: float) -> int: ...
    def home_entries(self) -> frozenset[str]: ...
    def exists(self, what: str) -> bool: ...  # "data", "config" or "home:<relative path>"
    def read_state(self) -> str: ...
    def write_state(self, text: str) -> None: ...


def named(name: str) -> Callable[[F], F]:
    def mark(func: F) -> F:
        func.check_name = name  # type: ignore[attr-defined]
        return func

    return mark


def fetch_registry() -> tuple[str, str] | None:
    """(latest, the plain release just below it) from the npm registry, or None."""
    try:
        with urllib.request.urlopen(REGISTRY, timeout=30) as reply:  # noqa: S310 - https constant
            data = json.load(reply)
        latest = str(data["dist-tags"]["latest"])
        plain = sorted(
            (tuple(map(int, v.split("."))), v) for v in data["versions"] if PLAIN.fullmatch(v)
        )
        older = [v for key, v in plain if key < tuple(map(int, latest.split(".")))]
        return (latest, older[-1]) if older else None
    except OSError, ValueError, KeyError:
        return None


def parse(done: Done) -> dict[str, Any]:
    try:
        data = json.loads(done.output)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class Checks(unittest.TestCase):
    """What every scenario class shares: the host, the report lines and the skip path."""

    scenario = ""
    host: Host
    registry: tuple[str, str] | None = None
    installed = False
    blocked: str | None = None  # a reason every check is skipped with (docker down)
    before: frozenset[str] = frozenset()
    name = ""
    last_install = ""

    def setUp(self) -> None:
        self.name = getattr(getattr(type(self), self._testMethodName), "check_name", "")
        if type(self).blocked:
            self.skip("", type(self).blocked or "")

    # -- helpers ---------------------------------------------------------------------------

    def install_args(self) -> list[str]:
        return ["--yes", "--lang", "en", "--source", self.host.source, "--harness", ""] + [
            "--no-jev",
            "--rea-mode",
            "direct",
        ]

    def scrubbed(self, text: str) -> str:
        host = getattr(self, "host", None)  # absent when the scenario is blocked early
        return scrub(text, getattr(host, "tree", None))

    def record(
        self, cmd: str, code: int | None, ok: bool, detail: str = "", note: str = ""
    ) -> None:
        """`note` says what was simulated or set up by hand; it is part of a passed result."""
        result = "failed" if not ok else f"passed ({note})" if note else "passed"
        report_line(
            self.scenario, self.name, self.scrubbed(cmd), code, result, self.scrubbed(detail)
        )
        if not ok:
            self.fail(f"{self.name}: {detail[-800:]}")

    def skip(self, cmd: str, reason: str) -> None:
        report_line(self.scenario, self.name, cmd, None, f"skipped: {self.scrubbed(reason)}")
        self.skipTest(reason)

    def wev(self, *args: str, timeout: float = SHORT) -> tuple[Done, str]:
        return self.host.run_wev(args, timeout), "wev " + shlex.join(args)

    def install_sh(self, *args: str) -> tuple[Done, str]:
        return self.host.run_install(args, LONG), "bash install.sh " + shlex.join(args)

    def need_install(self) -> None:
        if not type(self).installed:
            self.skip("", "the installer did not finish cleanly")

    def need_registry(self, cmd: str) -> tuple[str, str]:
        if self.registry is None:
            self.skip(cmd, "registry unreachable")
        return self.registry or ("", "")

    def sources(self) -> dict[str, dict[str, Any]]:
        done, _ = self.wev("skills", "list")
        return {s["name"]: s for s in parse(done).get("sources", [])}

    def active(self, name: str = "rea") -> str | None:
        value = self.sources().get(name, {}).get("active")
        return value if isinstance(value, str) else None

    def versions(self) -> dict[str, Any]:
        return {n: s.get("active") for n, s in self.sources().items()}


class CoreChecks(Checks):
    """The checks, in order."""

    @named("installer exits 0, zero failures")
    def test_01_installer_exits_0_with_no_failure_rows(self) -> None:
        done, cmd = self.install_sh(*self.install_args())
        ok = done.exit == 0 and "Finished with" not in done.output
        type(self).installed = ok
        type(self).last_install = done.output
        self.record(cmd, done.exit, ok, done.output)

    @named("wev version = clone version")
    def test_02_wev_version_is_the_clone_version(self) -> None:
        self.need_install()
        done, cmd = self.wev("version")
        self.record(cmd, done.exit, parse(done).get("version") == __version__, done.output)

    @named("skills list: rea and agent-skills newest, wev-skills not managed")
    def test_03_skills_list_shows_newest_active_and_wev_not_self_managed(self) -> None:
        self.need_install()
        done, cmd = self.wev("skills", "list")
        src = {s["name"]: s for s in parse(done).get("sources", [])}
        rea, skills = src.get("rea", {}), src.get("agent-skills", {})
        newest = self.registry[0] if self.registry else rea.get("latest_seen")
        ok = (
            rea.get("active") == newest
            and skills.get("active") is not None
            and src.get("wev-skills", {}).get("active") is None
        )
        self.record(cmd, done.exit, ok, f"newest rea: {newest}\n{done.output}")

    @named("rea status mode direct")
    def test_04_rea_status_is_direct(self) -> None:
        self.need_install()
        done, cmd = self.wev("rea", "status")
        self.record(cmd, done.exit, parse(done).get("mode") == "direct", done.output)

    @named("jev status orchestration harness")
    def test_05_jev_status_orchestration_is_harness(self) -> None:
        self.need_install()
        done, cmd = self.wev("jev", "status")
        ok = parse(done).get("orchestration") == "harness"
        self.record(cmd, done.exit, ok, done.output)

    @named("rea serve answers initialize + tools/list with at least one tool")
    def test_06_rea_serve_lists_tools(self) -> None:
        self.need_install()
        try:
            count = self.host.tool_count(SHORT)
            self.record("wev rea serve", None, count >= 1, f"{count} tools")
        except (OSError, ValueError, TimeoutError) as exc:
            self.record("wev rea serve", None, False, f"{type(exc).__name__}: {exc}")

    @named("no ~/.claude/skills or ~/.agents/skills created")
    def test_07_no_skill_links_in_a_fresh_home(self) -> None:
        self.need_install()
        links = [p for p in NO_LINKS if self.host.exists(f"home:{p}")]
        self.record("ls ~/.claude/skills ~/.agents/skills", None, not links, str(links))

    @named("re-run exits 0 with the same versions")
    def test_08_rerun_gives_the_same_versions(self) -> None:
        self.need_install()
        before = self.versions()
        done, cmd = self.install_sh(*self.install_args())
        ok = done.exit == 0 and before == self.versions()
        self.record(cmd, done.exit, ok, done.output)

    @named("skills install rea --version <previous> keeps the newest active")
    def test_09_install_previous_release_keeps_the_active_one(self) -> None:
        self.need_install()
        newest, previous = self.need_registry("skills install rea --version <previous>")
        done, cmd = self.wev("skills", "install", "rea", "--version", previous)
        ok = done.exit == 0 and self.active() == newest
        self.record(cmd.replace(previous, "<previous>"), done.exit, ok, done.output)

    @named("skills rollback rea -> previous release active")
    def test_10_rollback_returns_to_the_previous_release(self) -> None:
        self.need_install()
        newest, previous = self.need_registry("skills rollback rea")
        # The CLI cannot make an older release active, so state is seeded as it is after an
        # update from <previous> to <newest>; the rollback itself is the real command.
        data = json.loads(self.host.read_state())
        data["sources"]["rea"].update(active=newest, previous=previous)
        self.host.write_state(json.dumps(data))
        done, cmd = self.wev("skills", "rollback", "rea")
        ok = done.exit == 0 and self.active() == previous
        note = "state seeded: the CLI cannot make an older release active"
        self.record(cmd, done.exit, ok, done.output, note)

    @named("skills update rea --yes -> newest active again")
    def test_11_update_returns_to_the_newest_release(self) -> None:
        self.need_install()
        newest = self.need_registry("skills update rea --yes")[0]
        done, cmd = self.wev("skills", "update", "rea", "--yes", timeout=LONG)
        ok = done.exit == 0 and self.active() == newest
        self.record(cmd, done.exit, ok, done.output)

    @named("skills install rea --version <broken> exits 8, active unchanged")
    def test_12_a_broken_version_exits_8_and_changes_nothing(self) -> None:
        self.need_install()
        was = self.active()
        done, cmd = self.wev("skills", "install", "rea", "--version", BROKEN)
        self.record(cmd, done.exit, done.exit == 8 and self.active() == was, done.output)

    @named("uninstall --purge removes data and config, nothing else under HOME")
    def test_13_uninstall_leaves_nothing(self) -> None:
        done, cmd = self.install_sh("--uninstall", "--yes", "--purge", "--source", self.host.source)
        gone = not self.host.exists("data") and not self.host.exists("config")
        extra = sorted(
            p
            for p in self.host.home_entries() - self.before
            if Path(p).parts[0] not in ALLOWED_LEFTOVERS
        )
        ok = done.exit == 0 and gone and not extra
        self.record(cmd, done.exit, ok, f"extra under HOME: {extra[:20]}\n{done.output}")
