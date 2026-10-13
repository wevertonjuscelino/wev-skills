"""Message catalogs: ``locales/<domain>.<lang>.json`` files merged per language."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache
from pathlib import Path

from wev_skills.core.errors import ValidationError

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "pt-BR")

_active: ContextVar[str | None] = ContextVar("wev_active_language", default=None)
_configured: ContextVar[str | None] = ContextVar("wev_config_language", default=None)


@contextmanager
def use_language(lang: str | None) -> Iterator[None]:
    """Make ``lang`` the explicit language for ``t``/``resolve_language`` inside the block."""
    token = _active.set(_normalize(lang) if lang else None)
    try:
        yield
    finally:
        _active.reset(token)


@contextmanager
def use_config_language(lang: str | None) -> Iterator[None]:
    """Make ``lang``, a ``language`` a configuration sets explicitly, the language that
    ``resolve_language`` falls back to after ``WEV_LANG`` and before ``LANG``."""
    token = _configured.set(_normalize(lang) if lang else None)
    try:
        yield
    finally:
        _configured.reset(token)


def resolve_language(explicit: str | None = None) -> str:
    """Order: explicit argument, active ``use_language`` block (``--lang``), WEV_LANG, the
    ``use_config_language`` block, LANG ``pt*``, ``en``."""
    if explicit:
        return _normalize(explicit)
    active = _active.get()
    if active:
        return active
    wev_lang = os.environ.get("WEV_LANG")
    if wev_lang:
        return _normalize(wev_lang)
    configured = _configured.get()
    if configured:
        return configured
    if os.environ.get("LANG", "").lower().startswith("pt"):
        return "pt-BR"
    return DEFAULT_LANG


def _normalize(value: str) -> str:
    lowered = value.strip().lower().replace("_", "-")
    if lowered.startswith("pt"):
        return "pt-BR"
    if lowered.startswith("en"):
        return "en"
    raise ValidationError(
        "unsupported_language",
        f"unsupported language {value!r}; use one of {list(SUPPORTED_LANGS)}",
        {"supported": list(SUPPORTED_LANGS)},
    )


def catalog_files(lang: str) -> list[Path]:
    """Every ``<domain>.<lang>.json`` file for ``lang``, sorted by name."""
    return sorted(LOCALES_DIR.glob(f"*.{lang}.json"))


@cache
def _catalog(lang: str) -> Mapping[str, str]:
    merged: dict[str, str] = {}
    for path in catalog_files(lang):
        merged.update(json.loads(path.read_text(encoding="utf-8")))
    return merged


def clear_cache() -> None:
    _catalog.cache_clear()


def t(key: str, lang: str | None = None, /, **params: object) -> str:
    """Translate ``key``; fall back to English, then to the key itself."""
    language = resolve_language(lang)
    template = _catalog(language).get(key)
    if template is None and language != DEFAULT_LANG:
        template = _catalog(DEFAULT_LANG).get(key)
    if template is None:
        return key
    try:
        return template.format(**params)
    except KeyError, IndexError:
        return template
