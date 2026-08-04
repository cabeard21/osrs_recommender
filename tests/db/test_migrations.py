"""Alembic round-trip on a seeded database (§6.13, Step 3a exit criteria).

An empty-schema round trip only proves the DDL is syntactically valid. The task list
deliberately asks for `upgrade head -> downgrade base -> upgrade head` *on a database that
already holds rows*, because that is the case an empty round trip cannot catch: with
`foreign_keys=ON` (`tracker.db.session`), `DROP TABLE` on a parent performs an implicit
delete of every row that still has a live foreign-key reference to it, and it is only with
real rows in place that a `downgrade()` written in the wrong table order would surface.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from tracker.db.models import ActiveRoadmap, Base, Milestone, Player, SyncEvent, Unlock
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import (
    GpSensitivity,
    MilestoneClass,
    MilestoneKind,
    Source,
    UnlockState,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "tracker" / "migrations"))
    # Override whatever env.py would otherwise resolve (Settings/TRACKER_DATABASE_URL) so
    # this test is hermetic regardless of the developer's own config.yaml.
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _seed_one_row_per_representative_table(engine: Engine) -> int:
    """Populate enough of the schema to exercise every FK relationship once.

    Returns the seeded player id. Covers a current-state table with a composite key
    (``Unlock``), a nullable-enum column (``Milestone.freshness`` left unset), a
    ``CASCADE`` FK (``ActiveRoadmap``), and the ``SET NULL`` FK with ``player_id IS NULL``
    (``SyncEvent``, A17) in the same pass.
    """
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        player = Player(
            username="zezima",
            display_name="Zezima",
            created_at=NOW,
            gp_sensitivity=GpSensitivity.NORMAL,
        )
        session.add(player)
        session.flush()

        session.add(
            Unlock(
                player_id=player.id,
                key="ancient_magicks",
                state=UnlockState.UNLOCKED,
                source=Source.RUNELITE,
                observed_at=NOW,
            )
        )
        session.add(
            Milestone(
                player_id=player.id,
                key="comfortable_4_way_switches",
                kind=MilestoneKind.SELF_ATTESTED,
                class_=MilestoneClass.EXECUTION,
                achieved=True,
                source=Source.MANUAL,
                observed_at=NOW,
            )
        )
        session.add(ActiveRoadmap(player_id=player.id, roadmap_id="main_nh", selection_weight=1.0))
        session.add(
            SyncEvent(
                player_id=None,
                source=Source.RUNELITE,
                remote_addr="100.64.0.1",
                received_at=NOW,
                accepted=False,
                reason="invalid bearer token",
            )
        )
        session.commit()
        return player.id


class TestAlembicRoundTrip:
    """upgrade -> downgrade -> upgrade must survive a populated database (§6.13)."""

    def test_upgrade_downgrade_upgrade_on_seeded_database(self, tmp_path: Path) -> None:
        db_path = tmp_path / "roundtrip.db"
        database_url = f"sqlite:///{db_path}"
        config = _alembic_config(database_url)

        command.upgrade(config, "head")

        engine = build_engine(database_url)
        _seed_one_row_per_representative_table(engine)
        engine.dispose()

        command.downgrade(config, "base")
        command.upgrade(config, "head")

        engine = build_engine(database_url)
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        assert set(Base.metadata.tables) <= table_names, (
            "every model table must exist again after the round trip"
        )

        with Session(engine) as session:
            # The round trip recreates an *empty* schema — the seeded rows do not (and
            # should not) survive a downgrade to base. What matters is that the schema
            # is usable again, not that data persisted through a full teardown.
            assert session.scalar(select(Player)) is None
            fresh_player = Player(
                username="post_roundtrip",
                display_name="Post Roundtrip",
                created_at=NOW,
                gp_sensitivity=GpSensitivity.NORMAL,
            )
            session.add(fresh_player)
            session.commit()
            assert session.scalar(select(Player).where(Player.username == "post_roundtrip"))
        engine.dispose()

    def test_alembic_version_table_records_exactly_one_head(self, tmp_path: Path) -> None:
        """No branch point yet — a single revision, not a merge of parallel heads."""
        db_path = tmp_path / "single_head.db"
        config = _alembic_config(f"sqlite:///{db_path}")

        command.upgrade(config, "head")

        engine = build_engine(f"sqlite:///{db_path}")
        with engine.connect() as connection:
            rows = connection.exec_driver_sql("SELECT version_num FROM alembic_version").all()
        engine.dispose()
        assert len(rows) == 1


class TestSyncEventUnauthenticatedWrites:
    """§6.11, §11.3, A17 — the audit row rejected requests must produce."""

    @pytest.fixture
    def session(self, tmp_path: Path) -> Iterator[Session]:
        engine = build_engine(f"sqlite:///{tmp_path / 'sync_event.db'}")
        Base.metadata.create_all(engine)
        factory = build_session_factory(engine)
        with factory() as db_session:
            yield db_session
        engine.dispose()

    def test_player_id_null_is_accepted_for_a_rejected_request(self, session: Session) -> None:
        """An unauthenticated caller has no trusted identity to attach the row to (A17)."""
        event = SyncEvent(
            player_id=None,
            source=Source.RUNELITE,
            remote_addr="100.64.0.7",
            received_at=NOW,
            accepted=False,
            reason="missing bearer token",
        )
        session.add(event)
        session.commit()

        stored = session.scalar(select(SyncEvent))
        assert stored is not None
        assert stored.player_id is None
        assert stored.accepted is False
        assert stored.reason == "missing bearer token"
        assert stored.remote_addr == "100.64.0.7"

    def test_deleting_the_named_player_nulls_the_reference_not_the_row(
        self, session: Session
    ) -> None:
        """The audit trail must outlive the player it names — SET NULL, not CASCADE."""
        player = Player(
            username="zezima",
            display_name="Zezima",
            created_at=NOW,
            gp_sensitivity=GpSensitivity.NORMAL,
        )
        session.add(player)
        session.flush()

        event = SyncEvent(
            player_id=player.id,
            source=Source.RUNELITE,
            received_at=NOW,
            accepted=True,
        )
        session.add(event)
        session.commit()
        event_id = event.id

        session.delete(player)
        session.commit()
        # ``build_session_factory`` uses ``expire_on_commit=False`` (deliberately, for
        # Step 3b's read-heavy projection) so already-loaded objects are not refreshed
        # from the row SQLite mutated via ON DELETE SET NULL. Force that reload rather
        # than reading a stale in-memory ``player_id`` — the whole point of this test.
        session.expire_all()

        survivor = session.get(SyncEvent, event_id)
        assert survivor is not None, "SyncEvent must survive its player's deletion"
        assert survivor.player_id is None
