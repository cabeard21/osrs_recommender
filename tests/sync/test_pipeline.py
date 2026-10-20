"""Sync merges account facts and refreshes only authored Gear price facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

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

    def latest(self, item_ids: frozenset[int]) -> dict[int, PriceDTO]:
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
    assert _price_scope(content) == expected


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
