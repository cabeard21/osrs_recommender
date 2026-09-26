"""Factual price records and fixed timestamps for resolver tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from tracker.domain.types import PriceSourceLayer
from tracker.estimation.prices import PriceRecord

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FakePriceRecord:
    item_id: int
    high_price_gp: int | None = None
    high_trade_at: datetime | None = None
    low_price_gp: int | None = None
    low_trade_at: datetime | None = None
    fetched_at: datetime = NOW
    source: str = PriceSourceLayer.LIVE.value


@pytest.fixture
def price_record() -> Callable[..., PriceRecord]:
    return FakePriceRecord


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def ago() -> Callable[..., datetime]:
    def subtract(**kwargs: float) -> datetime:
        return NOW - timedelta(**kwargs)

    return subtract
