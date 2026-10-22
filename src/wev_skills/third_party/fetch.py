"""Download a third-party release and unpack it next to the others. The archive is untrusted."""

from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from wev_skills.core.fsutil import atomic_write_text
from wev_skills.core.ports import Runner
from wev_skills.third_party.check import CheckFailed, Opener, Release
from wev_skills.third_party.sources import Source
from wev_skills.third_party.state import VERSION_RE

MAX_ARCHIVE = 50 * 1024 * 1024
DOWNLOAD_TIMEOUT = 120.0
ALLOWED_HOSTS: dict[str, frozenset[str]] = {
    "github": frozenset({"api.github.com", "codeload.github.com", "github.com"}),
    "npm": frozenset({"registry.npmjs.org"}),
}
NPM_REF = "npm-ref.json"


def mcp_argv(version: str) -> tuple[str, ...]:
    return ("npx", "-y", f"rea-agents@{version}", "mcp")


def _allowed(kind: str, url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS[kind]


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """GitHub answers a tarball URL with a redirect; it may only go to another allowed host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not _allowed("github", newurl):
            raise CheckFailed("bad_tarball_url")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "wev-skills"})  # noqa: S310
    opener = urllib.request.build_opener(_CheckedRedirects)
    with opener.open(request, timeout=timeout) as response:
        body: bytes = response.read(MAX_ARCHIVE + 1)
    if len(body) > MAX_ARCHIVE:
        raise CheckFailed("too_large")
    return body


def _inside(root: PurePosixPath, target: PurePosixPath) -> bool:
    parts: list[str] = []
    for part in (root / target).parts[len(root.parts) :]:
        if part == "..":
            if not parts:
                return False
            parts.pop()
        elif part != ".":
            parts.append(part)
    return True


def _check_member(member: tarfile.TarInfo) -> None:
    name = PurePosixPath(member.name)
    unsafe = name.is_absolute() or ".." in name.parts or member.isdev() or member.isfifo()
    root = PurePosixPath("/root")
    if member.issym():
        link = PurePosixPath(member.linkname)
        unsafe = unsafe or link.is_absolute() or not _inside(root, name.parent / link)
    elif member.islnk():
        link = PurePosixPath(member.linkname)
        unsafe = unsafe or link.is_absolute() or not _inside(root, link)
    if unsafe:
        raise CheckFailed("unsafe_member")


def _check_members(archive: tarfile.TarFile) -> None:
    total = 0
    for member in archive.getmembers():
        _check_member(member)
        total += max(member.size, 0)
        if total > MAX_ARCHIVE:
            raise CheckFailed("too_large")


def _unpack(data: bytes, work: Path) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            _check_members(archive)
            archive.extractall(path=work, filter="data")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise CheckFailed("bad_archive") from exc
    base = work.resolve()
    for path in work.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(base):
            raise CheckFailed("unsafe_member")


def _place(work: Path, target: Path) -> None:
    """Move the archive's single top-level directory (GitHub adds one) to ``target``."""
    entries = list(work.iterdir())
    only = entries[0] if len(entries) == 1 and entries[0].is_dir() else work
    os.replace(only, target)


def _target(source: Source, version: str, home: Path) -> Path:
    if not VERSION_RE.fullmatch(version):
        raise CheckFailed("bad_version")
    base = home / source.name
    target = base / version
    assert target.resolve().is_relative_to(base.resolve()), target  # noqa: S101 - defensive
    return target


def _install_github(release: Release, target: Path, opener: Opener) -> None:
    if release.tarball is None or not _allowed("github", release.tarball):
        raise CheckFailed("bad_tarball_url")
    data = opener(release.tarball, DOWNLOAD_TIMEOUT)
    if len(data) > MAX_ARCHIVE:
        raise CheckFailed("too_large")
    work = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    try:
        work.mkdir(parents=True)
        _unpack(data, work)
        _place(work, target)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _install_npm(source: Source, release: Release, target: Path) -> None:
    ref = {"package": source.package, "version": release.version}
    work = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    try:
        atomic_write_text(work / NPM_REF, json.dumps(ref, indent=2) + "\n")
        os.replace(work, target)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def install_version(
    source: Source, release: Release, home: Path, opener: Opener, runner: Runner
) -> Path:
    """Put ``release`` under ``home/<source>/<version>`` without making it active. Nothing from
    it is imported or run; ``runner`` is for the health check that follows (Task 4)."""
    target = _target(source, release.version, home)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.kind == "github":
        _install_github(release, target, opener)
    else:
        _install_npm(source, release, target)
    return target
