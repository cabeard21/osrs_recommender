"""M2 gear price coverage and selected-leg provenance regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from tracker.content.loader import load_content
from tracker.db.models import Base, ItemPrice
from tracker.db.session import build_engine
from tracker.domain.types import PriceSourceLayer, RoadmapSelection
from tracker.estimation.prices import REASON_RECENT_LOW, REASON_STATIC_HINT
from tracker.integrations.prices.scope import scoped_item_ids
from tracker.sync.advisor import _price_facts
from tracker.sync.pipeline import _price_scope

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


def test_price_scope_adds_only_curated_tradeable_ladder_primary_ids() -> None:
    content = load_content()
    gear_ids = {
        item.item_id
        for item in content.items.values()
        if item.style is not None
        and item.slot is not None
        and item.tier is not None
        and item.acquisition == "tradeable"
        and item.item_id is not None
    }
    assert gear_ids
    assert _price_scope(content, RoadmapSelection()) == gear_ids

    selected = RoadmapSelection({"main_nh": 1.0})
    assert _price_scope(content, selected) == (
        scoped_item_ids(content, selected.weights) | gear_ids
    )


def test_advisor_selected_low_uses_low_trade_time() -> None:
    content = load_content()
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                ItemPrice(
                    item_id=4151,
                    high_price_gp=3_000_000,
                    high_trade_at=NOW - timedelta(days=20),
                    low_price_gp=2_000_000,
                    low_trade_at=NOW - timedelta(hours=3),
                    selected_price_gp=2_000_000,
                    selection_reason=REASON_RECENT_LOW,
                    provider="osrs_wiki",
                    fetched_at=NOW,
                    source=PriceSourceLayer.LIVE,
                )
            )
            session.flush()
            fact = _price_facts(session, content)[4151]
            assert fact.price_gp == 2_000_000
            assert fact.trade_at == NOW - timedelta(hours=3)
    finally:
        engine.dispose()


def test_advisor_static_hint_has_no_trade_time() -> None:
    content = load_content()
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                ItemPrice(
                    item_id=4151,
                    high_price_gp=3_000_000,
                    high_trade_at=NOW - timedelta(days=20),
                    selected_price_gp=1_000_000,
                    selection_reason=REASON_STATIC_HINT,
                    provider="osrs_wiki",
                    fetched_at=NOW,
                    source=PriceSourceLayer.LIVE,
                )
            )
            session.flush()
            fact = _price_facts(session, content)[4151]
            assert fact.price_gp == 1_000_000
            assert fact.trade_at is None
    finally:
        engine.dispose()
