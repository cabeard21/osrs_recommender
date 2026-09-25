from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from tracker.accounts.service import AccountService
from tracker.db.models import Base, Player, QuestState, SkillSnapshot
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import QuestStatus, Source
from tracker.mcp.accounts import ConfiguredAccount
from tracker.mcp.server import build_server, create_http_app
from tracker.mcp.settings import MCPSettings
from tracker.quest_cape.service import CompleteQuest, TrainSkill


def test_account_snapshot_normalizes_legacy_wom_skill_without_changing_history(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'alias.db'}")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    now = datetime(2026, 9, 1, tzinfo=UTC)
    with sessions.begin() as db:
        db.add(Player(id=1, username="fixture", display_name="Fixture", created_at=now))
        db.flush()
        db.add(
            SkillSnapshot(
                player_id=1,
                skill="runecrafting",
                level=20,
                xp=4470,
                source=Source.WISE_OLD_MAN,
                observed_at=now,
            )
        )

    account = AccountService(sessions).get_snapshot(1)
    assert set(account.skills) == {"runecraft"}
    assert account.skills["runecraft"].level == 20
    assert account.summary()["skills"].keys() == {"runecraft"}
    with sessions() as db:
        assert db.query(SkillSnapshot).one().skill == "runecrafting"
    engine.dispose()


def test_snapshot_and_evaluations_are_read_only(tmp_path, service, monkeypatch):
    from tracker.recommendations import engine as recommendation_engine

    def forbidden(*args, **kwargs):
        raise AssertionError("read path invoked recommendations")

    monkeypatch.setattr(recommendation_engine, "recommend", forbidden)
    engine = build_engine(f"sqlite:///{tmp_path / 'account.db'}")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    now = datetime(2026, 9, 1, tzinfo=UTC)
    with sessions.begin() as db:
        db.add(
            Player(
                id=1,
                username="fixture",
                display_name="Fixture",
                created_at=now,
                last_sync_at=now,
                quest_points=10,
            )
        )
        db.flush()
        db.add(
            SkillSnapshot(
                player_id=1,
                skill="agility",
                level=66,
                xp=None,
                source=Source.RUNELITE,
                observed_at=now,
            )
        )
        db.add(
            SkillSnapshot(
                player_id=1,
                skill="agility",
                level=50,
                xp=None,
                source=Source.HISCORES,
                observed_at=now,
            )
        )
        for key in "abcde":
            db.add(
                QuestState(
                    player_id=1,
                    quest_id=key,
                    status=QuestStatus.NOT_STARTED,
                    source=Source.RUNELITE,
                    observed_at=now,
                )
            )

    def dump():
        with engine.connect() as connection:
            return {
                table.name: list(connection.execute(table.select()))
                for table in Base.metadata.sorted_tables
            }

    before = dump()
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    accounts = AccountService(sessions)
    account = accounts.get_snapshot(1)
    assert account.skills["agility"].level == 66
    assert account.skills["agility"].xp is None
    assert "magic" not in account.skills
    assert account.quest_observations["a"].source == "runelite"
    service.get_goal_status(account)
    service.get_available_actions(account)
    service.evaluate_action(account, CompleteQuest(type="complete_quest", quest="a"))
    assert dump() == before
    service.evaluate_action(
        account, TrainSkill(type="train_skill", skill="agility", target_level=70)
    )
    assert dump() == before
    with pytest.raises(ValueError):
        service.evaluate_action(account, CompleteQuest(type="complete_quest", quest="invalid"))
    assert dump() == before
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for s in statements
    )
    assert accounts.get_snapshot(1) == account
    app = create_http_app(
        build_server(ConfiguredAccount(accounts, 1), service),
        MCPSettings(enabled=True, player_id=1),
    )
    with TestClient(app, base_url="http://127.0.0.1:8503") as client:
        for action in (
            {"type": "complete_quest", "quest": "a"},
            {"type": "train_skill", "skill": "agility", "target_level": 70},
        ):
            response = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "evaluate_action", "arguments": {"action": action}},
                },
            )
            assert response.status_code == 200
            assert not response.json()["result"].get("isError")
            assert dump() == before
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for s in statements
    )
    engine.dispose()


def test_separate_wal_reader_observes_commits_and_restart(tmp_path):
    """The sidecar sees live writer commits, not a copied or cached desktop database."""
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    writer = build_engine(url)
    reader = build_engine(url)
    Base.metadata.create_all(writer)
    writes = build_session_factory(writer)
    now = datetime(2026, 9, 24, tzinfo=UTC)
    try:
        with writes.begin() as db:
            db.add(Player(id=1, username="live", display_name="Live", created_at=now))
        accounts = AccountService(build_session_factory(reader))
        before = accounts.get_snapshot(1)
        with writes.begin() as db:
            db.add(
                SkillSnapshot(
                    player_id=1,
                    skill="agility",
                    level=70,
                    xp=737627,
                    source=Source.RUNELITE,
                    observed_at=now,
                )
            )
            db.add(
                QuestState(
                    player_id=1,
                    quest_id="a",
                    status=QuestStatus.COMPLETE,
                    source=Source.RUNELITE,
                    observed_at=now,
                )
            )
            db.flush()
            assert accounts.get_snapshot(1).fingerprint == before.fingerprint
        after = accounts.get_snapshot(1)
        assert after.skills["agility"].level == 70
        assert after.quests["a"] == QuestStatus.COMPLETE
        assert after.fingerprint != before.fingerprint
        reader.dispose()
        restarted = build_engine(url)
        try:
            assert AccountService(build_session_factory(restarted)).get_snapshot(1) == after
        finally:
            restarted.dispose()
    finally:
        reader.dispose()
        writer.dispose()
