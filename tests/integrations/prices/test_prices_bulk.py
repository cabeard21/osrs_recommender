"""Catalog refreshes use one bulk request without retaining the whole economy."""

from datetime import UTC, datetime

import httpx
import pytest

from tracker.config.settings import PricesSettings
from tracker.integrations.prices.client import PricesClient


def test_catalog_sized_scope_uses_one_bulk_request_and_filters_response():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "1": {"high": 4_000_000_000, "highTime": 1},
                    "99999": {"high": 123, "highTime": 1},
                    "2": {"high": True, "highTime": "bad"},
                }
            },
        )

    with PricesClient(PricesSettings(), transport=httpx.MockTransport(respond)) as client:
        result = client.latest(range(1, 100))
    assert len(calls) == 1
    assert not calls[0].url.params
    assert set(result) == {1, 2}
    assert result[1].high_price_gp == 4_000_000_000
    assert result[1].high_trade_at == datetime.fromtimestamp(1, tz=UTC)
    assert result[2].high_price_gp is None
    assert result[2].high_trade_at is None


@pytest.mark.parametrize("payload", [[], None, {"data": []}, {"data": None}])
def test_malformed_bulk_payload_is_best_effort(payload):
    with PricesClient(
        PricesSettings(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    ) as client:
        assert client.latest(range(1, 100)) == {}


def test_bad_bulk_json_preserves_cache_fallback_path():
    with PricesClient(
        PricesSettings(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not json")),
    ) as client:
        assert client.latest(range(1, 100)) == {}


def test_prices_default_to_current_v2_latest_endpoint():
    assert PricesSettings().base_url == "https://prices.runescape.wiki/api/v2/osrs"


def test_known_equipment_price_scope_does_not_require_ladder_membership():
    from tracker.content.loader import Content
    from tracker.content.schema import Item
    from tracker.integrations.prices.scope import scoped_item_ids

    content = Content(
        items={
            "new_bow": Item(
                id="new_bow", name="New bow", item_id=123, slot="weapon", acquisition="tradeable"
            )
        }
    )
    assert scoped_item_ids(content) == frozenset({123})


@pytest.mark.parametrize("timestamp", [1e99, float("inf"), -1e99])
def test_out_of_range_trade_time_is_unknown(timestamp):
    # Exercise parser directly; JSON cannot represent all nonfinite values safely.
    from tracker.integrations.prices.client import _epoch_to_datetime

    assert _epoch_to_datetime(timestamp) is None
