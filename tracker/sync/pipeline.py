"""Account sync and supported Gear price refresh.

The caller owns the transaction. A RuneLite payload is merged as one observation;
periodic and manual runs refresh cached market facts without changing account state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from tracker.config.settings import PricesSettings
from tracker.content.loader import Content
from tracker.db.persist_prices import DatabasePriceCache, persist_prices
from tracker.db.repository import get_player_by_username
from tracker.domain.types import Source
from tracker.gear.catalog import load_catalog
from tracker.gear.support import project_catalog
from tracker.integrations.prices.cache import resolve_prices
from tracker.integrations.prices.client import PricesClient
from tracker.integrations.prices.scope import scoped_item_ids
from tracker.sync.merge import MergeOutcome, merge_sync_payload


@dataclass(frozen=True)
class PipelineResult:
    player_id: int
    merge: MergeOutcome | None = None
    prices_written: int = 0


def _price_scope(content: Content) -> frozenset[int]:
    """Retain authored prices and discover supported exact physical tradeable IDs.

    Reload on each refresh so updated catalog/classification bytes are discovered;
    the catalog loader rejects stale classification evidence before projection.
    Price discovery does not assert account eligibility or alter support policy.
    """
    catalog = project_catalog(load_catalog(content), "community_best_effort")
    supported = frozenset(
        item.id
        for item in catalog.items.values()
        if item.tradeable is True
        and not item.unsupported_effects
        and (item.requirements_complete or item.id in catalog.community_assumptions)
    )
    return scoped_item_ids(content) | supported


def _refresh_prices(
    session: Session,
    content: Content,
    scope: frozenset[int],
    *,
    client: PricesClient | None,
    settings: PricesSettings | None,
    cache: DatabasePriceCache | None,
    now: datetime,
    manual_refresh: bool,
) -> int:
    if client is None or settings is None or not scope:
        return 0
    reader = cache if cache is not None else DatabasePriceCache(session)
    dtos = resolve_prices(
        scope,
        client=client,
        cache=reader,
        content=content,
        settings=settings,
        now=now,
        manual_refresh_requested=manual_refresh,
        bulk_refresh=True,
    )
    if manual_refresh and cache is not None:
        cache.note_manual_refresh(now)
    return persist_prices(session, dtos)


def run_pipeline(
    session: Session,
    *,
    content: Content,
    now: datetime,
    player_id: int | None = None,
    payload: Mapping[str, Any] | None = None,
    source: Source = Source.RUNELITE,
    prices_client: PricesClient | None = None,
    prices_settings: PricesSettings | None = None,
    price_cache: DatabasePriceCache | None = None,
    manual_price_refresh: bool = False,
) -> PipelineResult:
    """Merge a payload or refresh facts for an existing player; caller commits."""
    if payload is None and player_id is None:
        raise ValueError("run_pipeline needs either a payload to merge or a player_id to refresh")
    merge: MergeOutcome | None = None
    if payload is not None:
        merge = merge_sync_payload(session, payload, source=source)
        player_id = merge.player_id
    if player_id is None:  # pragma: no cover
        raise ValueError("no player_id after the merge stage")
    prices_written = _refresh_prices(
        session,
        content,
        _price_scope(content)
        if prices_client is not None and prices_settings is not None
        else frozenset(),
        client=prices_client,
        settings=prices_settings,
        cache=price_cache,
        now=now,
        manual_refresh=manual_price_refresh,
    )
    return PipelineResult(player_id=player_id, merge=merge, prices_written=prices_written)


def player_id_for_username(session: Session, username: str) -> int | None:
    player = get_player_by_username(session, username)
    return player.id if player is not None else None
