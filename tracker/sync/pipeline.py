"""§12's pipeline, stages 3–7 — the one place database reads meet engine calls.

::

    RuneLite POSTs the snapshot                                     [client]
    -> server validates against the JSON Schema; records SyncEvent  [8a]
 3  -> facts merged under §7.4's precedence rules                   [8b]
 4  -> freshness service maps PracticeEvents onto milestones        [8c]
 5  -> prices refreshed for referenced items, if TTL expired        [7 + here]
 6  -> progression engine recomputes CapabilityState                [4 + here]
 7  -> recommendation engine runs; snapshot persisted               [6 + here]
    -> dashboard refreshes over websocket                           [10]

Stage 2 is the endpoint's and stage 8 is the browser's — neither is a server-side function
call, which is why ``run_pipeline`` covers 3 through 7 and no more.

**This module is the caller side of §16.1's purity boundary.** Every engine it invokes is a
pure function over frozen inputs; every read and every write is here. That is not a
stylistic preference — it is what makes the engine chain testable without a database and
re-runnable against a stored ``PlayerState``, and Step 4's AST test fails the build if any
engine module reaches for a session.

**Ordering constraints that the diagram does not make obvious:**

* The **incumbent must be read before the new snapshot is written** (§9.9). Persist first
  and the run becomes its own incumbent, so hysteresis compares a candidate against itself
  and anti-thrash is silently disabled.
* **Freshness runs before the progression engine** (stage 4 before 6), because
  ``readiness_confidence`` reads ``last_practiced_at``. Reversed, every sync would compute
  readiness from the *previous* sync's practice.
* **Prices refresh before estimation** (stage 5 before 7), for the same reason: an estimate
  reads the price map it is handed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from tracker.config.settings import PricesSettings
from tracker.content.loader import Content
from tracker.db.persist_engine_output import (
    load_incumbent,
    persist_capability_states,
    persist_recommendation_run,
    prune_snapshots,
)
from tracker.db.persist_prices import DatabasePriceCache, persist_prices, stored_prices
from tracker.db.projection import build_player_state
from tracker.db.repository import get_player_by_username, roadmap_selection
from tracker.domain.types import Recommendation, RoadmapSelection, Source
from tracker.estimation.prices import resolve_price
from tracker.freshness.service import (
    FreshnessOutcome,
    apply_practice_events,
    materialize_freshness,
)
from tracker.integrations.prices.cache import resolve_prices
from tracker.integrations.prices.client import PricesClient
from tracker.integrations.prices.scope import scoped_item_ids
from tracker.progression.engine import compute_capability_states
from tracker.recommendations.engine import recommend_run
from tracker.sync.merge import MergeOutcome, merge_sync_payload

#: How many §6.10 snapshots to keep per player. The pipeline runs on every sync, and §15's
#: History view wants a trend rather than an archive; 200 is roughly a season of daily play
#: and still cheap to scan. Not content — a storage policy, not a game fact.
SNAPSHOT_RETENTION = 200


@dataclass(frozen=True)
class PipelineResult:
    """What one pipeline run did, stage by stage.

    Returned rather than logged because two callers need it for different reasons: the sync
    endpoint reports it back to the plugin, and the UI needs the fresh recommendations
    without re-querying what it just caused to be written.
    """

    player_id: int
    merge: MergeOutcome | None = None
    freshness: FreshnessOutcome = field(default_factory=FreshnessOutcome)
    prices_written: int = 0
    capability_states: int = 0
    snapshot_id: int | None = None
    recommendations: tuple[Recommendation, ...] = ()
    blocked: tuple[Recommendation, ...] = ()


def _price_scope(content: Content, selection: RoadmapSelection) -> frozenset[int]:
    """The active roadmap ids and primary ids of curated tradeable gear.

    The gear scope is limited to authored ladder members, not the entire item economy.
    Ownership variants are deliberately excluded: only an item's primary id is quoted.
    """
    gear_ids = frozenset(
        item.item_id
        for item in content.items.values()
        if item.item_id is not None
        and item.style is not None
        and item.slot is not None
        and item.tier is not None
        and item.acquisition == "tradeable"
    )
    return scoped_item_ids(content, selection.weights) | gear_ids


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
    """Stage 5. Returns the number of ``ItemPrice`` rows written.

    With no client configured this is a no-op rather than an error: §7.5 requires *"no
    user-visible failure when a cached or static fallback exists"*, and stage 7 reads
    whatever is stored regardless. An app started without network access still produces
    recommendations, with the estimates flagged low-confidence by §8.4's own rules.
    """
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
    )

    # A19: the three ``selected_*`` columns are the §8.3 policy's output, computed purely
    # by Step 5 and persisted here — the writer §6.8 defines but never names.
    items_by_numeric_id = {
        item.item_id: item for item in content.items.values() if item.item_id is not None
    }
    resolved = {
        item_id: resolve_price(items_by_numeric_id.get(item_id), dto, now=now)
        for item_id, dto in dtos.items()
    }

    if manual_refresh and cache is not None:
        cache.note_manual_refresh(now)

    return persist_prices(session, dtos, resolved=resolved)


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
    """Run stages 3–7 for one player. **The caller commits.**

    Two entry shapes, one pipeline:

    * with a ``payload``, this is a sync — stage 3 merges it, and the player is identified
      by the payload's username, the only identity the server trusts (§6.11);
    * with a ``player_id`` and no payload, this is a recompute — the background worker's
      price refresh and the UI's "recalculate" both want stages 4–7 with no new facts.

    The transaction boundary is the caller's for the reason 8b gives: one payload is one
    observation of one account at one instant, and a run that half-applied would leave the
    account describing a moment that never existed.
    """
    if payload is None and player_id is None:
        raise ValueError("run_pipeline needs either a payload to merge or a player_id to recompute")

    # ---- stage 3: merge ---------------------------------------------------
    merge: MergeOutcome | None = None
    if payload is not None:
        merge = merge_sync_payload(session, payload, source=source)
        player_id = merge.player_id
    if player_id is None:  # pragma: no cover — narrowed by the guard above, kept for mypy
        raise ValueError("no player_id after the merge stage")

    # ---- stage 4: freshness ----------------------------------------------
    freshness = apply_practice_events(session, player_id, content)

    # ---- stage 5: prices --------------------------------------------------
    selection = roadmap_selection(session, player_id)
    scope = _price_scope(content, selection)
    prices_written = _refresh_prices(
        session,
        content,
        scope,
        client=prices_client,
        settings=prices_settings,
        cache=price_cache,
        now=now,
        manual_refresh=manual_price_refresh,
    )

    # ---- stage 6: progression --------------------------------------------
    state = build_player_state(session, player_id)
    views = compute_capability_states(state, content, content.profile, now)
    capability_states = persist_capability_states(session, player_id, views, computed_at=now)
    # A18 — §6.6 calls ``Milestone.freshness`` materialized and nothing materialized it.
    # It runs here, after stage 4 wrote the ``last_practiced_at`` it derives from.
    materialize_freshness(session, player_id, now)

    # ---- stage 7: recommendations ----------------------------------------
    # Read the incumbent *before* writing this run's snapshot (§9.9) — see module docstring.
    incumbent = load_incumbent(session, player_id)
    run = recommend_run(
        state,
        selection,
        content,
        content.profile,
        incumbent,
        prices=stored_prices(session, scope),
        now=now,
    )
    snapshot = persist_recommendation_run(
        session,
        player_id,
        run.primary,
        selection=selection,
        scoring_profile_version=content.profile.version,
        run_at=now,
        blocked=run.blocked,
    )
    prune_snapshots(session, player_id, keep=SNAPSHOT_RETENTION)

    return PipelineResult(
        player_id=player_id,
        merge=merge,
        freshness=freshness,
        prices_written=prices_written,
        capability_states=capability_states,
        snapshot_id=snapshot.id,
        recommendations=run.primary,
        blocked=run.blocked,
    )


def player_id_for_username(session: Session, username: str) -> int | None:
    """Resolve a username to a row id, or ``None`` when the account is not yet known."""
    player = get_player_by_username(session, username)
    return player.id if player is not None else None
