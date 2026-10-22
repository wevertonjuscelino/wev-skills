"""macos-isolated: rea in its container (`--rea-mode isolated`) on this Mac, in an isolated HOME.
Needs the Docker daemon; without it every check is skipped. Spends network and one docker
build (minutes), no account."""

from __future__ import annotations

import json
import os
import sys
import unittest

from tests.e2e import _core, _docker
from tests.e2e._support import ROOT, Done, mcp_tool_count, run
from tests.e2e.test_macos_core import WEV, LocalHost

SCENARIO = "macos-isolated"
BUILD_TIMEOUT = 1800.0
MOUNT = ":/opt/rea-home"
FIXTURE_SUFFIXES = (".elf", ".wasm", ".zip")


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=macos-isolated")
class MacosIsolated(_core.Checks):
    scenario = SCENARIO
    local: LocalHost
    version = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.blocked = _docker.daemon_problem()
        if cls.blocked:
            return
        cls.local = LocalHost()
        cls.host = cls.local
        (cls.local._tree.root / "work").mkdir()

    @classmethod
    def tearDownClass(cls) -> None:
        if not cls.blocked:
            cls.local.cleanup()

    def in_work(self, *args: str) -> Done:
        tree = self.local._tree
        return run([sys.executable, str(WEV), *args], 120, tree.env(), tree.root / "work")

    @_core.named("installer --rea-mode isolated exits 0, zero failures")
    def test_01_installer(self) -> None:
        args = [*self.host_args(), "--rea-mode", "isolated"]
        done, cmd = self.install_sh(*args)
        ok = done.exit == 0 and "Finished with" not in done.output
        type(self).installed = ok
        self.record(cmd, done.exit, ok, done.output)

    def host_args(self) -> list[str]:
        return ["--yes", "--lang", "en", "--source", self.host.source, "--harness", "", "--no-jev"]

    @_core.named("wev rea build-image builds the image")
    def test_02_build_image(self) -> None:
        self.need_install()
        done, cmd = self.wev("rea", "build-image", timeout=BUILD_TIMEOUT)
        self.record(cmd, done.exit, done.exit == 0, done.output)

    @_core.named("docker image inspect wev-rea:<version> finds it")
    def test_03_image_exists(self) -> None:
        self.need_install()
        version = self.active() or ""
        type(self).version = version
        argv = ["docker", "image", "inspect", f"wev-rea:{version}"]
        done = run(argv, 60, self.local._tree.env())
        self.record(
            "docker image inspect wev-rea:<version>", done.exit, done.exit == 0, done.output
        )

    @_core.named("rea serve (isolated) answers initialize + tools/list from the container")
    def test_04_serve_lists_tools(self) -> None:
        self.need_install()
        tree = self.local._tree
        argv = [sys.executable, str(WEV), "rea", "serve"]
        try:
            count = mcp_tool_count(argv, tree.env(), _core.SHORT, tree.root / "work")
            self.record("wev rea serve", None, count >= 1, f"{count} tools")
        except (OSError, ValueError, TimeoutError) as exc:
            self.record("wev rea serve", None, False, f"{type(exc).__name__}: {exc}")

    @_core.named("a static tool call on a fixture in the mounted cwd returns evidence")
    def test_05_static_tool_call(self) -> None:
        self.need_install()
        fixtures = [
            p for p in (ROOT / "tests" / "fixtures").rglob("*") if p.suffix in FIXTURE_SUFFIXES
        ]
        reason = (
            "a fixture exists but the tool-call step is not written"
            if fixtures
            else ("no ELF, wasm or zip fixture under tests/fixtures")
        )
        self.skip("", reason)

    @_core.named("the container runs with the host uid and gid (--user)")
    def test_06_user_matches_host(self) -> None:
        self.need_install()
        done = self.in_work("rea", "serve", "--dry-run")
        argv = _core.parse(done).get("argv", [])
        want = f"{os.getuid()}:{os.getgid()}"
        got = argv[argv.index("--user") + 1] if "--user" in argv else None
        self.record("wev rea serve --dry-run", done.exit, got == want, f"{got} vs {want}")

    @_core.named("the writable home mount holds rea's state afterwards")
    def test_07_home_mount_holds_state(self) -> None:
        self.need_install()
        done = self.in_work("rea", "serve", "--dry-run")
        argv = _core.parse(done).get("argv", [])
        mounts = [a.removesuffix(MOUNT) for a in argv if isinstance(a, str) and a.endswith(MOUNT)]
        files = sorted(os.listdir(mounts[0])) if mounts and os.path.isdir(mounts[0]) else []
        self.record("ls <rea home mount>", None, bool(files), json.dumps(files[:20]))


if __name__ == "__main__":
    unittest.main()
