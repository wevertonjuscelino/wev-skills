"""Download a third-party release and unpack it next to the others. The archive is untrusted."""

from __future__ import annotations

import io
import json
import os
import posixpath
import shutil
import tarfile
import time
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
MAX_MEMBERS = 10_000
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


CHUNK = 64 * 1024


def download(url: str, timeout: float) -> bytes:
    """The body of ``url``; ``timeout`` bounds the whole download, not each socket read."""
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(url, headers={"User-Agent": "wev-skills"})  # noqa: S310
    opener = urllib.request.build_opener(_CheckedRedirects)
    chunks: list[bytes] = []
    size = 0
    with opener.open(request, timeout=timeout) as response:
        while chunk := response.read1(CHUNK):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_ARCHIVE:
                raise CheckFailed("too_large")
            if time.monotonic() > deadline:
                raise CheckFailed("timed_out")
    return b"".join(chunks)


def _escapes_top(member: tarfile.TarInfo) -> bool:
    """A symlink target is read from the link's own directory and must stay in the top directory."""
    if PurePosixPath(member.linkname).is_absolute():
        return True
    parts = PurePosixPath(member.name).parts
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
    return not parts or not (resolved == parts[0] or resolved.startswith(f"{parts[0]}/"))


def _check_member(member: tarfile.TarInfo) -> None:
    name = PurePosixPath(member.name)
    unsafe = name.is_absolute() or ".." in name.parts or member.isdev() or member.isfifo()
    if member.islnk():  # a hard link names a path from the archive root
        link = PurePosixPath(member.linkname)
        unsafe = unsafe or link.is_absolute() or ".." in link.parts
    elif member.issym():
        unsafe = unsafe or _escapes_top(member)
    if unsafe:
        raise CheckFailed("unsafe_member")


def _check_members(archive: tarfile.TarFile) -> None:
    """Walk the headers one by one, stopping at the first limit, before anything is written."""
    total = 0
    for count, member in enumerate(archive, start=1):
        if count > MAX_MEMBERS:
            raise CheckFailed("too_many_members")
        _check_member(member)
        total += max(member.size, 0)
        if total > MAX_ARCHIVE:
            raise CheckFailed("too_large")


def _single_top(work: Path) -> Path:
    """GitHub wraps the files in one directory; anything else is not a release tarball."""
    entries = list(work.iterdir())
    if any(entry.is_symlink() for entry in entries):
        raise CheckFailed("unsafe_member")
    if len(entries) != 1 or not entries[0].is_dir():
        raise CheckFailed("bad_archive")
    return entries[0]


def _check_links(top: Path) -> None:
    """Every link must land strictly inside ``top``, the directory that becomes the version."""
    base = top.resolve()
    for path in top.rglob("*"):
        if path.is_symlink():
            target = path.resolve()
            if target == base or not target.is_relative_to(base):
                raise CheckFailed("unsafe_member")


def _unpack(data: bytes, work: Path) -> Path:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            _check_members(archive)
            archive.extractall(path=work, filter="data")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise CheckFailed("bad_archive") from exc
    top = _single_top(work)
    _check_links(top)
    return top


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
    try:
        data = opener(release.tarball, DOWNLOAD_TIMEOUT)
    except CheckFailed:
        raise
    except OSError as exc:  # URLError, HTTPError, timeouts
        raise CheckFailed("unreachable") from exc
    if len(data) > MAX_ARCHIVE:
        raise CheckFailed("too_large")
    work = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    try:
        work.mkdir(parents=True)
        os.replace(_unpack(data, work), target)
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
