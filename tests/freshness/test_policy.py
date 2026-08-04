"""The §6.6 freshness policy.

Two things are asserted here that the band table does not say out loud: which side of
each boundary belongs to which band, and that the two ``None`` cases mean *"do not
downgrade anything"* rather than *"assume the worst"*.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tracker.domain.types import Freshness, MilestoneClass
from tracker.freshness.policy import STALE_AFTER, VERY_STALE_AFTER, classify_age, freshness

NOW = datetime(2026, 8, 4, tzinfo=UTC)

EXECUTION = MilestoneClass.EXECUTION


def practiced(days_ago: float) -> datetime:
    return NOW - timedelta(days=days_ago)


class TestBands:
    """§6.6: ``< 30d`` current · ``30–90d`` stale · ``> 90d`` very_stale."""

    @pytest.mark.parametrize(
        ("days_ago", "expected"),
        [
            (0, Freshness.CURRENT),
            (1, Freshness.CURRENT),
            (29.9, Freshness.CURRENT),
            (30, Freshness.STALE),
            (60, Freshness.STALE),
            (89.9, Freshness.STALE),
            (90, Freshness.STALE),
            (90.1, Freshness.VERY_STALE),
            (365, Freshness.VERY_STALE),
        ],
    )
    def test_the_table(self, days_ago: float, expected: Freshness) -> None:
        assert freshness(practiced(days_ago), NOW, EXECUTION) is expected

    def test_both_boundaries_belong_to_the_middle_band(self) -> None:
        """§6.6 writes the middle band as the inclusive range *"30–90 days"* and
        ``very_stale`` as strictly *"> 90 days"*, so 30 and 90 are both ``stale``."""
        assert classify_age(STALE_AFTER) is Freshness.STALE
        assert classify_age(STALE_AFTER - timedelta(seconds=1)) is Freshness.CURRENT
        assert classify_age(VERY_STALE_AFTER) is Freshness.STALE
        assert classify_age(VERY_STALE_AFTER + timedelta(seconds=1)) is Freshness.VERY_STALE

    def test_a_future_timestamp_is_current_not_a_negative_band(self) -> None:
        """Clock skew between the plugin and the server is not evidence of decay."""
        assert freshness(NOW + timedelta(days=5), NOW, EXECUTION) is Freshness.CURRENT


class TestOnlyExecutionMilestonesAge:
    """§6.6: ``knowledge`` and ``threshold`` do not age, so they have no freshness."""

    @pytest.mark.parametrize(
        "milestone_class", [MilestoneClass.KNOWLEDGE, MilestoneClass.THRESHOLD]
    )
    def test_non_execution_classes_have_no_freshness(self, milestone_class: MilestoneClass) -> None:
        assert freshness(practiced(3650), NOW, milestone_class) is None

    def test_execution_is_the_only_class_that_returns_a_band(self) -> None:
        banded = [
            milestone_class
            for milestone_class in MilestoneClass
            if freshness(practiced(1), NOW, milestone_class) is not None
        ]
        assert banded == [MilestoneClass.EXECUTION]


class TestAbsentEvidence:
    """G6 — *"absent evidence never accelerates staleness"* (§7.6)."""

    def test_no_practice_record_is_none_not_very_stale(self) -> None:
        """A milestone attested before any practice tracking existed is not decayed; we
        simply have not observed practice. §4.5 forbids reading the second from the first.
        """
        assert freshness(None, NOW, EXECUTION) is None

    def test_none_is_returned_for_every_class_when_there_is_no_record(self) -> None:
        for milestone_class in MilestoneClass:
            assert freshness(None, NOW, milestone_class) is None


class TestPurity:
    """§16.1 — ``now`` is an argument, so the answer never depends on the wall clock."""

    def test_the_same_inputs_give_the_same_answer(self) -> None:
        last = practiced(45)
        assert freshness(last, NOW, EXECUTION) is freshness(last, NOW, EXECUTION)

    def test_advancing_the_clock_is_what_moves_the_band(self) -> None:
        last = practiced(20)
        assert freshness(last, NOW, EXECUTION) is Freshness.CURRENT
        assert freshness(last, NOW + timedelta(days=20), EXECUTION) is Freshness.STALE
        assert freshness(last, NOW + timedelta(days=200), EXECUTION) is Freshness.VERY_STALE


class TestClassifyAge:
    """The band table without the class gate — §6.9's knowledge-milestone note only."""

    @pytest.mark.parametrize(
        ("age", "expected"),
        [
            (timedelta(0), Freshness.CURRENT),
            (timedelta(days=45), Freshness.STALE),
            (timedelta(days=400), Freshness.VERY_STALE),
            (timedelta(days=-5), Freshness.CURRENT),
        ],
    )
    def test_it_bands_any_age(self, age: timedelta, expected: Freshness) -> None:
        assert classify_age(age) is expected

    def test_it_agrees_with_freshness_for_execution_milestones(self) -> None:
        for days_ago in (0, 15, 30, 75, 90, 120, 900):
            assert classify_age(timedelta(days=days_ago)) is freshness(
                practiced(days_ago), NOW, EXECUTION
            )
