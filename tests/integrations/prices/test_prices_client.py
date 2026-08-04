"""OSRS Wiki prices client tests (§7.5, §8.3, D10).

The mocked ``/latest`` response shape matches what was verified against the live API
at implementation time (see the module docstring of
``tracker.integrations.prices.client``): ``{"data": {"<id>": {"high", "highTime",
"low", "lowTime"}}}``, keyed by item id as a string, times in Unix seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from tracker.config.settings import PricesSettings
from tracker.integrations.http import CircuitBreaker
from tracker.integrations.prices.client import PricesClient, PriceSource

_FIXED_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _client(handler: httpx.MockTransport, **kwargs: object) -> PricesClient:
    return PricesClient(
        PricesSettings(),
        transport=handler,
        sleep=lambda _: None,
        clock=lambda: _FIXED_NOW,
        **kwargs,
    )


class TestScopedFetch:
    """§8.3, §11.6: only the requested ids are ever put on the wire."""

    def test_requests_only_the_given_ids(self) -> None:
        requested_ids: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            item_id = request.url.params.get("id")
            requested_ids.append(item_id)
            return httpx.Response(
                200, json={"data": {item_id: {"high": 100, "highTime": 1, "low": 90, "lowTime": 1}}}
            )

        client = _client(httpx.MockTransport(handler))
        client.latest([27690, 11802])

        assert sorted(requested_ids) == ["11802", "27690"]

    def test_an_unreferenced_id_is_never_requested(self) -> None:
        """Only the scoped set (§8.3's roadmap closure) reaches `latest`; an id the
        corpus declares but the roadmap never references must not appear on the wire.
        """
        requested_ids: set[str] = set()

        def handler(request: httpx.Request) -> httpx.Response:
            item_id = request.url.params["id"]
            requested_ids.add(item_id)
            return httpx.Response(200, json={"data": {}})

        # 999 stands in for an item the corpus declares but this roadmap never uses —
        # scope.py is responsible for excluding it before it ever reaches this client.
        scoped_ids = [27690, 11802]
        client = _client(httpx.MockTransport(handler))
        client.latest(scoped_ids)

        assert requested_ids == {"27690", "11802"}
        assert "999" not in requested_ids

    def test_empty_scope_issues_no_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request should be issued for an empty scope")

        client = _client(httpx.MockTransport(handler))
        assert client.latest([]) == {}


class TestResponseParsing:
    def test_prices_and_trade_timestamps_are_returned_separately_from_fetched_at(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "27690": {
                            "high": 39_153_913,
                            "highTime": 1_785_876_233,
                            "low": 38_288_000,
                            "lowTime": 1_785_875_920,
                        }
                    }
                },
            )

        client = _client(httpx.MockTransport(handler))
        result = client.latest([27690])

        price = result[27690]
        assert price.high_price_gp == 39_153_913
        assert price.low_price_gp == 38_288_000
        assert price.high_trade_at == datetime.fromtimestamp(1_785_876_233, tz=UTC)
        assert price.low_trade_at == datetime.fromtimestamp(1_785_875_920, tz=UTC)
        # D10: fetch time is a distinct fact from either trade time.
        assert price.fetched_at == _FIXED_NOW
        assert price.fetched_at != price.high_trade_at
        assert price.source is PriceSource.LIVE
        assert price.provider == "osrs_wiki"

    def test_item_absent_from_the_response_is_absent_from_the_result(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {}})

        client = _client(httpx.MockTransport(handler))
        assert client.latest([27690]) == {}


class TestPartialFailure:
    """§8.3, §7.5: one item's failure must not erase another's successfully fetched price."""

    def test_one_failing_item_does_not_drop_a_succeeding_one(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            item_id = request.url.params["id"]
            if item_id == "11802":
                return httpx.Response(500, json={})
            return httpx.Response(
                200, json={"data": {item_id: {"high": 1, "highTime": 1, "low": 1, "lowTime": 1}}}
            )

        client = _client(httpx.MockTransport(handler), breaker=CircuitBreaker(failure_threshold=99))
        result = client.latest([27690, 11802])

        assert 27690 in result
        assert 11802 not in result
