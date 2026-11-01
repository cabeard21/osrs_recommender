"""Read cached market observations for account-aware gear tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tracker.db.models import ItemPrice


@dataclass(frozen=True, slots=True)
class CachedPriceRecord:
    item_id: int
    high_price_gp: int | None
    high_trade_at: datetime | None
    low_price_gp: int | None
    low_trade_at: datetime | None
    fetched_at: datetime
    source: str
    provider: str


@dataclass(frozen=True, slots=True)
class DatabaseGearPrices:
    sessions: sessionmaker[Session]

    def get_prices(self) -> dict[int, CachedPriceRecord]:
        """Copy stored rows once; gear evaluation performs no network request or write."""
        with self.sessions(autoflush=False) as session:
            return self.read_prices(session)

    @staticmethod
    def read_prices(session: Session) -> dict[int, CachedPriceRecord]:
        rows = session.scalars(select(ItemPrice)).all()
        return {
            row.item_id: CachedPriceRecord(
                item_id=row.item_id,
                high_price_gp=row.high_price_gp,
                high_trade_at=row.high_trade_at,
                low_price_gp=row.low_price_gp,
                low_trade_at=row.low_trade_at,
                fetched_at=row.fetched_at,
                source=row.source.value,
                provider=row.provider,
            )
            for row in rows
        }
