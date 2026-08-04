"""The XP curve, checked against its own definition and against the anchors (§8.2).

A shipped constant that nothing re-derives is a constant nobody can tell has drifted. The
first test below recomputes all 99 entries from the generating formula; the rest pin the
two figures a player would notice immediately if they were wrong.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from tracker.estimation.xp_table import MAX_LEVEL, XP_FOR_LEVEL, level_for_xp, xp_for_level


def formula(level: int) -> int:
    """``xp(L) = floor( 1/4 · Σ_{l=1}^{L-1} floor( l + 300 · 2^(l/7) ) )`` — the OSRS curve."""
    points = 0
    for lower in range(1, level):
        points += math.floor(lower + 300 * 2 ** (lower / 7))
    return points // 4


class TestTheTableIsTheCurve:
    def test_every_entry_matches_the_generating_formula(self) -> None:
        """The literal table is the formula evaluated once. This is what stops the two
        diverging: an edited constant fails here rather than in a recommendation."""
        assert list(XP_FOR_LEVEL) == [formula(level) for level in range(1, MAX_LEVEL + 1)]

    @pytest.mark.parametrize(
        ("level", "xp"),
        [
            (1, 0),
            (2, 83),
            (92, 6_517_253),  # the halfway point of the 1–99 grind
            (99, 13_034_431),
        ],
    )
    def test_the_anchors_every_player_knows(self, level: int, xp: int) -> None:
        assert xp_for_level(level) == xp

    def test_the_curve_is_strictly_increasing(self) -> None:
        assert all(lower < higher for lower, higher in pairwise(XP_FOR_LEVEL))


class TestTheInverse:
    @pytest.mark.parametrize("level", range(1, MAX_LEVEL + 1))
    def test_level_for_xp_inverts_xp_for_level(self, level: int) -> None:
        assert level_for_xp(xp_for_level(level)) == level

    def test_one_xp_short_of_a_threshold_is_still_the_lower_level(self) -> None:
        assert level_for_xp(xp_for_level(92) - 1) == 91

    def test_xp_beyond_the_curve_is_still_99(self) -> None:
        """The cap is 200M XP and the curve ends at 99; *"level 108"* is not a fact."""
        assert level_for_xp(200_000_000) == MAX_LEVEL

    def test_a_level_outside_the_curve_raises_rather_than_clamping(self) -> None:
        """A band boundary computed wrongly should name its caller, not quietly return
        the level-99 figure and turn a bug into a merely implausible estimate."""
        with pytest.raises(ValueError, match="outside 1–99"):
            xp_for_level(100)
        with pytest.raises(ValueError, match="outside 1–99"):
            xp_for_level(0)

    def test_negative_xp_raises(self) -> None:
        """§6.2 / G5: an unranked skill is ``None``, never a negative total."""
        with pytest.raises(ValueError, match="negative"):
            level_for_xp(-1)
