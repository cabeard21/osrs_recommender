"""§12's pipeline end to end, over the real seed corpus (Step 9)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import PricesSettings, Settings
from tracker.content.loader import Content, load_content
from tracker.db.models import (
    Base,
    CapabilityState,
    ItemPrice,
    Milestone,
    RecommendationEntry,
    RecommendationSnapshot,
)
from tracker.db.persist_engine_output import load_incumbent
from tracker.db.repository import set_active_roadmap
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Freshness, MilestoneClass, PriceSourceLayer
from tracker.integrations.prices.client import PriceDTO, PricesClient, PriceSource
from tracker.sync.pipeline import PipelineResult, run_pipeline
from tracker.sync.worker import SingleFlightRefresher

NOW = datetime(2026, 8, 4, 15, 18, 41, tzinfo=UTC)


class RecordingPricesClient:
    """A ``PricesClient`` stand-in that records every fetch.

    Deliberately not a mock framework: the assertion these tests make is *"how many times
    was the provider called"*, which is §7.5's own rule ("at most one refresh attempt per
    recommendation run", "no request at all while valid cached data exists"), and a
    recording double states that directly.
    """

    def __init__(self) -> None:
        self.calls: list[frozenset[int]] = []

    def latest(self, item_ids: frozenset[int]) -> dict[int, PriceDTO]:
        self.calls.append(frozenset(item_ids))
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


@pytest.fixture(scope="session")
def content() -> Content:
    return load_content()


@pytest.fixture
def pipeline_sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'pipeline.db'}")
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


@pytest.fixture
def db(pipeline_sessions: sessionmaker[Session]) -> Iterator[Session]:
    with pipeline_sessions() as db_session:
        yield db_session


@pytest.fixture
def payload(build_payload: Callable[..., Any], to_iso: Callable[..., str]) -> dict[str, Any]:
    """A sync carrying enough of everything for the engines to have something to say."""
    return build_payload(
        NOW,
        skills=[
            {"skill": "magic", "level": 87, "xp": 4_000_000},
            {"skill": "strength", "level": 90, "xp": 5_400_000},
        ],
        unlocks=[{"key": "ancient_magicks", "state": "unlocked"}],
        quests=[{"quest_id": "desert_treasure_i", "status": "complete"}],
        observed_items=[],
        container_scans=[
            {"container": "bank", "scanned_at": to_iso(NOW)},
            {"container": "equipment", "scanned_at": to_iso(NOW)},
        ],
        practice_events=[
            {
                "domain": "lms",
                "started_at": to_iso(NOW - timedelta(minutes=7)),
                "ended_at": to_iso(NOW),
                "evidence_type": "lms_match_completed",
            }
        ],
    )


def _run(
    db: Session,
    content: Content,
    payload: dict[str, Any] | None = None,
    *,
    player_id: int | None = None,
    now: datetime = NOW,
    client: RecordingPricesClient | None = None,
) -> PipelineResult:
    return run_pipeline(
        db,
        content=content,
        now=now,
        player_id=player_id,
        payload=payload,
        prices_client=cast(PricesClient, client) if client is not None else None,
        prices_settings=PricesSettings() if client is not None else None,
    )


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def test_a_sync_produces_a_snapshot_with_entries(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """The §12 pipeline, whole: a payload in, a ranked snapshot out.

    This is the test that catches any two of Steps 2–8 disagreeing — a contract field with
    no merge, a merge with no projection, a projection the engine cannot read.
    """
    result = _run(db, content, payload)

    snapshots = db.scalars(select(RecommendationSnapshot)).all()
    entries = db.scalars(select(RecommendationEntry).order_by(RecommendationEntry.rank)).all()

    assert len(snapshots) == 1
    assert result.snapshot_id == snapshots[0].id
    assert entries, "the run ranked nothing at all"
    assert [entry.rank for entry in entries] == list(range(1, len(entries) + 1))


def test_capability_states_are_materialized(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    result = _run(db, content, payload)

    rows = db.scalars(select(CapabilityState)).all()
    assert {row.capability_id for row in rows} == set(content.capabilities)
    assert result.capability_states == len(content.capabilities)


def test_milestone_freshness_is_materialized(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """A18 — §6.6 calls the column materialized, and until Step 9 nothing materialized it.

    The payload carries an LMS practice event, so stage 4 gives every execution milestone
    declaring ``lms`` a ``last_practiced_at``, and stage 6 turns it into a band.
    """
    _run(db, content, payload)

    rows = db.scalars(select(Milestone).where(Milestone.class_ == MilestoneClass.EXECUTION)).all()
    practiced = [row for row in rows if row.last_practiced_at is not None]

    assert practiced, "no execution milestone was attributed the LMS event"
    assert all(row.freshness is Freshness.CURRENT for row in practiced)


def test_the_snapshot_records_the_profile_version_and_the_live_selection(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """A13 — ``roadmap_selection`` is read from ``ActiveRoadmap``, never hardcoded, and the
    weights are stored **as this run used them** (§6.12): a History view re-reading the live
    setting would relabel every past run whenever the user reweighted their roadmaps.
    """
    first = _run(db, content, payload)
    set_active_roadmap(db, first.player_id, "main_nh", selection_weight=0.75)
    set_active_roadmap(db, first.player_id, "anti_pk", selection_weight=0.25)
    db.flush()

    _run(db, content, player_id=first.player_id, now=NOW + timedelta(minutes=1))

    snapshots = db.scalars(select(RecommendationSnapshot).order_by(RecommendationSnapshot.id)).all()
    assert snapshots[0].roadmap_selection == {}
    assert snapshots[-1].roadmap_selection == {"main_nh": 0.75, "anti_pk": 0.25}
    assert all(row.scoring_profile_version == content.profile.version for row in snapshots)


def test_factors_persist_values_and_log_contributions(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """§6.10 and §9.5 — both, not either. Without the raw values a stored recommendation
    cannot explain itself; without the log contributions it is impossible to see which
    input moved between two runs.
    """
    _run(db, content, payload)

    entry = db.scalars(select(RecommendationEntry).order_by(RecommendationEntry.rank)).first()
    assert entry is not None
    assert entry.factors
    for factor in entry.factors.values():
        assert {"value", "weight", "log_contribution"} <= set(factor)


def test_the_reason_is_generated_not_empty(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """§9.5 — the "Why" line is read off the largest log contributions, never authored."""
    _run(db, content, payload)

    entry = db.scalars(select(RecommendationEntry).order_by(RecommendationEntry.rank)).first()
    assert entry is not None
    assert entry.reason.strip()


# ---------------------------------------------------------------------------
# §9.9 — hysteresis across runs
# ---------------------------------------------------------------------------


def test_a_second_identical_run_does_not_displace_the_incumbent(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """§9.9's anti-thrash, at the layer that owns it.

    The engine's own tests prove the 1.10× rule. What only the pipeline can prove is that
    the incumbent is read back from storage and fed in at all.
    """
    first = _run(db, content, payload)
    assert first.recommendations, "the first run ranked nothing, so there is no incumbent"

    second = _run(db, content, player_id=first.player_id, now=NOW + timedelta(minutes=5))

    assert second.recommendations[0].candidate_id == first.recommendations[0].candidate_id


def test_the_incumbent_is_readable_after_a_run(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """The ordering constraint that has no other test.

    ``load_incumbent`` must find the previous run's top entry, and the pipeline must call
    it *before* writing the new snapshot — persist first and each run becomes its own
    incumbent, comparing a candidate against itself and disabling anti-thrash silently.
    """
    first = _run(db, content, payload)
    incumbent = load_incumbent(db, first.player_id)

    assert incumbent is not None
    assert incumbent.candidate_id == first.recommendations[0].candidate_id


# ---------------------------------------------------------------------------
# §7.5 — request behaviour
# ---------------------------------------------------------------------------


def test_no_price_request_is_issued_while_the_cache_is_fresh(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """§7.5: *"No request at all while valid cached data exists."*

    The first run populates the cache; the second must not call the provider. The rule is
    about the provider's sustained-volume threshold, so the assertion is on call count.
    """
    client = RecordingPricesClient()
    first = _run(db, content, payload)
    set_active_roadmap(db, first.player_id, "main_nh", selection_weight=1.0)
    db.flush()

    _run(db, content, player_id=first.player_id, now=NOW + timedelta(minutes=1), client=client)
    assert client.calls, "the first priced run should have fetched the roadmap-scoped ids"

    calls_after_first = len(client.calls)
    _run(db, content, player_id=first.player_id, now=NOW + timedelta(minutes=5), client=client)

    assert len(client.calls) == calls_after_first


def test_prices_are_persisted_with_their_selection(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """A19 — ``selected_price_gp`` / ``selection_policy`` / ``selection_reason`` had no
    writer anywhere in the design. This is it: Step 5 computes them purely, Step 9 stores
    them, and ``selection_reason`` is what lets §15 explain any figure it shows.
    """
    client = RecordingPricesClient()
    first = _run(db, content, payload)
    set_active_roadmap(db, first.player_id, "main_nh", selection_weight=1.0)
    db.flush()

    _run(db, content, player_id=first.player_id, now=NOW + timedelta(minutes=1), client=client)

    rows = db.scalars(select(ItemPrice)).all()
    assert rows, "no price rows were written"
    for row in rows:
        assert row.source is PriceSourceLayer.LIVE
        assert row.selected_price_gp is not None
        assert row.selection_reason


def test_the_pipeline_runs_without_a_price_client(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """§7.5: *"no user-visible failure when a cached or static fallback exists."*

    An app started with no network still recommends. Its estimates are flagged
    low-confidence by §8.4's own rules, which is a different thing from failing.
    """
    result = _run(db, content, payload, client=None)

    assert result.snapshot_id is not None
    assert result.prices_written == 0


def test_no_roadmap_selected_means_no_price_request_at_all(
    db: Session, content: Content, payload: dict[str, Any]
) -> None:
    """§8.3's fetch scope is the *active roadmap's* transitive closure, so a player who has
    selected no roadmap references no items and the provider is never called.

    Not an edge case — it is the state of every account between its first sync and its
    first visit to the Roadmaps view, and pulling the full item economy to cover it would
    recreate the item database §3 rules out.
    """
    client = RecordingPricesClient()

    result = _run(db, content, payload, client=client)

    assert client.calls == []
    assert result.prices_written == 0


def test_a_recompute_needs_either_a_payload_or_a_player(db: Session, content: Content) -> None:
    with pytest.raises(ValueError, match="payload"):
        run_pipeline(db, content=content, now=NOW)


# ---------------------------------------------------------------------------
# The worker's single-flight guarantee
# ---------------------------------------------------------------------------


def _settings() -> Settings:
    return Settings(bind_address="127.0.0.1", api_token="token-for-tests")


def test_the_refresher_runs_the_pipeline(
    pipeline_sessions: sessionmaker[Session], content: Content, payload: dict[str, Any]
) -> None:
    with pipeline_sessions() as setup:
        first = _run(setup, content, payload)
        setup.commit()

    refresher = SingleFlightRefresher(pipeline_sessions, content, _settings(), clock=lambda: NOW)
    outcome = refresher.refresh(first.player_id)

    assert outcome.ran is True
    assert outcome.result is not None
    assert outcome.result.snapshot_id != first.snapshot_id


def test_a_refresh_arriving_while_the_lock_is_held_is_skipped_not_queued(
    pipeline_sessions: sessionmaker[Session], content: Content, payload: dict[str, Any]
) -> None:
    """§7.5's "at most one refresh attempt per recommendation run", against a concurrent
    caller rather than a loop.

    Two pipelines would not merely double the fetch: they would write the same
    ``CapabilityState`` rows from two different ``PlayerState`` reads, and the loser would
    silently overwrite the winner. A held lock stands in for the scheduled run that a
    manual refresh lands on top of — and the answer must be "no", not "later": a refresh
    happening right now is as good as the one being asked for, and a queue would let
    repeated clicking schedule the work the throttle exists to prevent.
    """
    with pipeline_sessions() as setup:
        first = _run(setup, content, payload)
        setup.commit()

    refresher = SingleFlightRefresher(pipeline_sessions, content, _settings(), clock=lambda: NOW)
    refresher._lock.acquire()
    try:
        assert refresher.busy is True
        outcome = refresher.refresh(first.player_id)
    finally:
        refresher._lock.release()

    assert outcome.ran is False
    assert outcome.result is None
    assert outcome.skipped_reason
