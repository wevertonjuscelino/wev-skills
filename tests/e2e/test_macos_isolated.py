"""macos-isolated: rea in its container (`--rea-mode isolated`) on this Mac, in an isolated HOME.
Needs the Docker daemon; without it every check is skipped. Spends network and one docker
build (minutes), no account. The isolated HOME hides ~/.docker, so DOCKER_HOST is taken from the
account's Docker context and passed to the commands (the report says so).

Label: implemented but untested against a live Docker daemon in this change."""

from __future__ import annotations

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
NOTE = "the account's real Docker context endpoint (DOCKER_HOST) was passed in"


class DockerLocalHost(LocalHost):
    """The isolated tree, plus the Docker endpoint the isolated HOME can no longer find."""

    def env(self) -> dict[str, str]:
        return _docker.docker_env(super().env())


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=macos-isolated")
class MacosIsolated(_core.Checks):
    scenario = SCENARIO
    local: DockerLocalHost
    status: dict[str, object] = {}

    @classmethod
    def setUpClass(cls) -> None:
        local = DockerLocalHost()
        cls.blocked = _docker.daemon_problem(local.env())
        if cls.blocked:
            local.cleanup()
            return
        cls.local = local
        cls.host = local
        cls.addClassCleanup(local.cleanup)
        (local._tree.root / "work").mkdir()

    def in_work(self, *args: str) -> Done:
        return run(
            [sys.executable, str(WEV), *args], 120, self.local.env(), self.local._tree.root / "work"
        )

    def dry_run_argv(self) -> list[str]:
        argv = _core.parse(self.in_work("rea", "serve", "--dry-run")).get("argv", [])
        return [a for a in argv if isinstance(a, str)]

    @_core.named("installer --rea-mode isolated exits 0, zero failures")
    def test_01_installer(self) -> None:
        args = ["--yes", "--lang", "en", "--source", self.host.source, "--harness", ""]
        done, cmd = self.install_sh(*args, "--no-jev", "--rea-mode", "isolated")
        ok = done.exit == 0 and "Finished with" not in done.output
        type(self).installed = ok
        self.record(cmd, done.exit, ok, done.output, NOTE)

    @_core.named("wev rea build-image builds the image")
    def test_02_build_image(self) -> None:
        self.need_install()
        done, cmd = self.wev("rea", "build-image", timeout=BUILD_TIMEOUT)
        self.record(cmd, done.exit, done.exit == 0, done.output, NOTE)

    @_core.named("docker image inspect wev-rea:<version> finds it")
    def test_03_image_exists(self) -> None:
        self.need_install()
        done, _ = self.wev("rea", "status")
        info = _core.parse(done)
        image, version = info.get("image"), info.get("version")
        if not (isinstance(image, str) and isinstance(version, str)):
            self.record("wev rea status", done.exit, False, done.output)
            return
        type(self).status = dict(info)
        inspect = run(["docker", "image", "inspect", image], 60, self.local.env())
        ok = inspect.exit == 0 and image.endswith(f":{version}")
        self.record("docker image inspect wev-rea:<version>", inspect.exit, ok, inspect.output)

    @_core.named("rea serve (isolated) answers initialize + tools/list from the container")
    def test_04_serve_lists_tools(self) -> None:
        self.need_install()
        argv = [sys.executable, str(WEV), "rea", "serve"]
        work = self.local._tree.root / "work"
        try:
            count = mcp_tool_count(argv, self.local.env(), _core.SHORT, work)
            self.record("wev rea serve", None, count >= 1, f"{count} tools", NOTE)
        except (OSError, ValueError, TimeoutError) as exc:
            self.record("wev rea serve", None, False, f"{type(exc).__name__}: {exc}")

    @_core.named("a static tool call on a fixture in the mounted cwd returns evidence")
    def test_05_static_tool_call(self) -> None:
        self.need_install()
        found = [
            p for p in (ROOT / "tests" / "fixtures").rglob("*") if p.suffix in FIXTURE_SUFFIXES
        ]
        if found:  # a fixture appeared: the tool-call step must be written, not skipped
            detail = f"write the tool-call step for {found[0].name}"
            self.record("tests/fixtures", None, False, detail)
        self.skip("", "no ELF/wasm/zip fixture in tests/fixtures")

    @_core.named("the container runs as the host uid and gid (--user)")
    def test_06_user_matches_host(self) -> None:
        self.need_install()
        argv = self.dry_run_argv()
        want = f"{os.getuid()}:{os.getgid()}"
        got = argv[argv.index("--user") + 1] if "--user" in argv else None
        image = str(self.status.get("image", ""))
        base = ["docker", "run", "--rm", "--user", want, "--entrypoint", "id", image]
        uid, gid = (run([*base, flag], 120, self.local.env()) for flag in ("-u", "-g"))
        seen = f"{uid.output.strip()}:{gid.output.strip()}"
        ok = got == want and seen == want and uid.exit == 0 and gid.exit == 0
        self.record("docker run --user <uid>:<gid> id", uid.exit, ok, f"{got} / {seen} vs {want}")

    @_core.named("the writable home mount is a writable directory (rea state there if any)")
    def test_07_home_mount(self) -> None:
        self.need_install()
        mounts = [a.removesuffix(MOUNT) for a in self.dry_run_argv() if a.endswith(MOUNT)]
        path = mounts[0] if mounts else ""
        ok = bool(path) and os.path.isdir(path) and os.access(path, os.W_OK)
        files = sorted(os.listdir(path)) if ok else []
        note = "" if files else "rea wrote nothing there during initialize/tools-list"
        self.record("ls <rea home mount>", None, ok, f"{files[:20]}", note)


if __name__ == "__main__":
    unittest.main()
