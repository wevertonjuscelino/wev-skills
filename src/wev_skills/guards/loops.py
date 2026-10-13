"""Loop shapes the identical-command rule alone would miss: short repeating cycles."""

from __future__ import annotations

from collections.abc import Sequence

CYCLE_LENGTHS = (2, 3)
"""Periods looked for. Period one is the identical-command rule itself."""


def find_cycle(signatures: Sequence[str], repeats: int) -> tuple[str, ...]:
    """The cycle of 2 or 3 distinct signatures the sequence ends with, repeated more than
    ``repeats`` times in a row; empty when there is none."""
    for period in CYCLE_LENGTHS:
        needed = period * (repeats + 1)
        if repeats < 1 or len(signatures) < needed:
            continue
        tail = list(signatures[-needed:])
        cycle = tail[:period]
        periodic = all(tail[index] == tail[index - period] for index in range(period, needed))
        if periodic and len(set(cycle)) == period:
            return tuple(cycle)
    return ()
