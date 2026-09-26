"""Account fact repository lookups, history, and upsert behavior."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.db.conftest import NOW, VOIDWAKER_ITEM_ID
from tracker.db import repository
from tracker.db.models import SkillSnapshot
from tracker.domain.types import (
    Container,
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
    def test_legacy_alias_and_canonical_rows_select_one_current_skill(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        old = repository.append_skill_snapshot(
            session,
            player_id,
            skill="runecrafting",
            level=20,
            xp=4470,
            source=Source.WISE_OLD_MAN,
            observed_at=NOW - timedelta(days=1),
        )
        fresh = repository.append_skill_snapshot(
            session,
            player_id,
            skill="runecraft",
            level=21,
            xp=5018,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()

        assert repository.current_skill_snapshots(session, player_id) == [fresh]
        assert {row.id for row in session.scalars(select(SkillSnapshot))} == {old.id, fresh.id}

    def test_alias_selection_uses_time_source_canonical_key_then_row_id(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        rows = [
            repository.append_skill_snapshot(
                session,
                player_id,
                skill=skill,
                level=level,
                xp=level,
                source=source,
                observed_at=at,
            )
            for skill, level, source, at in (
                ("runecraft", 10, Source.RUNELITE, NOW - timedelta(days=1)),
                ("runecrafting", 11, Source.WISE_OLD_MAN, NOW),
                ("runecrafting", 12, Source.RUNELITE, NOW),
                ("runecraft", 13, Source.RUNELITE, NOW),
                ("runecraft", 14, Source.RUNELITE, NOW),
            )
        ]
        session.commit()

        assert repository.current_skill_snapshots(session, player_id) == [rows[-1]]

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
