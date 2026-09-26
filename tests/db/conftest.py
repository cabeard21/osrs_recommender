"""SQLite account fact fixtures for repository tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tracker.db.models import Base, Player
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import GpSensitivity

#: A fixed clock. Aware UTC — see the module docstring.
NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)

#: An arbitrary but valid numeric OSRS item id, used wherever a test needs one (§10.5).
VOIDWAKER_ITEM_ID = 27_690


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    """A session on an empty database with the real schema."""
    engine = build_engine(f"sqlite:///{tmp_path / 'projection.db'}")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def _new_player(
    session: Session,
    *,
    username: str = "zezima",
    last_sync_at: datetime | None = NOW,
    combat_level: int | None = 126,
    quest_points: int | None = 300,
    gp_sensitivity: GpSensitivity = GpSensitivity.NORMAL,
) -> int:
    """Insert a player and return its id.

    The defaults describe a *synced* account, because most tests here are about some
    other fact and would otherwise have to restate a sync that is not what they test.
    The tests that care about A6 pass ``last_sync_at=None`` explicitly.
    """
    player = Player(
        username=username,
        display_name=username.title(),
        created_at=NOW - timedelta(days=365),
        last_sync_at=last_sync_at,
        combat_level=combat_level,
        quest_points=quest_points,
        gp_sensitivity=gp_sensitivity,
    )
    session.add(player)
    session.flush()
    return player.id


@pytest.fixture
def new_player() -> Callable[..., int]:
    """Insert a ``Player`` row and return its id."""
    return _new_player
