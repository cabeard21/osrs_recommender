"""The §8.3 three-layer price resolution cascade.

.. code-block::

    Live market price
        |  unavailable
    Cached last-known price (within TTL)
        |  unavailable or too old
    Static content hint
        |  absent
    unknown

``resolve_prices`` is the one place that decision runs. It reads existing price state
through an **injected** :class:`PriceCacheReader` rather than a database query — Step 9
owns the database; this package must not import :mod:`tracker.db` (module docstring of
:mod:`tracker.integrations`) — and it reads the static fallback from the already-loaded
:class:`~tracker.content.loader.Content`, never from the network.

**TTL governs whether we re-fetch, not how much we trust what we fetched.** The TTL
check compares ``now`` against ``PriceDTO.fetched_at`` — *our* clock — deciding only
"is it worth asking the provider again." Confidence in the number itself is a
downstream concern (§8.4) derived from ``high_trade_at``/``low_trade_at``, which this
module passes through unmodified. Conflating the two is exactly the defect D10 calls
out for ``ContainerScan``, one layer further out.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol

from tracker.config.settings import PricesSettings
from tracker.content.loader import Content
from tracker.integrations.prices.client import PriceDTO, PricesClient, PriceSource


class PriceCacheReader(Protocol):
    """Read-only view over persisted price state (§8.3).

    Implemented by Step 9's database-backed reader. This module never queries a
    database directly — it only ever calls methods on whatever is injected here, which
    is what keeps Step 7 decoupled from Step 3's schema.
    """

    def get(self, item_id: int) -> PriceDTO | None:
        """The last-known price row for this item, whatever its age, or ``None`` if
        this item has never been fetched."""
        ...

    def last_manual_refresh_at(self) -> datetime | None:
        """When a manual refresh last actually ran, for the §7.5 60s throttle."""
        ...


def resolve_prices(
    item_ids: Iterable[int],
    *,
    client: PricesClient,
    cache: PriceCacheReader,
    content: Content,
    settings: PricesSettings,
    now: datetime,
    manual_refresh_requested: bool = False,
    bulk_refresh: bool = False,
) -> dict[int, PriceDTO]:
    """Resolve a price for every requested id, one cascade pass, one fetch attempt.

    * No request at all while every requested id already has cached data within
      ``settings.ttl_hours`` — the "no request while valid cached data exists" rule.
    * At most one call to ``client.latest`` per invocation — "at most one refresh
      attempt per recommendation run" — even when several ids need refreshing.
    * A manual refresh forces that one call even if the cache is fresh, but only if
      the last manual refresh honoured was at least
      ``settings.manual_refresh_min_interval_seconds`` ago; otherwise it silently
      degrades to the normal TTL policy rather than surfacing a failure.
    * Every requested id gets an entry — falling through to a static hint or
      ``unknown`` rather than being dropped — because a candidate missing a price
      entirely is a worse UI experience than one flagged low-confidence.
    * ``bulk_refresh`` keeps scheduled/manual equipment refreshes on one bulk
      endpoint request even when only one newly discovered ID needs a quote.
    """
    ids = frozenset(item_ids)
    ttl = timedelta(hours=settings.ttl_hours)

    stale_or_missing = {
        item_id for item_id in ids if not _cache_is_fresh(cache.get(item_id), now=now, ttl=ttl)
    }

    manual_refresh_allowed = manual_refresh_requested and _manual_refresh_allowed(
        cache.last_manual_refresh_at(),
        now=now,
        min_interval=timedelta(seconds=settings.manual_refresh_min_interval_seconds),
    )

    live: dict[int, PriceDTO] = {}
    if stale_or_missing or manual_refresh_allowed:
        fetch_ids = ids if manual_refresh_allowed else stale_or_missing
        live = client.latest(fetch_ids, bulk=True) if bulk_refresh else client.latest(fetch_ids)

    resolved: dict[int, PriceDTO] = {}
    for item_id in ids:
        resolved[item_id] = _resolve_one(
            item_id, live=live, cache=cache, content=content, now=now, ttl=ttl
        )
    return resolved


def _resolve_one(
    item_id: int,
    *,
    live: dict[int, PriceDTO],
    cache: PriceCacheReader,
    content: Content,
    now: datetime,
    ttl: timedelta,
) -> PriceDTO:
    fetched = live.get(item_id)
    if fetched is not None:
        return fetched

    cached = cache.get(item_id)
    if cached is not None and _cache_is_fresh(cached, now=now, ttl=ttl):
        return replace(cached, source=PriceSource.CACHED)

    item = content.item_by_numeric_id(item_id)
    if item is not None and item.fallback_price_gp is not None:
        return PriceDTO(
            item_id=item_id,
            high_price_gp=item.fallback_price_gp,
            high_trade_at=None,
            low_price_gp=None,
            low_trade_at=None,
            provider="static_hint",
            fetched_at=now,
            source=PriceSource.STATIC_HINT,
        )

    return PriceDTO(
        item_id=item_id,
        high_price_gp=None,
        high_trade_at=None,
        low_price_gp=None,
        low_trade_at=None,
        provider="unknown",
        fetched_at=now,
        source=PriceSource.UNKNOWN,
    )


def _cache_is_fresh(cached: PriceDTO | None, *, now: datetime, ttl: timedelta) -> bool:
    # A recent failed lookup or static fallback is not a cached market quote.
    # Only successful market observations may suppress the next provider attempt.
    if cached is None or cached.source not in {PriceSource.LIVE, PriceSource.CACHED}:
        return False
    if cached.high_price_gp is None and cached.low_price_gp is None:
        return False
    return now - cached.fetched_at <= ttl


def _manual_refresh_allowed(
    last_refresh: datetime | None, *, now: datetime, min_interval: timedelta
) -> bool:
    if last_refresh is None:
        return True
    return now - last_refresh >= min_interval
