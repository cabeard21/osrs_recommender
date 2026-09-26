"""Focused factual dashboard contracts after recommendation retirement."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import Settings
from tracker.db.models import Base, Player
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import GpSensitivity
from tracker.ui.gear import progression_views
from tracker.ui.read_model import (
    dashboard_view,
    first_player_id,
    set_gp_sensitivity,
    set_tracked_username,
    settings_view,
    unlock_rows,
)
from tracker.ui.view_model import skill_row


@pytest.fixture
def sessions(tmp_path: Path) -> sessionmaker[Session]:
    engine = build_engine(f"sqlite:///{tmp_path / 'ui.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_dashboard_shows_account_and_quest_facts_without_a_ranking(
    sessions: sessionmaker[Session],
) -> None:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    with sessions() as session:
        session.add(Player(username="player", display_name="Player", created_at=now))
        session.commit()
        player_id = first_player_id(session)
        assert player_id is not None
        view = dashboard_view(
            session,
            player_id,
            now,
            quest_cape_completed=12,
            quest_cape_total=80,
            quest_cape_unknown=3,
            quest_cape_available=5,
        )
    assert view.display_name == "Player"
    assert view.quest_cape_completed == 12
    assert view.quest_cape_unknown == 3
    assert "never synced" in view.last_sync_at_label
    assert len(view.staleness_notes) == 3


def test_gp_preference_is_stored_but_factual_view_does_not_apply_it(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as session:
        player_id = set_tracked_username(session, None, "player")
        session.commit()
        set_gp_sensitivity(session, player_id, GpSensitivity.HIGH)
        settings = Settings(bind_address="127.0.0.1", api_token="test")
        view = settings_view(session, player_id, settings)
    assert view.gp_sensitivity is GpSensitivity.HIGH


def test_unranked_skill_remains_unranked() -> None:
    row = skill_row(skill_id="attack", name="Attack", is_combat=True, level=1, xp=None)
    assert row.level is None
    assert row.level_label == "unranked"


def test_unlocks_do_not_require_legacy_capability_content(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as session:
        player_id = set_tracked_username(session, None, "player")
        session.commit()
        assert unlock_rows(session, player_id, None) == ()  # type: ignore[arg-type]


def test_gear_dashboard_passes_the_same_snapshot_prices_and_time_to_service() -> None:
    snapshot = object()
    prices = {4151: object()}
    now = datetime(2026, 9, 26, tzinfo=UTC)
    calls = []

    class RecordingGearService:
        def progression(self, received_snapshot, **kwargs):  # type: ignore[no-untyped-def]
            calls.append((received_snapshot, kwargs))
            return {"style": kwargs["style"], "items": []}

    views = progression_views(  # type: ignore[arg-type]
        RecordingGearService(), snapshot, prices, now
    )
    assert [view["style"] for view in views] == ["melee", "ranged", "magic"]
    assert all(received is snapshot for received, _ in calls)
    assert all(kwargs["price_records"] is prices and kwargs["now"] is now for _, kwargs in calls)


def test_gear_dashboard_collects_every_service_progression_page() -> None:
    snapshot = object()
    prices = {}
    now = datetime(2026, 9, 26, tzinfo=UTC)
    calls = []

    class PagedGearService:
        def progression(self, received_snapshot, **kwargs):  # type: ignore[no-untyped-def]
            calls.append((received_snapshot, kwargs))
            offset = kwargs.get("offset", 0)
            return {
                "style": kwargs["style"],
                "items": [f"{kwargs['style']}-{offset}"],
                "total": 2,
                "next_offset": 1 if offset == 0 else None,
            }

    views = progression_views(PagedGearService(), snapshot, prices, now)  # type: ignore[arg-type]

    assert [view["items"] for view in views] == [
        ["melee-0", "melee-1"],
        ["ranged-0", "ranged-1"],
        ["magic-0", "magic-1"],
    ]
    assert [kwargs.get("offset", 0) for _, kwargs in calls] == [0, 1, 0, 1, 0, 1]
    assert all(received is snapshot for received, _ in calls)
    assert all(kwargs["price_records"] is prices and kwargs["now"] is now for _, kwargs in calls)
