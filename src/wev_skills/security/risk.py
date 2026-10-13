"""The risk record of a command and the small helpers every classification rule shares."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from wev_skills import i18n
from wev_skills.core._codec import Serializable

Argv = tuple[str, ...]

FLAG_FIELDS = {
    "d": "destructive",
    "x": "external_effect",
    "p": "privileged",
    "n": "network",
    "u": "unanalyzable",
}
MIN_ABBREVIATION = 3
"""``--x``: the shortest spelling taken as an abbreviation of a long option."""


@dataclass(frozen=True)
class CommandRisk(Serializable):
    destructive: bool = False
    external_effect: bool = False
    privileged: bool = False
    network: bool = False
    unanalyzable: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def needs_approval(self) -> bool:
        return self.destructive or self.external_effect or self.privileged or self.unanalyzable

    @property
    def is_risky(self) -> bool:
        return self.needs_approval or self.network

    def merge(self, other: CommandRisk) -> CommandRisk:
        names = FLAG_FIELDS.values()
        flags = {name: getattr(self, name) or getattr(other, name) for name in names}
        return CommandRisk(reasons=tuple(dict.fromkeys(self.reasons + other.reasons)), **flags)


SAFE = CommandRisk()


def risk(flags: str, code: str) -> CommandRisk:
    fields = {FLAG_FIELDS[flag]: True for flag in flags}
    return CommandRisk(reasons=(i18n.t(f"security.risk.{code}"),), **fields)


def has_flag(args: Sequence[str], short: str = "", long: Sequence[str] = ()) -> bool:
    for arg in args:
        if arg.startswith("--"):
            if arg.split("=", 1)[0] in long:
                return True
        elif arg.startswith("-") and any(char in short for char in arg[1:]):
            return True
    return False


def abbreviates(arg: str, option: str) -> bool:
    """``arg`` is ``option`` or a prefix of it that a parser of long options would accept.

    Ambiguous prefixes count too: a tool would reject them, and asking costs less than
    letting ``--forc`` through.
    """
    head = arg.split("=", 1)[0]
    return head.startswith("--") and len(head) >= MIN_ABBREVIATION and option.startswith(head)


def has_long(args: Sequence[str], options: Sequence[str]) -> bool:
    """Any of ``args`` spells, or abbreviates, one of the long ``options``."""
    return any(abbreviates(arg, option) for arg in args for option in options)
