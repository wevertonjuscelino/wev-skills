"""Grants for commands with an external effect are tied to ``HEAD`` and the tree.

A push, a merge or a publish ships whatever the repository holds when it runs. A grant for
such a command (``CommandRisk.external_effect``) records the commit and the tree fingerprint
at grant time and counts only while both still match: after a new commit or an edit the
operator grants again. Other grants keep their binding (argv, directory, run, single use,
expiry); tying every grant to the tree would add prompts without stopping a regression.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypedDict

from wev_skills.core.errors import PermissionDenied
from wev_skills.security.commands import classify


@dataclass(frozen=True)
class Anchor:
    head: str
    tree: str


AnchorSource = Callable[[], Anchor]


class AnchorFields(TypedDict, total=False):
    """The ``ApprovalRequest`` fields an anchored grant sets."""

    head: str
    tree: str


def needs_anchor(argv: Sequence[str]) -> bool:
    """The command classifier says ``argv`` has an effect outside the machine."""
    try:
        return classify(argv).external_effect
    except PermissionDenied:
        return False  # not a command the executor would run at all


def anchor_fields(argv: Sequence[str], source: AnchorSource | None) -> AnchorFields:
    """``head`` and ``tree`` to record on a grant of ``argv``; empty when it is not anchored."""
    if source is None or not needs_anchor(argv):
        return {}
    now = source()
    return {"head": now.head, "tree": now.tree}


def moved(argv: Sequence[str], head: str, tree: str, source: AnchorSource | None) -> bool:
    """A grant of ``argv`` recorded at ``head`` and ``tree`` no longer matches the repository.

    Whether the grant is anchored follows from ``argv``, not from the stored fields, so a
    grant whose anchor was blanked, or that has no source to compare with, fails closed.
    """
    if not needs_anchor(argv):
        return False
    return source is None or source() != Anchor(head, tree)
