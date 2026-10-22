"""macos-core: the installer, rea, update, rollback and uninstall for real on this Mac, in an
isolated HOME. Spends network only (npm registry, GitHub releases), no account."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import unittest
import urllib.request
from pathlib import Path
from typing import Any

from tests.e2e._support import ROOT, Done, Tree, mcp_tool_count, report_line, run, scrub
from wev_skills import __version__

SCENARIO = "macos-core"
WEV = ROOT / "bin" / "wev"
INSTALLER = ROOT / "install.sh"
REGISTRY = "https://registry.npmjs.org/rea-agents"
BROKEN = "0.0.0-wev-e2e-broken"
INSTALL = ["--yes", "--lang", "en", "--source", str(ROOT), "--harness", ""] + [
    "--no-jev",
    "--rea-mode",
    "direct",
]
# npx creates these in HOME and the uninstaller does not own them.
ALLOWED_LEFTOVERS = frozenset({".npm", ".cache"})
LONG, SHORT = 900.0, 180.0
PLAIN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def _fetch_registry() -> tuple[str, str] | None:
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


def _json(done: Done) -> dict[str, Any]:
    try:
        data = json.loads(done.output)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=macos-core (make e2e)")
class MacosCore(unittest.TestCase):
    tree: Tree
    registry: tuple[str, str] | None
    installed = False
    before: frozenset[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = Tree()
        cls.before = cls.tree.listing()
        cls.registry = _fetch_registry()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tree.cleanup()

    # -- helpers ---------------------------------------------------------------------------

    def shown(self, argv: list[str]) -> str:
        words = [Path(a).name if a in (str(WEV), str(INSTALLER)) else a for a in argv]
        if words[:1] == [Path(sys.executable).name] or argv[:1] == [sys.executable]:
            words = ["wev", *words[2:]]
        return scrub(shlex.join(words), self.tree)

    def record(
        self, name: str, cmd: str, code: int | None, ok: bool, detail: str = "", note: str = ""
    ) -> None:
        """`note` says what was simulated or set up by hand; it is part of a passed result."""
        result = "failed" if not ok else f"passed ({note})" if note else "passed"
        report_line(SCENARIO, name, cmd, code, result, scrub(detail, self.tree))
        if not ok:
            self.fail(f"{name}: {detail[-800:]}")

    def skip(self, name: str, cmd: str, reason: str) -> None:
        report_line(SCENARIO, name, cmd, None, f"skipped: {reason}")
        self.skipTest(reason)

    def wev(self, *args: str, timeout: float = SHORT) -> tuple[Done, str]:
        argv = [sys.executable, str(WEV), *args]
        return run(argv, timeout, self.tree.env()), self.shown(argv)

    def install_sh(self, *args: str) -> tuple[Done, str]:
        argv = ["bash", str(INSTALLER), *args]
        return run(argv, LONG, self.tree.env()), self.shown(argv)

    def need_install(self, name: str) -> None:
        if not type(self).installed:
            self.skip(name, "", "the installer did not finish cleanly")

    def sources(self) -> dict[str, dict[str, Any]]:
        done, _ = self.wev("skills", "list")
        return {s["name"]: s for s in _json(done).get("sources", [])}

    def allow_npx_dir(self) -> None:
        """Direct mode finds npx only on permissions.exec_path (not on PATH), so a version
        manager's directory must be listed in the user config, as a person with nvm would."""
        npx = shutil.which("npx")
        conf = self.tree.config / "wev-skills" / "wev.config.json"
        data = json.loads(conf.read_text(encoding="utf-8")) if conf.exists() else {}
        data.setdefault("permissions", {})["exec_path"] = [str(Path(npx).parent)] if npx else []
        conf.write_text(json.dumps(data), encoding="utf-8")

    def active(self, name: str = "rea") -> str | None:
        value = self.sources().get(name, {}).get("active")
        return value if isinstance(value, str) else None

    # -- the checks, in order --------------------------------------------------------------

    def test_01_installer_exits_0_with_no_failure_rows(self) -> None:
        done, cmd = self.install_sh(*INSTALL)
        ok = done.exit == 0 and "Finished with" not in done.output
        type(self).installed = ok
        self.record("installer exits 0, zero failures", cmd, done.exit, ok, done.output)

    def test_02_wev_version_is_the_clone_version(self) -> None:
        self.need_install("wev version = clone version")
        done, cmd = self.wev("version")
        got = _json(done).get("version")
        self.record("wev version = clone version", cmd, done.exit, got == __version__, done.output)

    def test_03_skills_list_shows_newest_active_and_wev_not_self_managed(self) -> None:
        self.need_install("skills list: rea and agent-skills newest, wev-skills not managed")
        done, cmd = self.wev("skills", "list")
        src = {s["name"]: s for s in _json(done).get("sources", [])}
        rea, skills = src.get("rea", {}), src.get("agent-skills", {})
        newest = self.registry[0] if self.registry else rea.get("latest_seen")
        ok = (
            rea.get("active") == newest
            and skills.get("active") is not None
            and src.get("wev-skills", {}).get("active") is None
        )
        name = "skills list: rea and agent-skills newest, wev-skills not managed"
        self.record(name, cmd, done.exit, ok, f"newest rea: {newest}\n{done.output}")

    def test_04_rea_status_is_direct(self) -> None:
        self.need_install("rea status mode direct")
        done, cmd = self.wev("rea", "status")
        ok = _json(done).get("mode") == "direct"
        self.record("rea status mode direct", cmd, done.exit, ok, done.output)

    def test_05_jev_status_orchestration_is_harness(self) -> None:
        self.need_install("jev status orchestration harness")
        done, cmd = self.wev("jev", "status")
        ok = _json(done).get("orchestration") == "harness"
        self.record("jev status orchestration harness", cmd, done.exit, ok, done.output)

    def test_06_rea_serve_lists_tools(self) -> None:
        name = "rea serve answers initialize + tools/list with at least one tool"
        self.need_install(name)
        self.allow_npx_dir()
        argv = [sys.executable, str(WEV), "rea", "serve"]
        try:
            count = mcp_tool_count(argv, self.tree.env(), SHORT)
            note = "npx directory added to exec_path in the isolated user config"
            self.record(name, self.shown(argv), None, count >= 1, f"{count} tools", note)
        except (OSError, ValueError, TimeoutError) as exc:
            self.record(name, self.shown(argv), None, False, f"{type(exc).__name__}: {exc}")

    def test_07_no_skill_links_in_a_fresh_home(self) -> None:
        self.need_install("no ~/.claude/skills or ~/.agents/skills created")
        links = [p for p in (".claude/skills", ".agents/skills") if (self.tree.home / p).exists()]
        name = "no ~/.claude/skills or ~/.agents/skills created"
        self.record(name, "ls ~/.claude/skills ~/.agents/skills", None, not links, str(links))

    def test_08_rerun_gives_the_same_versions(self) -> None:
        self.need_install("re-run exits 0 with the same versions")
        before = {n: s.get("active") for n, s in self.sources().items()}
        done, cmd = self.install_sh(*INSTALL)
        after = {n: s.get("active") for n, s in self.sources().items()}
        ok = done.exit == 0 and before == after
        self.record("re-run exits 0 with the same versions", cmd, done.exit, ok, done.output)

    def test_09_install_previous_release_keeps_the_active_one(self) -> None:
        name = "skills install rea --version <previous> keeps the newest active"
        self.need_install(name)
        if self.registry is None:
            self.skip(name, "skills install rea --version <previous>", "registry unreachable")
        newest, previous = self.registry or ("", "")
        done, cmd = self.wev("skills", "install", "rea", "--version", previous)
        ok = done.exit == 0 and self.active() == newest
        self.record(name, cmd.replace(previous, "<previous>"), done.exit, ok, done.output)

    def test_10_rollback_returns_to_the_previous_release(self) -> None:
        name = "skills rollback rea -> previous release active"
        self.need_install(name)
        if self.registry is None:
            self.skip(name, "skills rollback rea", "registry unreachable")
        newest, previous = self.registry or ("", "")
        # The CLI cannot make an older release active, so state is seeded as it is after an
        # update from <previous> to <newest>; the rollback itself is the real command.
        state_file = self.tree.data / "wev-skills" / "third-party" / "state.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["sources"]["rea"].update(active=newest, previous=previous)
        state_file.write_text(json.dumps(data), encoding="utf-8")
        done, cmd = self.wev("skills", "rollback", "rea")
        ok = done.exit == 0 and self.active() == previous
        note = "state seeded: the CLI cannot make an older release active"
        self.record(name, cmd, done.exit, ok, done.output, note)

    def test_11_update_returns_to_the_newest_release(self) -> None:
        name = "skills update rea --yes -> newest active again"
        self.need_install(name)
        if self.registry is None:
            self.skip(name, "skills update rea --yes", "registry unreachable")
        newest = (self.registry or ("", ""))[0]
        done, cmd = self.wev("skills", "update", "rea", "--yes", timeout=LONG)
        ok = done.exit == 0 and self.active() == newest
        self.record(name, cmd, done.exit, ok, done.output)

    def test_12_a_broken_version_exits_8_and_changes_nothing(self) -> None:
        name = "skills install rea --version <broken> exits 8, active unchanged"
        self.need_install(name)
        was = self.active()
        done, cmd = self.wev("skills", "install", "rea", "--version", BROKEN)
        ok = done.exit == 8 and self.active() == was
        self.record(name, cmd, done.exit, ok, done.output)

    def test_13_uninstall_leaves_nothing(self) -> None:
        done, cmd = self.install_sh("--uninstall", "--yes", "--purge", "--source", str(ROOT))
        gone = not (self.tree.data / "wev-skills").exists()
        gone = gone and not (self.tree.config / "wev-skills").exists()
        extra = sorted(
            p
            for p in self.tree.listing() - self.before
            if Path(p).parts[0] not in ALLOWED_LEFTOVERS
        )
        ok = done.exit == 0 and gone and not extra
        name = "uninstall --purge removes data and config, nothing else under HOME"
        self.record(name, cmd, done.exit, ok, f"extra under HOME: {extra[:20]}\n{done.output}")


if __name__ == "__main__":
    unittest.main()
