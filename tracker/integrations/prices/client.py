"""OSRS Wiki real-time prices client — the live layer of the §8.3 cascade.

Provider: ``https://prices.runescape.wiki/api/v2/osrs`` (§7.5, D10). Response shape
verified against the live ``/latest`` endpoint at implementation time (2026-08-04),
via ``id=<item_id>``::

    {
        "data": {
            "27690": {
                "high": 39153913,
                "highTime": 1785876233,
                "low": 38288000,
                "lowTime": 1785875920,
            }
        }
    }

``high``/``low`` are instant buy/sell prices in gp; ``highTime``/``lowTime`` are Unix
seconds for *when that trade happened* — a different fact from when we called the API
(D10, §6.8). Either pair may be absent (no recent trade) rather than present-but-null.

Small lookups remain scoped by numeric ID. Catalog-sized refreshes (32 or more
IDs) fetch one bulk snapshot and retain only the requested equipment IDs. This
follows the provider's bulk-use guidance without persisting the whole economy.

A per-item failure (after the §7.5 retry schedule, or while the breaker is open) is
swallowed and that id is simply absent from the returned mapping — never raised past
this method. §8.3's cascade needs a partial result, not an all-or-nothing one: one
item lacking recent trade data must not take working data for the rest of the scoped
set down with it. This is also how "at most one refresh *attempt*" is honoured when
several ids need a fetch in the same run: each id is asked for once, not retried
across repeat calls within the run — the bounded 0s/2s/8s schedule inside
:func:`~tracker.integrations.http.get_with_retry` is that one attempt's execution, not
several.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

from tracker.config.settings import PricesSettings
from tracker.integrations.http import (
    CircuitBreaker,
    CircuitBreakerOpen,
    RequestFailed,
    build_client,
    get_with_retry,
)

logger = logging.getLogger(__name__)


class PriceSource(StrEnum):
    """§6.8's ``ItemPrice.source`` — which layer of the §8.3 cascade supplied a value.

    Distinct from :class:`tracker.domain.types.Source`, which is observation
    *provenance* (``runelite`` / ``wise_old_man`` / ``hiscores``, ...). This is
    resolution *layer*. §6.8 stores both a ``provider`` name and this ``source`` tag
    on the same row, so the UI can explain any figure it shows.
    """

    LIVE = "live"
    CACHED = "cached"
    STATIC_HINT = "static_hint"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PriceDTO:
    """§6.8's ``ItemPrice`` columns the provider client is responsible for.

    Everything here except the three ``selected_*`` columns, which §6.8 assigns to
    the §8.3 resolution policy (:mod:`tracker.integrations.prices.cache`) instead —
    they are *output of a policy*, not data the feed supplies.

    ``high_trade_at``/``low_trade_at`` are kept separate from ``fetched_at`` on
    purpose (D10): fetching today does not make a three-day-old trade fresh, and
    Step 8.4's ``estimate_confidence`` is derived from the trade timestamp, never
    from fetch time.
    """

    item_id: int
    high_price_gp: int | None
    high_trade_at: datetime | None
    low_price_gp: int | None
    low_trade_at: datetime | None
    provider: str
    fetched_at: datetime
    source: PriceSource


class PricesClient:
    """Live fetch for a caller-scoped set of numeric item ids (§7.5, §8.3).

    Returns a :class:`PriceDTO` mapping and persists nothing — Step 9's pipeline owns
    all writes (module docstring of :mod:`tracker.integrations`).
    """

    def __init__(
        self,
        settings: PricesSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        breaker: CircuitBreaker | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._client = build_client(
            base_url=settings.base_url, user_agent=settings.user_agent, transport=transport
        )
        self._breaker = breaker if breaker is not None else CircuitBreaker()
        self._clock = clock
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PricesClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def latest(self, item_ids: Iterable[int]) -> dict[int, PriceDTO]:
        """Live prices for exactly the given ids — never more (§8.3, §11.6).

        Best-effort: an id whose fetch fails is simply absent from the result, so one
        provider hiccup does not erase prices this run successfully fetched for other
        scoped items. Callers needing "did the request happen at all" should inspect
        the breaker they injected rather than this return value.
        """
        scoped = sorted(frozenset(item_ids))
        # Keep tiny lookups scoped; a catalog refresh must not make hundreds of requests.
        if len(scoped) >= 32:
            data = self._fetch_data()
            fetched_at = self._clock()
            return {
                item_id: self._record(item_id, data[str(item_id)], fetched_at)
                for item_id in scoped
                if isinstance(data.get(str(item_id)), dict)
            }
        result: dict[int, PriceDTO] = {}
        for item_id in scoped:
            entry = self._fetch_one(item_id)
            if entry is not None:
                result[item_id] = entry
        return result

    def _fetch_one(self, item_id: int) -> PriceDTO | None:
        data = self._fetch_data(item_id)
        entry = data.get(str(item_id))
        if not isinstance(entry, dict):
            return None
        return self._record(item_id, entry, self._clock())

    def _fetch_data(self, item_id: int | None = None) -> dict[str, Any]:
        try:
            response = get_with_retry(
                self._client,
                "/latest",
                params={"id": item_id} if item_id is not None else {},
                breaker=self._breaker,
                sleep=self._sleep,
            )
            payload = response.json()
        except (RequestFailed, CircuitBreakerOpen, ValueError) as exc:
            logger.warning("price fetch failed (%s): %s", item_id or "catalog", exc)
            return {}
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else {}

    def _record(self, item_id: int, entry: dict[str, Any], fetched_at: datetime) -> PriceDTO:
        return PriceDTO(
            item_id=item_id,
            high_price_gp=_as_int(entry.get("high")),
            high_trade_at=_epoch_to_datetime(entry.get("highTime")),
            low_price_gp=_as_int(entry.get("low")),
            low_trade_at=_epoch_to_datetime(entry.get("lowTime")),
            provider=self._settings.provider,
            fetched_at=fetched_at,
            source=PriceSource.LIVE,
        )


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _epoch_to_datetime(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None
