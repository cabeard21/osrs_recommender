"""The §8.3 three-layer cascade: live -> cached (within TTL) -> static hint -> unknown.

`PricesClient` is used directly with `httpx.MockTransport` rather than faked, so these
tests exercise the real request path too — the assertion that no HTTP call happens
when the cache is fresh is only meaningful if a real request would otherwise have gone
out.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tracker.config.settings import PricesSettings
from tracker.content.loader import Content
from tracker.content.schema import Item
from tracker.integrations.prices.cache import resolve_prices
from tracker.integrations.prices.client import PriceDTO, PricesClient, PriceSource

_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
_ITEM_ID = 27690


class _FakeCacheReader:
    def __init__(
        self, prices: dict[int, PriceDTO] | None = None, last_manual_refresh: datetime | None = None
    ) -> None:
        self._prices = prices or {}
        self._last_manual_refresh = last_manual_refresh

    def get(self, item_id: int) -> PriceDTO | None:
        return self._prices.get(item_id)

    def last_manual_refresh_at(self) -> datetime | None:
        return self._last_manual_refresh


def _content(fallback_price_gp: int | None = 85_000_000) -> Content:
    return Content(
        items={
            "voidwaker": Item(
                id="voidwaker",
                name="Voidwaker",
                item_id=_ITEM_ID,
                price_mode="live",
                fallback_price_gp=fallback_price_gp,
            )
        },
    )


def _price(source: PriceSource, fetched_at: datetime) -> PriceDTO:
    return PriceDTO(
        item_id=_ITEM_ID,
        high_price_gp=1,
        high_trade_at=fetched_at,
        low_price_gp=1,
        low_trade_at=fetched_at,
        provider="osrs_wiki",
        fetched_at=fetched_at,
        source=source,
    )


def _client_that_must_not_be_called() -> PricesClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be issued while cached data is within TTL")

    return PricesClient(
        PricesSettings(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        clock=lambda: _NOW,
    )


class TestNoRequestWhileCacheIsFresh:
    """§7.5: "No request at all while valid cached data exists.\""""

    def test_fresh_cache_serves_without_any_http_call(self) -> None:
        cache = _FakeCacheReader({_ITEM_ID: _price(PriceSource.LIVE, _NOW - timedelta(hours=1))})
        result = resolve_prices(
            [_ITEM_ID],
            client=_client_that_must_not_be_called(),
            cache=cache,
            content=_content(),
            settings=PricesSettings(),
            now=_NOW,
        )
        assert result[_ITEM_ID].source is PriceSource.CACHED

    def test_stale_cache_triggers_exactly_one_fetch_attempt(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                json={"data": {str(_ITEM_ID): {"high": 5, "highTime": 1, "low": 4, "lowTime": 1}}},
            )

        client = PricesClient(
            PricesSettings(),
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=lambda: _NOW,
        )
        cache = _FakeCacheReader({_ITEM_ID: _price(PriceSource.LIVE, _NOW - timedelta(hours=13))})

        result = resolve_prices(
            [_ITEM_ID],
            client=client,
            cache=cache,
            content=_content(),
            settings=PricesSettings(),
            now=_NOW,
        )

        assert calls == 1
        assert result[_ITEM_ID].source is PriceSource.LIVE
        assert result[_ITEM_ID].high_price_gp == 5

    def test_missing_cache_entry_also_triggers_a_fetch(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"data": {str(_ITEM_ID): {"high": 7, "highTime": 1, "low": 6, "lowTime": 1}}},
            )

        client = PricesClient(
            PricesSettings(),
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=lambda: _NOW,
        )
        result = resolve_prices(
            [_ITEM_ID],
            client=client,
            cache=_FakeCacheReader(),
            content=_content(),
            settings=PricesSettings(),
            now=_NOW,
        )
        assert result[_ITEM_ID].source is PriceSource.LIVE


@pytest.mark.parametrize(
    "source,high,low",
    [
        (PriceSource.UNKNOWN, None, None),
        (PriceSource.LIVE, None, None),
        (PriceSource.CACHED, None, None),
        (PriceSource.STATIC_HINT, 10, None),
    ],
)
def test_recent_missing_or_fallback_quote_retries_live(source, high, low):
    """Recording a failed lookup must not suppress the next scheduled lookup."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": {"892": {"high": 100, "highTime": 1}}})

    cached = replace(_price(source, _NOW), item_id=892, high_price_gp=high, low_price_gp=low)
    with PricesClient(
        PricesSettings(), transport=httpx.MockTransport(handler), clock=lambda: _NOW
    ) as client:
        result = resolve_prices(
            [892],
            client=client,
            cache=_FakeCacheReader({892: cached}),
            content=Content(items={}),
            settings=PricesSettings(),
            now=_NOW,
        )
    assert len(calls) == 1
    assert result[892].high_price_gp == 100
    assert result[892].source is PriceSource.LIVE


@pytest.mark.parametrize("high,low", [(None, 10), (0, None), (None, 0)])
def test_recent_market_quote_with_one_price_stays_cached(high, low):
    cached = replace(_price(PriceSource.LIVE, _NOW), high_price_gp=high, low_price_gp=low)
    with _client_that_must_not_be_called() as client:
        result = resolve_prices(
            [_ITEM_ID],
            client=client,
            cache=_FakeCacheReader({_ITEM_ID: cached}),
            content=_content(),
            settings=PricesSettings(),
            now=_NOW,
        )
    assert result[_ITEM_ID].source is PriceSource.CACHED
    assert result[_ITEM_ID].high_price_gp == high
    assert result[_ITEM_ID].low_price_gp == low


class TestFallbackCascade:
    def test_stale_cache_and_failed_live_fetch_falls_to_static_hint(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={})

        client = PricesClient(
            PricesSettings(),
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=lambda: _NOW,
        )
        cache = _FakeCacheReader({_ITEM_ID: _price(PriceSource.LIVE, _NOW - timedelta(hours=13))})

        result = resolve_prices(
            [_ITEM_ID],
            client=client,
            cache=cache,
            content=_content(fallback_price_gp=85_000_000),
            settings=PricesSettings(),
            now=_NOW,
        )
        assert result[_ITEM_ID].source is PriceSource.STATIC_HINT
        assert result[_ITEM_ID].high_price_gp == 85_000_000

    def test_no_cache_no_live_no_fallback_is_unknown(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={})

        client = PricesClient(
            PricesSettings(),
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=lambda: _NOW,
        )
        result = resolve_prices(
            [_ITEM_ID],
            client=client,
            cache=_FakeCacheReader(),
            content=_content(fallback_price_gp=None),
            settings=PricesSettings(),
            now=_NOW,
        )
        assert result[_ITEM_ID].source is PriceSource.UNKNOWN
        assert result[_ITEM_ID].high_price_gp is None

    def test_a_live_success_is_preferred_over_a_fresh_cache_entry(self) -> None:
        """When a fetch does happen (because some other id needed it), a live result
        for this id wins over its own still-fresh cache entry."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {str(_ITEM_ID): {"high": 99, "highTime": 1, "low": 98, "lowTime": 1}}
                },
            )

        client = PricesClient(
            PricesSettings(),
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=lambda: _NOW,
        )
        cache = _FakeCacheReader({_ITEM_ID: _price(PriceSource.LIVE, _NOW - timedelta(hours=13))})
        result = resolve_prices(
            [_ITEM_ID],
            client=client,
            cache=cache,
            content=_content(),
            settings=PricesSettings(),
            now=_NOW,
        )
        assert result[_ITEM_ID].high_price_gp == 99
        assert result[_ITEM_ID].source is PriceSource.LIVE


class TestManualRefreshThrottle:
    """§7.5: "Manual refresh rate-limited to once per 60 seconds.\""""

    def test_manual_refresh_forces_a_fetch_even_when_cache_is_fresh(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                json={
                    "data": {str(_ITEM_ID): {"high": 42, "highTime": 1, "low": 41, "lowTime": 1}}
                },
            )

        client = PricesClient(
            PricesSettings(),
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=lambda: _NOW,
        )
        cache = _FakeCacheReader(
            {_ITEM_ID: _price(PriceSource.LIVE, _NOW - timedelta(minutes=5))},
            last_manual_refresh=None,
        )

        result = resolve_prices(
            [_ITEM_ID],
            client=client,
            cache=cache,
            content=_content(),
            settings=PricesSettings(),
            now=_NOW,
            manual_refresh_requested=True,
        )

        assert calls == 1
        assert result[_ITEM_ID].high_price_gp == 42

    def test_manual_refresh_within_the_throttle_window_is_silently_ignored(self) -> None:
        """No user-visible failure (§7.5) — a throttled manual refresh just degrades to
        the normal TTL policy instead of erroring."""
        client = _client_that_must_not_be_called()
        cache = _FakeCacheReader(
            {_ITEM_ID: _price(PriceSource.LIVE, _NOW - timedelta(hours=1))},
            last_manual_refresh=_NOW - timedelta(seconds=10),
        )

        result = resolve_prices(
            [_ITEM_ID],
            client=client,
            cache=cache,
            content=_content(),
            settings=PricesSettings(manual_refresh_min_interval_seconds=60),
            now=_NOW,
            manual_refresh_requested=True,
        )
        assert result[_ITEM_ID].source is PriceSource.CACHED
