"""Sync merges account facts and refreshes supported exact-ID Gear prices."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.orm import Session

from tracker.config.settings import PricesSettings
from tracker.content.loader import load_content
from tracker.db.models import ItemPrice, Player, QuestState
from tracker.domain.types import Source
from tracker.integrations.prices.client import PriceDTO, PricesClient, PriceSource
from tracker.sync.pipeline import _price_scope, run_pipeline

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


class RecordingPricesClient:
    def __init__(self) -> None:
        self.calls: list[frozenset[int]] = []

    def latest(self, item_ids: frozenset[int], *, bulk: bool = False) -> dict[int, PriceDTO]:
        assert bulk
        self.calls.append(item_ids)
        return {
            item_id: PriceDTO(
                item_id=item_id,
                high_price_gp=1_000_000,
                high_trade_at=NOW - timedelta(hours=1),
                low_price_gp=900_000,
                low_trade_at=NOW - timedelta(hours=2),
                provider="osrs_wiki",
                fetched_at=NOW,
                source=PriceSource.LIVE,
            )
            for item_id in item_ids
        }


def test_price_scope_contains_reviewed_tradeable_equipment() -> None:
    content = load_content()
    expected = frozenset(
        item.item_id
        for item in content.items.values()
        if item.item_id is not None and item.slot is not None and item.acquisition == "tradeable"
    )
    assert expected
    from tracker.gear.catalog import load_catalog
    from tracker.gear.support import project_catalog

    catalog = project_catalog(load_catalog(content), "community_best_effort")
    supported = frozenset(
        item.id
        for item in catalog.items.values()
        if item.tradeable is True
        and not item.unsupported_effects
        and (item.requirements_complete or item.id in catalog.community_assumptions)
    )
    assert _price_scope(content) == expected | supported
    assert 1207 in _price_scope(content)  # Community Steel dagger, absent from authored scope.


def test_sync_merges_facts_without_recommendation_writes(
    session: Session, build_payload: Callable[..., Any]
) -> None:
    content = load_content()
    payload = build_payload(
        NOW,
        quests=[{"quest_id": "desert_treasure_i", "status": "complete"}],
    )

    result = run_pipeline(
        session, content=content, now=NOW, payload=payload, source=Source.RUNELITE
    )

    assert result.merge is not None
    assert result.merge.player_id == result.player_id
    assert session.get(Player, result.player_id) is not None
    assert session.query(QuestState).filter_by(player_id=result.player_id).count() == 1


def test_refresh_caches_raw_prices_without_selecting_a_recommendation_price(
    session: Session, build_payload: Callable[..., Any]
) -> None:
    content = load_content()
    first = run_pipeline(session, content=content, now=NOW, payload=build_payload(NOW))
    client = RecordingPricesClient()

    result = run_pipeline(
        session,
        content=content,
        now=NOW,
        player_id=first.player_id,
        prices_client=cast(PricesClient, client),
        prices_settings=PricesSettings(),
    )

    assert result.merge is None
    assert result.prices_written > 0
    assert client.calls == [_price_scope(content)]
    row = session.get(ItemPrice, next(iter(client.calls[0])))
    assert row is not None
    assert row.high_price_gp == 1_000_000
    assert row.low_price_gp == 900_000
    assert row.provider == "osrs_wiki"


def test_scope_rediscovers_classification_without_reloading_content(monkeypatch) -> None:
    from dataclasses import replace

    from tracker.gear.catalog import load_catalog

    content = load_content()
    catalog = load_catalog(content)
    without = replace(catalog, community_items={})
    loaded = iter((without, catalog, without))
    monkeypatch.setattr("tracker.sync.pipeline.load_catalog", lambda content: next(loaded))
    assert 1207 not in _price_scope(content)
    assert 1207 in _price_scope(content)
    assert 1207 not in _price_scope(content)


def test_account_only_sync_does_not_require_equipment_catalog(session, monkeypatch) -> None:
    def unexpected_load(content):
        raise AssertionError("Account-only sync must not load the equipment catalog")

    monkeypatch.setattr("tracker.sync.pipeline.load_catalog", unexpected_load)
    assert run_pipeline(session, content=load_content(), now=NOW, player_id=1).prices_written == 0


def test_scope_preserves_explicit_tradeability_and_effect_blockers(monkeypatch) -> None:
    from dataclasses import replace

    from tracker.gear.catalog import load_catalog

    content = load_content()
    catalog = load_catalog(content)
    for updates in ({"tradeable": False}, {"unsupported_effects": ("Known special",)}):
        changed = catalog.items[1207].model_copy(update=updates)
        selected = replace(catalog, items={**catalog.items, 1207: changed})
        monkeypatch.setattr("tracker.sync.pipeline.load_catalog", lambda content, c=selected: c)
        assert 1207 not in _price_scope(content)


@pytest.mark.parametrize("quote_present", [True, False])
def test_new_single_id_uses_bulk_and_preserves_cached_facts(
    session: Session,
    monkeypatch,
    quote_present: bool,
) -> None:
    from tracker.db.persist_prices import persist_prices

    cached = PriceDTO(841, 50, NOW, 40, NOW, "osrs_wiki", NOW, PriceSource.LIVE)
    persist_prices(session, {841: cached})
    monkeypatch.setattr(
        "tracker.sync.pipeline._price_scope", lambda content: frozenset({841, 1207})
    )
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    **(
                        {"1207": {"high": 99, "highTime": int(NOW.timestamp())}}
                        if quote_present
                        else {}
                    ),
                    "999999": {"high": 1, "highTime": int(NOW.timestamp())},
                }
            },
        )

    with PricesClient(
        PricesSettings(), transport=httpx.MockTransport(respond), clock=lambda: NOW
    ) as client:
        run_pipeline(
            session,
            content=load_content(),
            now=NOW,
            player_id=1,
            prices_client=client,
            prices_settings=PricesSettings(),
        )
    assert len(calls) == 1
    assert calls[0].url.path.endswith("/latest")
    assert not calls[0].url.params
    assert session.get(ItemPrice, 999999) is None
    existing = session.get(ItemPrice, 841)
    assert existing.high_price_gp == 50
    assert existing.fetched_at == NOW
    assert existing.high_trade_at == NOW
    assert existing.provider == "osrs_wiki"
    added = session.get(ItemPrice, 1207)
    assert (added.high_price_gp if added else None) == (99 if quote_present else None)
