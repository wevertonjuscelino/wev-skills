#!/usr/bin/env python3
"""Compute the wev-skills version ``X.Y.Z`` from git history. Standard library only.

The scheme (see docs/guides/maintaining.md):

* X counts releases to ``main``: the major of the latest ``vX.Y.Z`` tag reachable from the ref.
* Y counts the pull requests merged into ``dev`` since that tag (merge commits on the first-parent
  chain from the ref back to the tag).
* Z counts the commits of the pull request in progress. When the ref sits on a merge, Z is the
  number of commits that merge brought in.

Versions are computed, never written per commit; files change only at release.

Usage: ``versioning.py [--ref REF] [--next-release | --latest-tag]``. Prints ``X.Y.Z`` (no leading
``v``); ``--latest-tag`` prints the name of the latest release tag, or nothing when there is none.
Exit codes: 0 ok, 1 git failure or unknown ref, 2 usage error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class VersioningError(Exception):
    """A git command failed or the history cannot be read."""


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=False
        )
    except OSError as error:
        raise VersioningError(f"cannot run git: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise VersioningError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def latest_release_tag(repo: Path, ref: str) -> tuple[str, int] | None:
    """The highest ``vX.Y.Z`` tag reachable from ``ref``, as ``(name, major)``."""
    names = _git(repo, "tag", "--merged", ref, "--list", "v[0-9]*").split()
    found: list[tuple[tuple[int, int, int], str]] = []
    for name in names:
        match = TAG_PATTERN.match(name)
        if match:
            found.append(((int(match[1]), int(match[2]), int(match[3])), name))
    if not found:
        return None
    key, name = max(found)
    return name, key[0]


def _first_parent_chain(repo: Path, ref: str, base: str | None) -> list[tuple[str, int]]:
    """Commits from ``ref`` back to ``base`` (exclusive), newest first, as (sha, parent count)."""
    spec = f"{base}..{ref}" if base else ref
    out = _git(repo, "rev-list", "--first-parent", "--parents", spec)
    return [(fields[0], len(fields) - 1) for fields in (line.split() for line in out.splitlines())]


def compute(repo: Path, ref: str = "HEAD") -> Version:
    """The version of ``ref`` under the scheme above."""
    tag = latest_release_tag(repo, ref)
    major = tag[1] if tag else 0
    chain = _first_parent_chain(repo, ref, tag[0] if tag else None)
    merges = [sha for sha, parents in chain if parents > 1]
    loose = 0
    for _sha, parents in chain:
        if parents > 1:
            break
        loose += 1
    if loose > 0:
        return Version(major, len(merges) + 1, loose)
    if not merges:
        return Version(major, 0, 0)
    merge = merges[0]
    brought = _git(repo, "rev-list", "--count", "--no-merges", f"{merge}^1..{merge}^2")
    return Version(major, len(merges), int(brought.strip()))


def next_release(repo: Path, ref: str = "HEAD") -> Version:
    """The version the next dev-to-main merge publishes: ``(X+1).0.0``."""
    tag = latest_release_tag(repo, ref)
    return Version((tag[1] if tag else 0) + 1, 0, 0)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Compute the wev-skills version from git history.")
    parser.add_argument("--ref", default="HEAD", help="commit-ish to version (default HEAD)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--next-release", action="store_true", help="print (X+1).0.0")
    mode.add_argument("--latest-tag", action="store_true", help="print the latest release tag")
    parser.add_argument("--repo", default=".", help="repository directory (default .)")
    args = parser.parse_args(argv[1:])
    repo = Path(args.repo)
    try:
        if args.latest_tag:
            tag = latest_release_tag(repo, args.ref)
            print(tag[0] if tag else "")
            return 0
        version = next_release(repo, args.ref) if args.next_release else compute(repo, args.ref)
    except VersioningError as error:
        print(f"versioning: {error}", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
