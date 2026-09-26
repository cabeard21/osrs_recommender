"""M3 migration from a populated pre-retirement database preserves account facts."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from tracker.db.session import build_engine

PRE_M3_REVISION = "e2f8a34b91c7"
ACCOUNT_TABLES = (
    "player",
    "skill_snapshot",
    "unlock",
    "quest_state",
    "observed_item",
    "container_scan",
    "item_price",
    "sync_event",
)
RETIRED_TABLES = (
    "advisor_message",
    "advisor_conversation",
    "guidance_note",
    "recommendation_entry",
    "recommendation_snapshot",
    "capability_state",
    "active_roadmap",
    "practice_event",
    "milestone",
)
SELECTED_PRICE_COLUMNS = {"selected_price_gp", "selection_policy", "selection_reason"}
RAW_PRICE_COLUMNS = {
    "item_id",
    "high_price_gp",
    "high_trade_at",
    "low_price_gp",
    "low_trade_at",
    "provider",
    "fetched_at",
    "source",
}


def _config(database_url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "tracker" / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _rows(connection, table: str) -> list[tuple]:
    return sorted(tuple(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{table}"'))


def test_retirement_migration_preserves_account_facts(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'pre_m3.sqlite'}"
    config = _config(database_url)
    command.upgrade(config, PRE_M3_REVISION)
    engine = build_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO player (id, username, display_name, created_at, last_sync_at, "
            "combat_level, quest_points, gp_sensitivity, account_type, members) VALUES "
            "(1, 'account', 'Account', '2026-09-01', '2026-09-02', 100, 200, 'high', 'ironman', 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO skill_snapshot (player_id, skill, level, xp, source, observed_at) "
            "VALUES (1, 'attack', 80, 1986068, 'runelite', '2026-09-02')"
        )
        connection.exec_driver_sql(
            "INSERT INTO unlock (player_id, key, state, source, observed_at) "
            "VALUES (1, 'ancient_magicks', 'unlocked', 'runelite', '2026-09-02')"
        )
        connection.exec_driver_sql(
            "INSERT INTO quest_state (player_id, quest_id, status, source, observed_at) "
            "VALUES (1, 'desert_treasure_i', 'complete', 'runelite', '2026-09-02')"
        )
        connection.exec_driver_sql(
            "INSERT INTO observed_item "
            "(player_id, item_id, container, quantity, source, observed_at) "
            "VALUES (1, 4151, 'bank', 1, 'runelite', '2026-09-02')"
        )
        connection.exec_driver_sql(
            "INSERT INTO container_scan (player_id, container, scanned_at, source) "
            "VALUES (1, 'bank', '2026-09-02', 'runelite')"
        )
        connection.exec_driver_sql(
            "INSERT INTO item_price (item_id, high_price_gp, high_trade_at, "
            "low_price_gp, low_trade_at, selected_price_gp, selection_policy, "
            "selection_reason, provider, fetched_at, source) VALUES "
            "(4151, 1000000, '2026-09-01', 900000, '2026-08-31', 1000000, "
            "'acquisition_cost', 'recent high', 'wiki', '2026-09-02', 'live')"
        )
        connection.exec_driver_sql(
            "INSERT INTO sync_event (player_id, source, received_at, accepted) "
            "VALUES (1, 'runelite', '2026-09-02', 1)"
        )
        connection.exec_driver_sql(
            'INSERT INTO milestone (player_id, key, kind, "class", achieved, source, '
            "observed_at) "
            "VALUES (1, 'practice', 'self_attested', 'execution', 1, 'manual', '2026-09-02')"
        )
        connection.exec_driver_sql(
            "INSERT INTO active_roadmap (player_id, roadmap_id, selection_weight) "
            "VALUES (1, 'main', 1.0)"
        )
        before = {
            table: _rows(connection, table) for table in ACCOUNT_TABLES if table != "item_price"
        }
        raw_before = connection.exec_driver_sql(
            "SELECT item_id, high_price_gp, high_trade_at, low_price_gp, low_trade_at, "
            "provider, fetched_at, source FROM item_price"
        ).all()
    engine.dispose()
    command.upgrade(config, "head")

    engine = build_engine(database_url)
    with engine.connect() as connection:
        names = set(inspect(connection).get_table_names())
        assert set(ACCOUNT_TABLES) <= names
        assert not set(RETIRED_TABLES) & names
        assert {table: _rows(connection, table) for table in before} == before
        raw_after = connection.exec_driver_sql(
            "SELECT item_id, high_price_gp, high_trade_at, low_price_gp, low_trade_at, "
            "provider, fetched_at, source FROM item_price"
        ).all()
        assert raw_after == raw_before
        columns = {column["name"] for column in inspect(connection).get_columns("item_price")}
        assert RAW_PRICE_COLUMNS <= columns
        assert not SELECTED_PRICE_COLUMNS & columns
        player_columns = {column["name"] for column in inspect(connection).get_columns("player")}
        assert "gp_sensitivity" in player_columns
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()


def test_retirement_downgrade_requires_restoring_backup(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'rollback.sqlite'}"
    config = _config(database_url)
    command.upgrade(config, "head")

    with pytest.raises(RuntimeError, match="restore the verified pre-M3 SQLite backup"):
        command.downgrade(config, PRE_M3_REVISION)
