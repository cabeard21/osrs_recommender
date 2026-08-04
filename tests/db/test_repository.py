"""The per-aggregate helpers in :mod:`tracker.db.repository`.

The projection tests already exercise every read path this module owns, so what is left
here is what they cannot see: that the writers round-trip, that ``upsert`` overwrites the
one row its natural key names rather than accumulating, and that the §4.3 roadmap
selection comes back as a :class:`~tracker.domain.types.RoadmapSelection` **outside** the
``PlayerState`` — §16.1 passes it to ``recommend`` as its own parameter because it is live
configuration, not an observation of the account.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.db.conftest import NOW, VOIDWAKER_ITEM_ID
from tracker.db import repository
from tracker.db.models import ActiveRoadmap, SkillSnapshot
from tracker.domain.types import (
    Container,
    MilestoneClass,
    MilestoneKind,
    QuestStatus,
    Source,
    UnlockState,
)

PlayerFactory = Callable[..., int]


class TestPlayerLookup:
    def test_get_player_returns_none_for_an_unknown_id(self, session: Session) -> None:
        assert repository.get_player(session, 999) is None

    def test_require_player_raises_for_an_unknown_id(self, session: Session) -> None:
        with pytest.raises(repository.PlayerNotFoundError):
            repository.require_player(session, 999)

    def test_lookup_by_username(self, session: Session, new_player: PlayerFactory) -> None:
        player_id = new_player(session, username="zezima")
        session.commit()

        found = repository.get_player_by_username(session, "zezima")
        assert found is not None
        assert found.id == player_id
        assert repository.get_player_by_username(session, "nobody") is None


class TestSkillSnapshots:
    def test_appending_never_overwrites_the_history(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """§6.2 is a log — the §15 XP chart needs the rows the current value replaced."""
        player_id = new_player(session)
        for days_ago in (30, 10, 1):
            repository.append_skill_snapshot(
                session,
                player_id,
                skill="magic",
                level=99,
                xp=None,
                source=Source.RUNELITE,
                observed_at=NOW - timedelta(days=days_ago),
            )
        session.commit()

        stored = session.scalar(select(func.count()).select_from(SkillSnapshot))
        assert stored == 3
        assert len(repository.current_skill_snapshots(session, player_id)) == 1

    def test_current_snapshots_are_empty_for_a_player_with_no_history(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        session.commit()
        assert repository.current_skill_snapshots(session, player_id) == []


class TestFactUpserts:
    """Each fact table is keyed by its natural key and overwritten in place (§6.3–§6.6)."""

    def test_unlock_upsert_replaces_rather_than_accumulates(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        repository.upsert_unlock(
            session,
            player_id,
            "rigour",
            state=UnlockState.AVAILABLE,
            source=Source.RUNELITE,
            observed_at=NOW - timedelta(days=1),
        )
        session.commit()
        repository.upsert_unlock(
            session,
            player_id,
            "rigour",
            state=UnlockState.UNLOCKED,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()

        rows = repository.get_unlocks(session, player_id)
        assert len(rows) == 1
        assert rows[0].state is UnlockState.UNLOCKED
        assert rows[0].observed_at == NOW

    def test_quest_state_upsert_round_trips(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        repository.upsert_quest_state(
            session,
            player_id,
            "desert_treasure_i",
            status=QuestStatus.IN_PROGRESS,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()
        repository.upsert_quest_state(
            session,
            player_id,
            "desert_treasure_i",
            status=QuestStatus.COMPLETE,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()

        rows = repository.get_quest_states(session, player_id)
        assert [(row.quest_id, row.status) for row in rows] == [
            ("desert_treasure_i", QuestStatus.COMPLETE)
        ]

    def test_observed_item_is_keyed_per_container(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """The same item in two containers is two rows (§6.5), not one overwritten."""
        player_id = new_player(session)
        for container in (Container.BANK, Container.EQUIPMENT):
            repository.upsert_observed_item(
                session,
                player_id,
                VOIDWAKER_ITEM_ID,
                container,
                quantity=1,
                source=Source.RUNELITE,
                observed_at=NOW,
            )
        session.commit()

        rows = repository.get_observed_items(session, player_id)
        assert {row.container for row in rows} == {Container.BANK, Container.EQUIPMENT}

    def test_a_zero_quantity_row_is_stored_not_normalized_away(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """*"Looked, and it was not there"* is a fact worth keeping (§4.5)."""
        player_id = new_player(session)
        repository.upsert_observed_item(
            session,
            player_id,
            VOIDWAKER_ITEM_ID,
            Container.BANK,
            quantity=0,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()

        rows = repository.get_observed_items(session, player_id)
        assert [row.quantity for row in rows] == [0]

    def test_container_scan_records_the_latest_full_sighting(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        repository.record_container_scan(
            session,
            player_id,
            Container.BANK,
            scanned_at=NOW - timedelta(days=21),
            source=Source.RUNELITE,
        )
        session.commit()
        repository.record_container_scan(
            session, player_id, Container.BANK, scanned_at=NOW, source=Source.RUNELITE
        )
        session.commit()

        rows = repository.get_container_scans(session, player_id)
        assert len(rows) == 1
        assert rows[0].scanned_at == NOW

    def test_milestone_upsert_preserves_a_null_attested_at(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """A7 — recording practice must not silently count as having been prompted."""
        player_id = new_player(session)
        repository.upsert_milestone(
            session,
            player_id,
            "comfortable_4_way_switches",
            kind=MilestoneKind.SELF_ATTESTED,
            class_=MilestoneClass.EXECUTION,
            achieved=False,
            source=Source.DERIVED,
            observed_at=NOW,
            last_practiced_at=NOW - timedelta(days=2),
        )
        session.commit()

        rows = repository.get_milestones(session, player_id)
        assert len(rows) == 1
        assert rows[0].attested_at is None
        assert rows[0].last_practiced_at == NOW - timedelta(days=2)


class TestRoadmapSelection:
    """§6.12, A13 — and §16.1's insistence that this is not part of ``PlayerState``."""

    def test_selection_round_trips_from_active_roadmap_rows(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        repository.set_active_roadmap(session, player_id, "main_nh", selection_weight=0.75)
        repository.set_active_roadmap(session, player_id, "anti_pk", selection_weight=0.25)
        session.commit()

        selection = repository.roadmap_selection(session, player_id)

        assert selection.weights == {"main_nh": 0.75, "anti_pk": 0.25}
        assert selection.normalized() == {"main_nh": 0.75, "anti_pk": 0.25}

    def test_weights_are_stored_raw_and_normalized_only_on_read(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """§6.12 — deselecting one roadmap must not rescale the others' stored values."""
        player_id = new_player(session)
        repository.set_active_roadmap(session, player_id, "main_nh", selection_weight=0.6)
        repository.set_active_roadmap(session, player_id, "anti_pk", selection_weight=0.6)
        session.commit()

        assert repository.roadmap_selection(session, player_id).weights == {
            "main_nh": 0.6,
            "anti_pk": 0.6,
        }
        assert repository.roadmap_selection(session, player_id).normalized() == {
            "main_nh": 0.5,
            "anti_pk": 0.5,
        }

        repository.clear_active_roadmap(session, player_id, "anti_pk")
        session.commit()

        stored = session.scalars(
            select(ActiveRoadmap).where(ActiveRoadmap.player_id == player_id)
        ).all()
        assert [(row.roadmap_id, row.selection_weight) for row in stored] == [("main_nh", 0.6)]
        assert repository.roadmap_selection(session, player_id).normalized() == {"main_nh": 1.0}

    def test_no_selection_is_empty_not_an_error(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """Every account starts here; an exception would make first run a failure path."""
        player_id = new_player(session)
        session.commit()

        selection = repository.roadmap_selection(session, player_id)
        assert selection.weights == {}
        assert selection.normalized() == {}

    def test_clearing_a_roadmap_that_was_never_selected_is_silent(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        session.commit()
        repository.clear_active_roadmap(session, player_id, "main_nh")
        session.commit()
        assert repository.roadmap_selection(session, player_id).weights == {}

    def test_setting_the_same_roadmap_twice_changes_the_weight(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        repository.set_active_roadmap(session, player_id, "main_nh", selection_weight=0.4)
        session.commit()
        repository.set_active_roadmap(session, player_id, "main_nh", selection_weight=1.0)
        session.commit()

        assert repository.roadmap_selection(session, player_id).weights == {"main_nh": 1.0}
