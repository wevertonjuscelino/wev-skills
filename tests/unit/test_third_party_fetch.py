"""Download and side-by-side install of third-party releases. Archives are built in memory."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from wev_skills import cli
from wev_skills.third_party import check, fetch, sources

GH = sources.source("agent-skills")
NPM = sources.source("rea")
URL = "https://api.github.com/repos/addyosmani/agent-skills/tarball/v1.0.0"


def tarball(build: Callable[[tarfile.TarFile], None]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        build(archive)
    return buf.getvalue()


def add_file(archive: tarfile.TarFile, name: str, data: bytes = b"x") -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def add_link(archive: tarfile.TarFile, name: str, target: str, *, hard: bool = False) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
    info.linkname = target
    archive.addfile(info)


def good(archive: tarfile.TarFile) -> None:
    add_file(archive, "addyosmani-agent-skills-abc/skills/a/SKILL.md", b"# a")
    add_file(archive, "addyosmani-agent-skills-abc/README.md")


class Runner:
    def run(self, *_args: object) -> object:
        raise AssertionError("install runs nothing")


class FetchCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "third-party"
        self.calls: list[str] = []

    def opener(self, data: bytes) -> check.Opener:
        def get(url: str, timeout: float) -> bytes:
            self.calls.append(url)
            self.assertEqual(timeout, fetch.DOWNLOAD_TIMEOUT)
            return data

        return get

    def install(self, data: bytes, url: str = URL, version: str = "v1.0.0") -> Path:
        release = check.Release(version, "https://c", url)
        return fetch.install_version(GH, release, self.home, self.opener(data), Runner())  # type: ignore[arg-type]

    def refused(self, data: bytes, code: str, url: str = URL) -> None:
        with self.assertRaises(check.CheckFailed) as caught:
            self.install(data, url)
        self.assertEqual(caught.exception.code, code)
        base = self.home / "agent-skills"
        self.assertEqual(list(base.iterdir()) if base.exists() else [], [])

    def test_github_tarball_extracted_under_version_dir(self) -> None:
        path = self.install(tarball(good))
        self.assertEqual(path, self.home / "agent-skills" / "v1.0.0")
        self.assertEqual((path / "skills/a/SKILL.md").read_text(), "# a")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["v1.0.0"])

    def test_member_outside_target_refused_nothing_left(self) -> None:
        cases = {
            "dotdot": lambda a: add_file(a, "../x"),
            "nested dotdot": lambda a: add_file(a, "top/../../x"),
            "absolute": lambda a: add_file(a, "/tmp/x"),
            "symlink to /etc": lambda a: add_link(a, "top/l", "/etc"),
            "symlink up": lambda a: add_link(a, "top/l", "../../etc"),
            "hardlink absolute": lambda a: add_link(a, "top/h", "/etc/passwd", hard=True),
            "hardlink up": lambda a: add_link(a, "top/h", "../x", hard=True),
        }
        for label, build in cases.items():
            with self.subTest(label):
                self.refused(tarball(build), "unsafe_member")

    def test_device_member_refused(self) -> None:
        def build(archive: tarfile.TarFile) -> None:
            info = tarfile.TarInfo("top/dev")
            info.type = tarfile.CHRTYPE
            archive.addfile(info)

        self.refused(tarball(build), "unsafe_member")

    def test_link_inside_the_archive_is_allowed(self) -> None:
        def build(archive: tarfile.TarFile) -> None:
            add_file(archive, "top/a")
            add_link(archive, "top/l", "a")

        self.assertTrue((self.install(tarball(build)) / "l").is_symlink())

    def test_not_an_archive_refused(self) -> None:
        self.refused(b"<html>no</html>", "bad_archive")

    def test_too_large_refused(self) -> None:
        with mock.patch.object(fetch, "MAX_ARCHIVE", 10):
            self.refused(b"x" * 11, "too_large")
            self.refused(tarball(lambda a: add_file(a, "top/big", b"y" * 11)), "too_large")

    def test_bad_tarball_url_refused_before_download(self) -> None:
        urls = (
            "http://api.github.com/x",
            "https://evil.example/x",
            "file:///etc/passwd",
            "https://api.github.com.evil.example/x",
            "https://evil.example:443/x",
        )
        for url in urls:
            with self.subTest(url=url):
                self.refused(tarball(good), "bad_tarball_url", url)
        self.assertEqual(self.calls, [])
        release = check.Release("v1.0.0", "https://c", None)
        with self.assertRaises(check.CheckFailed):
            fetch.install_version(GH, release, self.home, self.opener(b""), Runner())  # type: ignore[arg-type]

    def test_existing_version_not_redownloaded(self) -> None:
        first = self.install(tarball(good))
        self.assertEqual(self.install(tarball(good)), first)
        self.assertEqual(len(self.calls), 1)

    def test_version_cannot_leave_the_source_directory(self) -> None:
        for version in ("..", ".", "a/b", "../x", ""):
            with self.subTest(version=version), self.assertRaises(check.CheckFailed):
                self.install(tarball(good), version=version)
        self.assertFalse((self.home.parent / "x").exists())

    def test_redirect_to_another_host_refused(self) -> None:
        handler = fetch._CheckedRedirects()
        with self.assertRaises(check.CheckFailed):
            handler.redirect_request(mock.Mock(), None, 302, "", {}, "https://evil.example/x")

    def test_npm_install_writes_ref_only(self) -> None:
        release = check.Release("2.0.0", "https://c", "https://registry.npmjs.org/x.tgz")
        path = fetch.install_version(NPM, release, self.home, self.opener(b""), Runner())  # type: ignore[arg-type]
        self.assertEqual(path, self.home / "rea" / "2.0.0")
        self.assertEqual(
            json.loads((path / "npm-ref.json").read_text()),
            {"package": "rea-agents", "version": "2.0.0"},
        )
        self.assertEqual([p.name for p in path.iterdir()], ["npm-ref.json"])
        self.assertEqual(self.calls, [])

    def test_mcp_argv(self) -> None:
        pinned = "rea-agents" + "@" + "2.0.0"
        self.assertEqual(fetch.mcp_argv("2.0.0"), ("npx", "-y", pinned, "mcp"))


class InstallCliCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.dir), "XDG_DATA_HOME": str(self.dir / "data")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *argv: str) -> tuple[int, dict[str, object]]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--lang", "en", *argv])
        return code, json.loads(out.getvalue() or "{}")

    def test_install_version_leaves_it_inactive(self) -> None:
        with mock.patch.object(fetch, "download", return_value=tarball(good)) as got:
            code, payload = self.run_main(
                "skills", "install", "agent-skills", "--version", "v1.0.0"
            )
        self.assertEqual(code, 0)
        path = self.dir / "data/wev-skills/third-party/agent-skills/v1.0.0"
        self.assertEqual(
            payload,
            {"source": "agent-skills", "version": "v1.0.0", "path": str(path), "active": False},
        )
        self.assertTrue((path / "skills/a/SKILL.md").is_file())
        self.assertEqual(got.call_args.args[0], URL)
        self.assertFalse((path.parent / "current").exists())

    def test_bad_version_and_failure_exit_codes(self) -> None:
        code, _ = self.run_main("skills", "install", "agent-skills", "--version", "../x")
        self.assertEqual(code, 2)
        with mock.patch.object(fetch, "download", return_value=b"nope"):
            code, _ = self.run_main("skills", "install", "agent-skills", "--version", "v1")
        self.assertEqual(code, 8)
        self.assertEqual(self.run_main("skills", "install", "nope")[0], 2)

    def test_install_defaults_to_latest(self) -> None:
        release = check.Release("v9.9.9", "https://c", "https://codeload.github.com/x")
        with (
            mock.patch.object(check, "latest", return_value=release),
            mock.patch.object(fetch, "download", return_value=tarball(good)),
        ):
            code, payload = self.run_main("skills", "install", "agent-skills")
        self.assertEqual((code, payload["version"]), (0, "v9.9.9"))
