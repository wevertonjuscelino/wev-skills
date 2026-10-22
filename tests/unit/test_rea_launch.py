"""The argv ``wev rea serve`` builds: exact for both modes, hostile inputs refused."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.rea import launch
from wev_skills.rea.config import ReaConfig
from wev_skills.third_party.state import SourceState, State


class ServeArgvTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.work = self.home / "proj"
        self.work.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rea_home = self.root / "reahome"

    def argv(
        self, cfg: ReaConfig, version: str = "6.7.0", cwd: Path | None = None
    ) -> tuple[str, ...]:
        return launch.serve_argv(
            cfg, version, cwd or self.work, self.rea_home, "/bin/docker", "/bin/npx"
        )

    def test_direct(self) -> None:
        self.assertEqual(
            self.argv(ReaConfig("direct")),
            ("/bin/npx", "-y", "rea-agents" + "@6.7.0", "mcp"),
        )

    def test_isolated_exact(self) -> None:
        expected = (
            "/bin/docker", "run", "--rm", "-i", "--init",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--network", "bridge",
            "--volume", f"{self.work}:{self.work}:ro",
            "--workdir", str(self.work),
            "--volume", f"{self.rea_home}:/opt/rea-home",
            "wev-rea:6.7.0",
        )  # fmt: skip
        self.assertEqual(self.argv(ReaConfig("isolated")), expected)

    def test_hostile_versions_refused(self) -> None:
        hostile = ("6.7.0 && rm -rf", "6.7.0;sh", "", "..", "a b", "$(x)", "x\n")
        for version in (*hostile, "latest", "next", "6.7", "-rf", "6.7.0\n", "1.2.3-"):
            for mode in ("direct", "isolated"):
                with self.subTest(version=version, mode=mode), self.assertRaises(ValidationError):
                    self.argv(ReaConfig(mode), version)  # type: ignore[arg-type]

    def test_semver_versions_accepted(self) -> None:
        for version in ("6.7.0", "6.7.0-beta.1"):
            with self.subTest(version=version):
                self.assertEqual(
                    self.argv(ReaConfig("direct"), version)[2], "rea-agents" + "@" + version
                )

    def test_path_with_mount_syntax_refused(self) -> None:
        for name in ("a:b", "a,b", "a\nb", "a\tb"):
            work = self.home / name
            work.mkdir()
            with self.subTest(cwd=name), self.assertRaises(ValidationError) as ctx:
                self.argv(ReaConfig("isolated"), cwd=work)
            self.assertEqual(ctx.exception.code, "rea_path_refused")

    def test_rea_home_must_be_absolute_and_plain(self) -> None:
        for bad in (Path("reahome"), Path("/tmp/a:b"), Path("/tmp/a,b")):
            with self.subTest(home=str(bad)), self.assertRaises(ValidationError) as ctx:
                launch.serve_argv(ReaConfig("isolated"), "6.7.0", self.work, bad, "/bin/docker")
            self.assertEqual(ctx.exception.code, "rea_path_refused")

    def test_cwd_refused(self) -> None:
        for cwd in (Path("/"), self.home, self.root):
            with self.subTest(cwd=str(cwd)):
                with self.assertRaises(ValidationError) as ctx:
                    self.argv(ReaConfig("isolated"), cwd=cwd)
                self.assertEqual(ctx.exception.code, "rea_cwd_refused")

    def test_cwd_refusal_does_not_apply_to_direct(self) -> None:
        self.assertEqual(len(self.argv(ReaConfig("direct"), cwd=Path("/"))), 4)

    def test_cwd_is_resolved(self) -> None:
        link = self.root / "link"
        link.symlink_to(self.work)
        argv = self.argv(ReaConfig("isolated"), cwd=link)
        self.assertIn(f"{self.work}:{self.work}:ro", argv)

    def test_pinned_version(self) -> None:
        state = State({"rea": SourceState(active="6.7.0")})
        self.assertEqual(launch.pinned_version(state), "6.7.0")
        for empty in (State({}), State({"rea": SourceState()})):
            with self.subTest(state=empty), self.assertRaises(StateConflict) as ctx:
                launch.pinned_version(empty)
            self.assertEqual(ctx.exception.code, "rea_not_installed")

    def test_serve_execs_the_argv(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        def fake(file: str, args: list[str]) -> None:
            calls.append((file, args))
            raise SystemExit(0)

        with self.assertRaises(SystemExit):
            launch.serve(("/bin/npx", "-y", "x"), execvp=fake)  # type: ignore[arg-type]
        self.assertEqual(calls, [("/bin/npx", ["/bin/npx", "-y", "x"])])


if __name__ == "__main__":
    unittest.main()
