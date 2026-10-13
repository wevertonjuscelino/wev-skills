"""The allowed SSH aliases. A host that is not listed is refused, never guessed."""

from __future__ import annotations

import re
from collections.abc import Iterable

from wev_skills import i18n
from wev_skills.config import RemoteConfig, RemoteHost
from wev_skills.core.errors import PermissionDenied, ValidationError

MAX_ALIAS_LENGTH = 253
PRODUCTION_LABELS = frozenset({"production", "prod"})
_ALIAS_RE = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*")


MAX_SHOWN_ALIAS = 80


def shown_alias(alias: object) -> str:
    """``alias`` as it appears in an error: the text itself, without quotes, control
    characters escaped and long values cut. A value that is not text shows as its type."""
    if not isinstance(alias, str):
        return f"<{type(alias).__name__}>"
    escaped = alias.encode("unicode_escape").decode("ascii")
    return escaped[:MAX_SHOWN_ALIAS]


def validate_alias(alias: object) -> str:
    """Return ``alias`` when ssh can only read it as a host name, else raise.

    Letters, digits, dot, underscore and hyphen only, never starting with a hyphen,
    so the value cannot be parsed as an option, a ``user@host`` pair, a port, a path
    or shell syntax.
    """
    if (
        not isinstance(alias, str)
        or len(alias) > MAX_ALIAS_LENGTH
        or _ALIAS_RE.fullmatch(alias) is None
    ):
        raise ValidationError(
            "remote_invalid_alias",
            i18n.t("remote.error.invalid_alias"),
            {"alias": shown_alias(alias)},
        )
    return alias


def is_production(host: RemoteHost) -> bool:
    return host.environment.strip().lower() in PRODUCTION_LABELS


class Inventory:
    """Immutable set of hosts taken from configuration."""

    def __init__(self, hosts: Iterable[RemoteHost]) -> None:
        by_alias: dict[str, RemoteHost] = {}
        for host in hosts:
            alias = validate_alias(host.alias)
            if alias in by_alias:
                raise ValidationError(
                    "remote_duplicate_alias",
                    i18n.t("remote.error.duplicate_alias", alias=alias),
                    {"alias": alias},
                )
            by_alias[alias] = host
        self._hosts: dict[str, RemoteHost] = by_alias

    @classmethod
    def from_config(cls, config: RemoteConfig) -> Inventory:
        return cls(config.hosts)

    def get(self, alias: str) -> RemoteHost:
        host = self._hosts.get(alias) if isinstance(alias, str) else None
        if host is None:
            raise PermissionDenied(
                "remote_host_not_listed",
                i18n.t("remote.error.host_not_listed"),
                {"alias": shown_alias(alias)},
            )
        return host

    def hosts(self) -> tuple[RemoteHost, ...]:
        return tuple(self._hosts.values())

    def aliases(self) -> tuple[str, ...]:
        return tuple(self._hosts)
