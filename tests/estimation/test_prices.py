"""The §8.3 cascade and §8.4's confidence table (§16.4: *"each fallback layer; confidence
from trade age, not fetch age"*).

Two things are being pinned here, and they fail differently. The cascade tests pin *which
layer supplied the number* — the thing ``selection_reason`` exists to let the UI explain.
The confidence tests pin D10: a fresh retrieval of stale market data is stale.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest

from tracker.content.schema import Item
from tracker.domain.types import Confidence, PriceSelectionPolicy, PriceSourceLayer
from tracker.estimation.prices import (
    REASON_CACHED_HIGH,
    REASON_CACHED_LOW,
    REASON_RECENT_HIGH,
    REASON_RECENT_LOW,
    REASON_STATIC_HINT,
    REASON_UNKNOWN,
    PriceRecord,
    price_confidence,
    resolve_price,
)

VOIDWAKER = Item(
    id="voidwaker",
    name="Voidwaker",
    item_id=27690,
    price_mode="live",
    fallback_price_gp=85_000_000,
    price_staleness_days=7,
)

#: The same item with no hand-authored hint — the cascade's last layer removed, so the
#: `unknown` row of §8.3 becomes reachable.
NO_HINT = Item(id="obscure", name="Obscure thing", item_id=99, price_mode="live")


class TestTheCascadeLayers:
    """§8.3 top to bottom, one test per layer, each asserting the recorded reason."""

    def test_live_recent_high_price_wins(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """The first line of the acquisition order. High before low is the conservative
        choice: the instant-buy price is what actually leaves the player's bank."""
        record = price_record(
            item_id=27690,
            high_price_gp=39_000_000,
            high_trade_at=ago(hours=2),
            low_price_gp=38_000_000,
            low_trade_at=ago(hours=1),
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.gp == 39_000_000
        assert resolved.layer is PriceSourceLayer.LIVE
        assert resolved.selection_reason == REASON_RECENT_HIGH
        assert resolved.confidence is Confidence.HIGH
        assert resolved.policy is PriceSelectionPolicy.ACQUISITION_COST

    def test_live_recent_low_price_is_the_second_choice(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """No recent high — the item has sellers and no buyers this week."""
        record = price_record(item_id=27690, low_price_gp=38_000_000, low_trade_at=ago(hours=3))

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.gp == 38_000_000
        assert resolved.layer is PriceSourceLayer.LIVE
        assert resolved.selection_reason == REASON_RECENT_LOW

    def test_a_stale_high_does_not_pre_empt_a_recent_low(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """*Recent* high, then *recent* low. The feed returns the latest trade whenever it
        happened, so an unconditional preference for the high would report a live layer
        that no live trade supports."""
        record = price_record(
            item_id=27690,
            high_price_gp=50_000_000,
            high_trade_at=ago(days=40),
            low_price_gp=38_000_000,
            low_trade_at=ago(hours=6),
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.gp == 38_000_000
        assert resolved.selection_reason == REASON_RECENT_LOW

    def test_the_cached_layer_supplies_a_last_known_price(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        record = price_record(
            item_id=27690,
            high_price_gp=41_000_000,
            high_trade_at=ago(hours=30),
            fetched_at=ago(hours=30),
            source=PriceSourceLayer.CACHED.value,
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.gp == 41_000_000
        assert resolved.layer is PriceSourceLayer.CACHED
        assert resolved.selection_reason == REASON_CACHED_HIGH
        assert resolved.confidence is Confidence.MEDIUM

    def test_a_cached_row_with_only_a_low_price_still_resolves(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        record = price_record(
            item_id=27690,
            low_price_gp=37_500_000,
            low_trade_at=ago(days=2),
            fetched_at=ago(days=2),
            source=PriceSourceLayer.CACHED.value,
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.selection_reason == REASON_CACHED_LOW
        assert resolved.layer is PriceSourceLayer.CACHED

    def test_a_live_row_whose_every_trade_is_stale_falls_to_the_cached_layer(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """§8.3's acquisition order is *recent high → recent low → **cached***. A fetch
        that succeeded but returned a month-old trade has produced a last-known price, and
        saying so is what stops the UI presenting it as today's market."""
        record = price_record(
            item_id=27690,
            high_price_gp=50_000_000,
            high_trade_at=ago(days=40),
            fetched_at=now,
            source=PriceSourceLayer.LIVE.value,
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.gp == 50_000_000
        assert resolved.layer is PriceSourceLayer.CACHED
        assert resolved.selection_reason == REASON_CACHED_HIGH
        assert resolved.confidence is Confidence.LOW

    def test_the_static_hint_is_reached_when_there_is_no_record_at_all(self, now: datetime) -> None:
        resolved = resolve_price(VOIDWAKER, None, now=now)

        assert resolved.gp == 85_000_000
        assert resolved.layer is PriceSourceLayer.STATIC_HINT
        assert resolved.selection_reason == REASON_STATIC_HINT
        assert resolved.confidence is Confidence.LOW
        assert resolved.trade_at is None

    def test_a_row_tagged_static_hint_is_not_mistaken_for_market_data(
        self, price_record: Callable[..., PriceRecord], now: datetime
    ) -> None:
        """``resolve_prices`` fills the static layer with a synthetic row carrying the
        fallback in ``high_price_gp``. Reading it as a live high price would report a
        hand-authored number as a trade — which is why the row's own ``source`` tag, and
        not the presence of a number, decides which layers it may satisfy."""
        record = price_record(
            item_id=27690,
            high_price_gp=85_000_000,
            fetched_at=now,
            source=PriceSourceLayer.STATIC_HINT.value,
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.layer is PriceSourceLayer.STATIC_HINT
        assert resolved.selection_reason == REASON_STATIC_HINT

    def test_a_cached_row_older_than_the_window_falls_through_to_the_hint(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """§8.3: *"unavailable **or too old**"*."""
        record = price_record(
            item_id=27690,
            high_price_gp=41_000_000,
            high_trade_at=ago(days=90),
            fetched_at=ago(days=90),
            source=PriceSourceLayer.CACHED.value,
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.gp == 85_000_000
        assert resolved.layer is PriceSourceLayer.STATIC_HINT

    def test_unknown_is_the_last_layer_and_reports_no_number(self, now: datetime) -> None:
        """``gp is None``, never ``0``: a zero would reach §9.4's ``cost_decay`` as *free*
        and flatter the candidate whose cost the app failed to learn (G5)."""
        resolved = resolve_price(NO_HINT, None, now=now)

        assert resolved.gp is None
        assert resolved.layer is PriceSourceLayer.UNKNOWN
        assert resolved.selection_reason == REASON_UNKNOWN
        assert resolved.confidence is Confidence.LOW

    def test_an_item_the_corpus_does_not_declare_still_resolves(self, now: datetime) -> None:
        resolved = resolve_price(None, None, now=now)
        assert resolved.layer is PriceSourceLayer.UNKNOWN

    def test_an_unrecognised_source_tag_degrades_rather_than_raising(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """The tag crosses a process boundary — an older schema, another client. A
        recommendation run must not die over a word it does not know."""
        record = price_record(
            item_id=27690,
            high_price_gp=39_000_000,
            high_trade_at=ago(hours=1),
            source="something_new",
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.layer is PriceSourceLayer.STATIC_HINT


class TestConfidenceComesFromTheTradeTimestampNotTheFetchTimestamp:
    """D10, §8.4 — the single rule this module exists to get right.

    *"Fetching today does not make a three-day-old trade fresh — this is the same defect
    as ``ContainerScan`` (§6.5) one layer out."*
    """

    def test_a_record_fetched_one_minute_ago_whose_trade_is_five_days_old_is_medium(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """The exit criterion, stated as a test name. The plausible wrong implementation
        is ``now - record.fetched_at``, which reports ``high`` here."""
        record = price_record(
            item_id=27690,
            high_price_gp=39_000_000,
            high_trade_at=ago(days=5),
            fetched_at=ago(minutes=1),
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.layer is PriceSourceLayer.LIVE
        assert resolved.selection_reason == REASON_RECENT_HIGH
        assert resolved.confidence is Confidence.MEDIUM
        assert resolved.trade_at == ago(days=5)

    def test_the_same_record_fetched_a_week_ago_with_a_one_hour_old_trade_is_high(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """The converse, which a fetch-age implementation also gets wrong — and in the
        direction that hides a good number rather than inventing one."""
        record = price_record(
            item_id=27690,
            high_price_gp=39_000_000,
            high_trade_at=ago(hours=1),
            fetched_at=ago(days=6),
            source=PriceSourceLayer.CACHED.value,
        )

        resolved = resolve_price(VOIDWAKER, record, now=now)

        assert resolved.layer is PriceSourceLayer.CACHED
        assert resolved.confidence is Confidence.HIGH

    @pytest.mark.parametrize(
        ("age", "expected"),
        [
            ({"hours": 1}, Confidence.HIGH),
            ({"hours": 23, "minutes": 59}, Confidence.HIGH),
            ({"hours": 24}, Confidence.MEDIUM),
            ({"days": 5}, Confidence.MEDIUM),
            ({"days": 7}, Confidence.MEDIUM),
            ({"days": 7, "seconds": 1}, Confidence.LOW),
            ({"days": 30}, Confidence.LOW),
        ],
    )
    def test_the_section_8_4_table_row_by_row(
        self,
        age: dict[str, float],
        expected: Confidence,
        now: datetime,
        ago: Callable[..., datetime],
    ) -> None:
        assert price_confidence(ago(**age), now=now) is expected

    def test_no_trade_data_at_all_is_low(self, now: datetime) -> None:
        """§8.4's last row. There is no fourth confidence value for *no evidence*; the
        absence is carried by the layer instead."""
        assert price_confidence(None, now=now) is Confidence.LOW


class TestThePerItemStalenessOverride:
    """§10.5's ``price_staleness_days``, which §8.3 treats as the item's own TTL."""

    def test_a_slow_moving_item_still_counts_a_ten_day_old_trade_as_live(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """Ahrim's robetop declares 30 days: it barely trades, and demoting every figure
        to the static hint would replace a real price with a hand-authored one."""
        slow = Item(
            id="ahrims_robetop",
            name="Ahrim's robetop",
            item_id=4712,
            price_mode="live",
            fallback_price_gp=1_500_000,
            price_staleness_days=30,
        )
        record = price_record(item_id=4712, high_price_gp=1_400_000, high_trade_at=ago(days=10))

        resolved = resolve_price(slow, record, now=now)

        assert resolved.layer is PriceSourceLayer.LIVE
        assert resolved.selection_reason == REASON_RECENT_HIGH

    def test_the_window_does_not_soften_the_confidence_table(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """A wider staleness window says *keep using this number*; it does not say *trust
        it more*. §8.4's thresholds are fixed at 24 hours and 7 days for every item."""
        slow = Item(
            id="ahrims_robetop", name="Ahrim's robetop", item_id=4712, price_staleness_days=30
        )
        record = price_record(item_id=4712, high_price_gp=1_400_000, high_trade_at=ago(days=10))

        assert resolve_price(slow, record, now=now).confidence is Confidence.LOW

    def test_an_item_declaring_nothing_gets_the_seven_day_default(
        self, price_record: Callable[..., PriceRecord], now: datetime, ago: Callable[..., datetime]
    ) -> None:
        """Seven days matches §8.3's worked example and §8.4's medium/low boundary, so an
        item that says nothing is treated exactly like one that says seven."""
        plain = Item(id="plain", name="Plain", item_id=1, price_mode="live")
        recent = price_record(item_id=1, high_price_gp=100, high_trade_at=ago(days=6))
        stale = price_record(item_id=1, high_price_gp=100, high_trade_at=ago(days=8))

        assert resolve_price(plain, recent, now=now).layer is PriceSourceLayer.LIVE
        assert resolve_price(plain, stale, now=now).layer is PriceSourceLayer.CACHED
