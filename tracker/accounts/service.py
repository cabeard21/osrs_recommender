"""A read transaction over existing sync tables. No refresh or recommendation work."""

from sqlalchemy.orm import Session, sessionmaker

from tracker.accounts.snapshot import AccountSnapshot, Observation
from tracker.db import repository
from tracker.domain.types import SkillState


class AccountService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def get_snapshot(self, player_id: int) -> AccountSnapshot:
        with self.sessions(autoflush=False) as session:
            # sqlite3's legacy transaction mode does not BEGIN for SELECT statements.
            if session.get_bind().dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN")
            player = repository.require_player(session, player_id)
            quests = repository.get_quest_states(session, player_id)
            return AccountSnapshot(
                player_id=player.id,
                username=player.username,
                skills={
                    row.skill: SkillState(row.level, row.xp, row.source, row.observed_at)
                    for row in repository.current_skill_snapshots(session, player_id)
                },
                quests={row.quest_id: row.status for row in quests},
                quest_observations={
                    row.quest_id: Observation(row.source.value, row.observed_at) for row in quests
                },
                unlocks={r.key: r.state for r in repository.get_unlocks(session, player_id)},
                quest_points=player.quest_points,
                combat_level=player.combat_level,
                members=player.members,
                last_sync_at=player.last_sync_at,
            )
