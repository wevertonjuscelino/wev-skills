"""Ask the registries which version of each third-party source is newest. Answers are untrusted."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from wev_skills import i18n
from wev_skills.security.untrusted import sanitize
from wev_skills.third_party.sources import SOURCES, Source
from wev_skills.third_party.state import VERSION_RE, SourceState, State

Opener = Callable[[str, float], bytes]
BASE_URLS: Mapping[str, str] = {
    "npm": "https://registry.npmjs.org",
    "github": "https://api.github.com",
}
REQUEST_TIMEOUT = 5.0
DAILY_BUDGET = 10.0
INTERVAL = timedelta(days=1)
MAX_BODY = 4 * 1024 * 1024


class CheckFailed(Exception):
    """One source could not be checked; ``code`` says why. Nothing is recorded for it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    tarball: str | None


@dataclass(frozen=True)
class Update:
    source: str
    active: str | None
    latest: str
    url: str


@dataclass(frozen=True)
class Outcome:
    state: State
    updates: tuple[Update, ...]
    checked: tuple[str, ...]
    failed: tuple[Mapping[str, str], ...]


def fetch(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(  # noqa: S310 - https URLs from the fixed registry
        url, headers={"Accept": "application/json", "User-Agent": "wev-skills"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body: bytes = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise CheckFailed("too_large")
    return body


def get_json(opener: Opener, url: str) -> object:
    try:
        return json.loads(opener(url, REQUEST_TIMEOUT))
    except CheckFailed:
        raise
    except urllib.error.HTTPError as exc:
        exc.close()
        raise CheckFailed(f"http_{exc.code}") from exc
    except (ValueError, RecursionError) as exc:  # bad JSON, bad UTF-8, absurd nesting
        raise CheckFailed("bad_shape") from exc
    except OSError as exc:  # network, timeout
        raise CheckFailed("unreachable") from exc


def _text(doc: object, *keys: str) -> str:
    for key in keys:
        if not isinstance(doc, dict) or key not in doc:
            raise CheckFailed("bad_shape")
        doc = doc[key]
    if not isinstance(doc, str):
        raise CheckFailed("bad_shape")
    return doc


def _version(value: str) -> str:
    if not VERSION_RE.fullmatch(value):
        raise CheckFailed("bad_version")
    return value


def _npm(src: Source, opener: Opener, base: str) -> Release:
    doc = get_json(opener, f"{base}/{src.package}")
    version = _version(_text(doc, "dist-tags", "latest"))
    try:
        tarball: str | None = _text(doc, "versions", version, "dist", "tarball")
    except CheckFailed:
        tarball = None
    return Release(version, src.changelog.format(version=version), tarball)


def _github_head(src: Source, opener: Opener, base: str) -> Release:
    doc = get_json(opener, f"{base}/repos/{src.package}/commits/HEAD")
    sha = _version(_text(doc, "sha"))
    return Release(
        sha[:12],
        f"https://github.com/{src.package}/commit/{sha}",
        f"{base}/repos/{src.package}/tarball/{sha}",
    )


def _github(src: Source, opener: Opener, base: str) -> Release:
    try:
        doc = get_json(opener, f"{base}/repos/{src.package}/releases/latest")
    except CheckFailed as exc:
        if exc.code != "http_404":
            raise
        return _github_head(src, opener, base)
    version = _version(_text(doc, "tag_name"))
    tarball = doc.get("tarball_url") if isinstance(doc, dict) else None
    link = src.changelog.format(version=version)  # never the answer's own html_url
    return Release(version, link, tarball if isinstance(tarball, str) else None)


def latest(source: Source, opener: Opener, base_urls: Mapping[str, str] = BASE_URLS) -> Release:
    base = base_urls.get(source.kind, BASE_URLS[source.kind]).rstrip("/")
    return (_npm if source.kind == "npm" else _github)(source, opener, base)


def is_due(state: State, now: datetime) -> bool:
    if state.checked_at is None:
        return True
    try:
        return now - datetime.fromisoformat(state.checked_at) >= INTERVAL
    except ValueError, TypeError:  # a marker that cannot be read counts as never checked
        return True


def _checked(item: SourceState, release: Release, now: datetime) -> SourceState:
    return replace(item, last_check=now.isoformat(), latest_seen=release.version)


def scan(
    state: State, now: datetime, opener: Opener, base_urls: Mapping[str, str], *, force: bool
) -> Outcome:
    due = force or is_due(state, now)
    sources = dict(state.sources)
    updates: list[Update] = []
    checked: list[str] = []
    failed: list[Mapping[str, str]] = []
    for src in SOURCES:
        item = sources.get(src.name, SourceState())
        if item.frozen:
            continue
        try:
            release = latest(src, opener, base_urls)
        except CheckFailed as exc:
            failed.append({"source": src.name, "code": exc.code})
            continue
        sources[src.name] = _checked(item, release, now)
        checked.append(src.name)
        if item.active and release.version not in (item.active, item.declined):
            updates.append(Update(src.name, item.active, release.version, release.url))
    marker = now.isoformat() if due and not failed else state.checked_at
    return Outcome(State(sources, marker), tuple(updates), tuple(checked), tuple(failed))


def check(
    state: State, now: datetime, opener: Opener, base_urls: Mapping[str, str], *, force: bool
) -> tuple[State, list[Update]]:
    outcome = scan(state, now, opener, base_urls, force=force)
    return outcome.state, list(outcome.updates)


def daily_context(updates: Sequence[Update]) -> str:
    items = "; ".join(sanitize(f"{u.source} {u.active} -> {u.latest} ({u.url})") for u in updates)
    return i18n.t("skills.hook.updates", items=items)
