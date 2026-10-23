"""The ratchet rule: a lesson enters only when it helps and costs nothing."""

from __future__ import annotations

from collections.abc import Mapping


def not_lower(baseline: Mapping[str, int], other: Mapping[str, int]) -> bool:
    """True when ``other`` has the same cases and none passes less often (so the total does
    not drop either); equal counts qualify."""
    return baseline.keys() == other.keys() and all(
        other[case] >= passes for case, passes in baseline.items()
    )


def improves(baseline: Mapping[str, int], other: Mapping[str, int]) -> bool:
    """True when ``other`` has the same cases, none passes less often, and the total rises."""
    if baseline.keys() != other.keys():
        return False
    if any(other[case] < passes for case, passes in baseline.items()):
        return False
    return sum(other.values()) > sum(baseline.values())
