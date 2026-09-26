"""Cache raw market observations with their source and capture times."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy.orm import Session

from tracker.db.models import ItemPrice
from tracker.domain.types import PriceSourceLayer
from tracker.integrations.prices.client import PriceDTO, PriceSource


class DatabasePriceCache:
    """``PriceCacheReader`` over the ``item_price`` table (§6.8, §8.3).

    ``last_manual_refresh_at`` is held in memory rather than in a column. §7.5's 60-second
    manual-refresh throttle exists to stop a user hammering a refresh button inside one
    session, and §5 makes the app a single long-lived uvicorn process, so process memory is
    the same lifetime as the thing being throttled. A restart forgets it and permits one
    extra fetch — well inside the "no fixed numeric rate limit" the provider publishes.
    Giving it a column would mean a schema migration to record a UI debounce.
    """

    def __init__(self, session: Session, *, last_manual_refresh_at: datetime | None = None) -> None:
        self._session = session
        self._last_manual_refresh_at = last_manual_refresh_at

    def get(self, item_id: int) -> PriceDTO | None:
        """The stored row for one item, whatever its age, as the DTO Step 7 expects.

        Returned as a ``PriceDTO`` rather than as the ORM row so the caller — pure cascade
        logic in :mod:`tracker.integrations.prices.cache` — never holds a live SQLAlchemy
        object whose attribute access could emit a query mid-decision.
        """
        row = self._session.get(ItemPrice, item_id)
        return _to_dto(row) if row is not None else None

    def last_manual_refresh_at(self) -> datetime | None:
        return self._last_manual_refresh_at

    def note_manual_refresh(self, at: datetime) -> None:
        """Record that a manual refresh was honoured, starting the §7.5 throttle window."""
        self._last_manual_refresh_at = at


def persist_prices(session: Session, prices: Mapping[int, PriceDTO]) -> int:
    """Upsert raw ``ItemPrice`` observations without storing a chosen price.

    Rows whose ``source`` is ``unknown`` are skipped. §8.3's cascade always returns an
    entry for every requested id — a candidate with no price is better flagged
    low-confidence than dropped — but "we could not price this" is not a market fact, and
    storing it would give the item a ``fetched_at`` implying we had looked something up.

    Gear resolves a price from these observations on demand, retaining the source and
    freshness of whichever observation it used.
    """
    written = 0
    for item_id, dto in prices.items():
        if dto.source == PriceSource.UNKNOWN:
            continue

        row = session.get(ItemPrice, item_id)
        if row is None:
            row = ItemPrice(item_id=item_id, provider=dto.provider, fetched_at=dto.fetched_at)
            session.add(row)

        row.high_price_gp = dto.high_price_gp
        row.high_trade_at = dto.high_trade_at
        row.low_price_gp = dto.low_price_gp
        row.low_trade_at = dto.low_trade_at
        row.provider = dto.provider
        row.fetched_at = dto.fetched_at
        row.source = PriceSourceLayer(dto.source.value)

        written += 1

    session.flush()
    return written


def _to_dto(row: ItemPrice) -> PriceDTO:
    """One ``ItemPrice`` row as the DTO shape both the cascade and the engine consume."""
    return PriceDTO(
        item_id=row.item_id,
        high_price_gp=row.high_price_gp,
        high_trade_at=row.high_trade_at,
        low_price_gp=row.low_price_gp,
        low_trade_at=row.low_trade_at,
        provider=row.provider,
        fetched_at=row.fetched_at,
        source=PriceSource(row.source.value),
    )
