"""The database side of §8.3's price cascade — the reader Step 7 injects, and A19's writer.

Two halves of one seam:

* :class:`DatabasePriceCache` implements Step 7's ``PriceCacheReader`` protocol. Step 7's
  client decides *whether to fetch* by asking this reader what is already stored; keeping
  the query here is what let Step 7 ship without depending on Step 3 at all.
* :func:`persist_prices` writes the fetched rows **and** the three ``selected_*`` columns
  §6.8 defines but assigns to no writer — the gap A19 records. Step 5 computes them purely
  (:func:`tracker.estimation.prices.resolve_price`); this is where they land.

The split matters: ``selected_price_gp`` is the *output of a policy*, not data the feed
supplied, so it is written from a ``ResolvedPrice`` rather than copied off a DTO.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.db.models import ItemPrice
from tracker.domain.types import PriceSourceLayer
from tracker.estimation.prices import ResolvedPrice
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


def persist_prices(
    session: Session,
    prices: Mapping[int, PriceDTO],
    *,
    resolved: Mapping[int, ResolvedPrice] | None = None,
) -> int:
    """Upsert one ``ItemPrice`` row per item, including A19's ``selected_*`` columns.

    Rows whose ``source`` is ``unknown`` are skipped. §8.3's cascade always returns an
    entry for every requested id — a candidate with no price is better flagged
    low-confidence than dropped — but "we could not price this" is not a market fact, and
    storing it would give the item a ``fetched_at`` implying we had looked something up.

    ``resolved`` is optional because the two writes have different natural moments: a fetch
    happens once per run, while a selection can be recomputed from stored rows at any time.
    When absent the ``selected_*`` columns are left as they were rather than cleared — a
    stale selection is more useful than none, and the next run overwrites it.
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

        selection = (resolved or {}).get(item_id)
        if selection is not None:
            row.selected_price_gp = selection.gp
            row.selection_policy = selection.policy
            row.selection_reason = selection.selection_reason

        written += 1

    session.flush()
    return written


def stored_prices(session: Session, item_ids: frozenset[int]) -> dict[int, PriceDTO]:
    """Every stored row among ``item_ids``, as the DTOs the engine reads.

    Converted rather than handed over as ORM rows, for a reason worth recording because it
    looks like pointless copying: the engine reads prices through
    :class:`~tracker.estimation.prices.PriceRecord`, whose ``source`` member is typed
    ``str`` so that a ``StrEnum``-tagged DTO satisfies it. ``ItemPrice.source`` is a plain
    ``Enum`` — the column's own type — and a plain ``Enum`` is not a ``str``. Passing rows
    through would type-check only by widening the protocol, which is exactly the loosening
    that would later let something non-price-shaped past it.

    The second reason is the one from :meth:`DatabasePriceCache.get`: a detached ORM row
    handed to pure code can emit a query on attribute access.
    """
    if not item_ids:
        return {}
    rows = session.scalars(select(ItemPrice).where(ItemPrice.item_id.in_(item_ids))).all()
    return {row.item_id: _to_dto(row) for row in rows}


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
