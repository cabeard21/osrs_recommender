"""§22.2's snapshot: ordering, and the observation-age bucket."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.advisor.conftest import NOW, make_content, make_price, make_state, make_task
from tracker.advisor.snapshot import (
    AdvisorSnapshot,
    ObservationAge,
    build_advisor_snapshot,
    confidence_word,
    observation_age,
)
from tracker.domain.types import CapabilityView, Confidence, Status


def _snapshot(**overrides: object) -> AdvisorSnapshot:
    defaults: dict[str, object] = {
        "state": make_state(),
        "content": make_content(),
        "now": NOW,
    }
    defaults.update(overrides)
    return build_advisor_snapshot(**defaults)  # type: ignore[arg-type]


class TestOrdering:
    def test_ranked_entries_are_ordered_by_rank(self) -> None:
        built = _snapshot(
            ranked=[
                make_task(candidate_id="c", rank=3),
                make_task(candidate_id="a", rank=1),
                make_task(candidate_id="b", rank=2),
            ]
        )
        assert [task.rank for task in built.ranked] == [1, 2, 3]

    def test_equal_ranks_break_on_candidate_id_rather_than_input_order(self) -> None:
        """Otherwise the hash in §22.3 moves on a difference the account never made."""
        forwards = _snapshot(
            ranked=[make_task(candidate_id="b", rank=1), make_task(candidate_id="a", rank=1)]
        )
        backwards = _snapshot(
            ranked=[make_task(candidate_id="a", rank=1), make_task(candidate_id="b", rank=1)]
        )
        assert [task.candidate_id for task in forwards.ranked] == ["a", "b"]
        assert forwards.ranked == backwards.ranked

    def test_blocked_entries_are_ordered_by_descending_score(self) -> None:
        built = _snapshot(
            blocked=[
                make_task(candidate_id="low", score=0.1, blocked=True),
                make_task(candidate_id="high", score=0.9, blocked=True),
            ]
        )
        assert [task.candidate_id for task in built.blocked] == ["high", "low"]

    def test_capabilities_are_ordered_by_id(self) -> None:
        views = [
            CapabilityView(capability_id="z", status=Status.LOCKED, unlock_fraction=0.0),
            CapabilityView(capability_id="a", status=Status.LOCKED, unlock_fraction=0.0),
        ]
        assert [view.capability_id for view in _snapshot(capabilities=views).capabilities] == [
            "a",
            "z",
        ]

    def test_prices_are_ordered_by_item_id(self) -> None:
        built = _snapshot(
            prices={
                4151: make_price(item_id=4151, name="Abyssal whip"),
                995: make_price(item_id=995, name="Coins"),
            }
        )
        assert list(built.prices) == [995, 4151]


class TestObservationAge:
    @pytest.mark.parametrize(
        ("elapsed", "expected"),
        [
            (timedelta(0), ObservationAge.TODAY),
            (timedelta(hours=23, minutes=59), ObservationAge.TODAY),
            (timedelta(days=1), ObservationAge.THIS_WEEK),
            (timedelta(days=6, hours=23), ObservationAge.THIS_WEEK),
            (timedelta(days=7), ObservationAge.THIS_MONTH),
            (timedelta(days=29, hours=23), ObservationAge.THIS_MONTH),
            (timedelta(days=30), ObservationAge.OLDER),
            (timedelta(days=400), ObservationAge.OLDER),
        ],
    )
    def test_buckets_at_their_boundaries(
        self, elapsed: timedelta, expected: ObservationAge
    ) -> None:
        assert observation_age(NOW - elapsed, now=NOW) is expected

    def test_never_synced_is_never_rather_than_old(self) -> None:
        """An account nobody has synced is a different fact from a stale one."""
        assert observation_age(None, now=NOW) is ObservationAge.NEVER

    def test_a_future_timestamp_does_not_raise(self) -> None:
        """Plugin/host clock skew is real and outside this application's control."""
        assert observation_age(NOW + timedelta(hours=2), now=NOW) is ObservationAge.TODAY

    def test_the_snapshot_derives_its_bucket_from_the_state(self) -> None:
        built = _snapshot(state=make_state(last_sync_at=NOW - timedelta(days=10)))
        assert built.observed_age is ObservationAge.THIS_MONTH


class TestConfidenceWord:
    def test_absent_confidence_is_unknown_not_low(self) -> None:
        """Nobody assessed it; calling that *low* would assert an assessment nobody made."""
        assert confidence_word(None) == "unknown"

    def test_a_confidence_renders_as_its_lowercase_name(self) -> None:
        assert confidence_word(Confidence.MEDIUM) == "medium"
