#!/usr/bin/env python3
"""Fail if likely credentials appear in tracked files.

Standard library only. With ``--staged`` it scans only the files in the git index that are
added, copied or modified (``git diff --cached --name-only --diff-filter=ACM``); it reads their
working-tree content. Otherwise it scans files listed by ``git ls-files``; when git is
unavailable or nothing is tracked yet, it walks the tree instead. Files under
``tests/`` are skipped because tests may contain fabricated fixtures; the
summary reports how many were skipped. In the walk fallback (untracked
content) the directories ``.wev``, ``.remember`` and ``__pycache__`` are also
pruned; tracked files in them are scanned. Files larger than ``MAX_BYTES`` are
scanned by their first and last ``MAX_BYTES // 2`` bytes and reported as
truncated. UTF-16 files with a byte order mark are decoded.

Only file, line and pattern name are printed, never the matched value.

This is a tripwire, not a full scanner. It misses secrets without a
recognizable prefix, header or secret-looking variable name, low-entropy or
letters-only passwords, UTF-16 without a BOM, and encoded or split values.

Patterns are assembled from fragments so this file does not match itself.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

GIT_DIR = ".git"
UNTRACKED_SKIP_DIRS = frozenset({".remember", ".wev", "__pycache__"})
SKIP_PREFIXES = ("tests/",)
MAX_BYTES = 2_000_000
CHUNK_BYTES = 1_000_000
MIN_SECRET_LENGTH = 16
MIN_SECRET_ENTROPY = 3.5
MIN_URL_PASSWORD_LENGTH = 3

_DASHES = "-" * 5
_URLSAFE = r"[A-Za-z0-9_\-]"
_AWS_PREFIXES = (
    "AK" + "IA", "AS" + "IA", "AB" + "IA", "AC" + "CA", "AG" + "PA",
    "AI" + "DA", "AI" + "PA", "AN" + "PA", "AN" + "VA", "AR" + "OA",
)  # fmt: skip
_PLACEHOLDER_MARKERS = (
    "changeme", "change-me", "example", "xxxx", "your", "placeholder",
    "redacted", "dummy", "sample", "<", ">", "${", "{{", "$", "todo",
)  # fmt: skip
_PLACEHOLDER_WORDS = frozenset({"password", "pass", "passwd", "pwd", "secret", "user"})
_SECRET_VALUE_CHARS = re.compile(r"^[A-Za-z0-9+/=_\-.~!@#^*:]+$")
_SECRET_NAME = (
    r"(?:secret|passw(?:or)?d|pwd|api[_-]?key|auth[_-]?key|token|"
    r"private[_-]?key|access[_-]?key|credential)"
)

PATTERNS: dict[str, re.Pattern[str]] = {
    "pem-private-key": re.compile(
        _DASHES + "BEGIN" + r" (?:[A-Z0-9]+ )*PRIVATE" + " KEY" + _DASHES
    ),
    "pgp-private-key": re.compile(_DASHES + "BEGIN PGP" + " PRIVATE" + " KEY BLOCK" + _DASHES),
    "putty-private-key": re.compile("PuTTY" + "-User-Key" + r"-File-\d"),
    "aws-access-key-id": re.compile(r"\b(?:" + "|".join(_AWS_PREFIXES) + r")[0-9A-Z]{16}\b"),
    "google-api-key": re.compile(r"\bAI" + "za" + r"[0-9A-Za-z_\-]{35}(?![0-9A-Za-z_\-])"),
    "google-oauth-token": re.compile(r"\bya" + r"29\." + _URLSAFE + "{20,}"),
    "github-token": re.compile(r"\b(?:gh[pousr])_[A-Za-z0-9]{30,}\b"),
    "github-fine-grained-token": re.compile(r"\bgithub" + r"_pat_[A-Za-z0-9_]{22,}\b"),
    "gitlab-token": re.compile(r"\bgl" + "pat-" + _URLSAFE + "{20,}"),
    "slack-token": re.compile(r"\bxo" + r"x[abeoprs]-[A-Za-z0-9-]{10,}"),
    "stripe-key": re.compile(r"\b(?:(?:sk|rk)_li" + r"ve_|wh" + r"sec_)[A-Za-z0-9]{16,}"),
    "model-api-key": re.compile(
        r"\bsk" + r"-(?:ant-|proj-)?(?=[A-Za-z0-9_\-]*\d)" + _URLSAFE + "{20,}"
    ),
    "npm-token": re.compile(r"\bnpm" + r"_[A-Za-z0-9]{36}\b"),
    "pypi-token": re.compile(r"\bpypi" + "-AgEI" + _URLSAFE + "{20,}"),
    "huggingface-token": re.compile(r"\bhf" + r"_[A-Za-z0-9]{30,}\b"),
    "sendgrid-key": re.compile(r"\bSG" + r"\." + _URLSAFE + r"{16,}\." + _URLSAFE + "{16,}"),
    "digitalocean-token": re.compile(r"\bdop" + r"_v1_[a-f0-9]{32,}"),
    "jwt": re.compile(
        r"\bey" + r"J" + _URLSAFE + r"{5,}\.ey" + "J" + _URLSAFE + r"{5,}\." + _URLSAFE + "*"
    ),
    "webhook-url": re.compile(
        r"https://(?:hooks\." + r"slack\.com/(?:services|workflows)/[A-Za-z0-9/_\-]{20,}"
        r"|discord(?:app)?\." + r"com/api/webhooks/\d+/" + _URLSAFE + "{20,})"
    ),
}  # fmt: skip

_URL_CREDENTIALS = re.compile(
    r"\b[a-z][a-z0-9+.\-]{1,20}://[^\s/:@\"'<>]+:(?P<value>[^\s/@\"'<>]+)@[^\s/\"'<>]+",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9_.\-]*" + _SECRET_NAME + r"[A-Za-z0-9_.\-]*[\"']?\s*[:=]\s*"
    r"(?:\"(?P<dq>[^\"\n]+)\"|'(?P<sq>[^'\n]+)'|(?P<bare>[^\s\"',;]+))",
    re.IGNORECASE,
)


def shannon_entropy(value: str) -> float:
    """Return the Shannon entropy of ``value`` in bits per character."""
    if not value:
        return 0.0
    total = len(value)
    return -sum((n / total) * math.log2(n / total) for n in Counter(value).values())


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return lowered in _PLACEHOLDER_WORDS or any(m in lowered for m in _PLACEHOLDER_MARKERS)


def _looks_like_secret(value: str) -> bool:
    return (
        len(value) >= MIN_SECRET_LENGTH
        and "://" not in value
        and _SECRET_VALUE_CHARS.match(value) is not None
        and any(c.isdigit() for c in value)
        and any(c.isalpha() for c in value)
        and not _is_placeholder(value)
        and shannon_entropy(value) >= MIN_SECRET_ENTROPY
    )


def _url_password_ok(match: re.Match[str]) -> bool:
    value = match.group("value")
    return len(value) >= MIN_URL_PASSWORD_LENGTH and not _is_placeholder(value)


def _assignment_ok(match: re.Match[str]) -> bool:
    value = match.group("dq") or match.group("sq") or match.group("bare") or ""
    return _looks_like_secret(value)


CHECKED_PATTERNS: dict[str, tuple[re.Pattern[str], Callable[[re.Match[str]], bool]]] = {
    "url-credentials": (_URL_CREDENTIALS, _url_password_ok),
    "generic-secret-assignment": (_SECRET_ASSIGNMENT, _assignment_ok),
}


def _line_names(line: str) -> list[str]:
    names = [name for name, pattern in PATTERNS.items() if pattern.search(line)]
    for name, (pattern, accepts) in CHECKED_PATTERNS.items():
        if any(accepts(match) for match in pattern.finditer(line)):
            names.append(name)
    return names


def scan_text(text: str, first_line: int = 1) -> list[tuple[int, str]]:
    """Return ``(line_number, pattern_name)`` for every match in ``text``."""
    findings: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=first_line):
        findings.extend((number, name) for name in _line_names(line))
    return findings


class ScanReport(NamedTuple):
    """Result of scanning a tree."""

    findings: list[str]
    skipped_tests: int
    truncated: list[str]
    scanned: int


def _git_files(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
        )
    except OSError, subprocess.CalledProcessError:
        return None
    names = [n for n in result.stdout.decode("utf-8", "replace").split("\0") if n]
    return names or None


def staged_files(root: Path) -> list[str]:
    """Paths added, copied or modified in the index (``git diff --cached``), posix-style.

    Raises ``RuntimeError`` when git cannot answer: a pre-commit check must not pass by default.
    """
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"cannot list staged files: {error}") from error
    names = [n for n in result.stdout.decode("utf-8", "replace").split("\0") if n]
    return sorted(n.replace(os.sep, "/") for n in names)


def _walk_files(root: Path) -> Iterator[str]:
    pruned = UNTRACKED_SKIP_DIRS | {GIT_DIR}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in pruned]
        for name in files:
            yield os.path.relpath(os.path.join(current, name), root)


def list_files(root: Path) -> list[str]:
    """Return posix-style relative paths: tracked files, else a pruned walk."""
    tracked = _git_files(root)
    names = tracked if tracked is not None else list(_walk_files(root))
    posix = (n.replace(os.sep, "/") for n in names)
    return sorted(n for n in posix if GIT_DIR not in Path(n).parts)


def _detect_codec(head: bytes) -> str:
    if head.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if head.startswith(b"\xfe\xff"):
        return "utf-16-be"
    return "utf-8"


def _count_newlines(path: Path, end: int) -> int:
    count = 0
    remaining = end
    with path.open("rb") as handle:
        while remaining > 0:
            block = handle.read(min(CHUNK_BYTES, remaining))
            if not block:
                break
            count += block.count(b"\n")
            remaining -= len(block)
    return count


def _read_segments(path: Path, size: int) -> tuple[list[tuple[str, int]], bool]:
    """Return ``(text, first_line)`` segments and whether the file was truncated."""
    with path.open("rb") as handle:
        if size <= MAX_BYTES:
            data = handle.read()
            return [(data.decode(_detect_codec(data), "replace"), 1)], False
        half = MAX_BYTES // 2
        head = handle.read(half)
        codec = _detect_codec(head)
        tail_start = (size - half) & ~1
        handle.seek(tail_start)
        tail = handle.read()
    base = _count_newlines(path, tail_start) + 1
    return [(head.decode(codec, "replace"), 1), (tail.decode(codec, "replace"), base)], True


def scan_report(root: Path, names: list[str] | None = None) -> ScanReport:
    """Scan ``names`` (default: the whole tree) under ``root``; return findings and bookkeeping."""
    findings: list[str] = []
    truncated: list[str] = []
    skipped_tests = scanned = 0
    for relative in list_files(root) if names is None else names:
        if relative.startswith(SKIP_PREFIXES):
            skipped_tests += 1
            continue
        path = root / relative
        try:
            if not path.is_file():
                continue
            segments, was_truncated = _read_segments(path, path.stat().st_size)
        except OSError as error:
            findings.append(f"{relative}: unreadable ({error.strerror})")
            continue
        scanned += 1
        if was_truncated:
            truncated.append(relative)
        for text, first_line in segments:
            findings.extend(f"{relative}:{n}: {name}" for n, name in scan_text(text, first_line))
    return ScanReport(findings, skipped_tests, truncated, scanned)


def scan_tree(root: Path) -> list[str]:
    """Return human-readable findings for the tree under ``root``."""
    return scan_report(root).findings


def main(argv: list[str]) -> int:
    args = argv[1:]
    staged = "--staged" in args
    positional = [a for a in args if a != "--staged"]
    root = Path(positional[0]) if positional else Path.cwd()
    if staged:
        try:
            report = scan_report(root, staged_files(root))
        except RuntimeError as error:
            print(f"scan_secrets: {error}", file=sys.stderr)
            return 2
    else:
        report = scan_report(root)
    if report.findings:
        print("Possible credentials found (values not printed):")
        for item in report.findings:
            print(f"  {item}")
    else:
        print("scan_secrets: no credential patterns found.")
    for name in report.truncated:
        print(
            f"  note: {name} exceeds {MAX_BYTES} bytes; only its first and last halves were scanned"
        )
    print(
        f"scan_secrets: {report.scanned} file(s) scanned, "
        f"{report.skipped_tests} file(s) under tests/ skipped, "
        f"{len(report.truncated)} truncated."
    )
    return 1 if report.findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
