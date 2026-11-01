"""A read transaction over existing sync tables. No refresh or recommendation work."""

from sqlalchemy.orm import Session, sessionmaker

from tracker.accounts.snapshot import (
    AccountSnapshot,
    ContainerScanFact,
    Observation,
    ObservedItemFact,
)
from tracker.db import repository
from tracker.domain.skills import canonical_skill_name
from tracker.domain.types import SkillState


class AccountService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def get_snapshot(self, player_id: int) -> AccountSnapshot:
        with self.sessions(autoflush=False) as session:
            # sqlite3's legacy transaction mode does not BEGIN for SELECT statements.
            if session.get_bind().dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN")
            return self.read_snapshot(session, player_id)

    @staticmethod
    def read_snapshot(session: Session, player_id: int) -> AccountSnapshot:
        player = repository.require_player(session, player_id)
        quests = repository.get_quest_states(session, player_id)
        scans = {
            row.container: ContainerScanFact(
                container=row.container, scanned_at=row.scanned_at, source=row.source.value
            )
            for row in repository.get_container_scans(session, player_id)
        }
        items = {
            (row.item_id, row.container): ObservedItemFact(
                item_id=row.item_id,
                container=row.container,
                quantity=row.quantity,
                source=row.source.value,
                observed_at=row.observed_at,
            )
            for row in repository.get_observed_items(session, player_id)
            if row.container not in scans or row.observed_at >= scans[row.container].scanned_at
        }
        return AccountSnapshot(
            player_id=player.id,
            username=player.username,
            skills={
                canonical_skill_name(row.skill): SkillState(
                    row.level, row.xp, row.source, row.observed_at
                )
                for row in repository.current_skill_snapshots(session, player_id)
            },
            quests={row.quest_id: row.status for row in quests},
            quest_observations={
                row.quest_id: Observation(row.source.value, row.observed_at) for row in quests
            },
            unlocks={r.key: r.state for r in repository.get_unlocks(session, player_id)},
            observed_items=items,
            container_scans=scans,
            quest_points=player.quest_points,
            combat_level=player.combat_level,
            members=player.members,
            last_sync_at=player.last_sync_at,
        )
