"""Fixtures for the persistence tests.

The database is built the way ``tests/db/test_migrations.py`` already builds one — a real
SQLite file under ``tmp_path`` opened through :func:`tracker.db.session.build_engine`, so
the ``foreign_keys=ON`` pragma is live, plus ``Base.metadata.create_all``. The schema is
created from the models rather than by running Alembic because that is the *other* test's
subject; here a migration failure should fail ``test_migrations.py``, not every projection
assertion at once.

**Timestamps are aware UTC**, and must be: §6's columns bind through
:class:`tracker.db.types.UtcDateTime`, which rejects a naive value rather than guessing
what it meant. That is what lets a projected timestamp be subtracted from an aware ``now``
in the engine — the comparison §4.5 rests on, and the one these tests share a clock with.

Builders are handed out as fixtures returning callables rather than as importable module
functions: ``conftest`` modules from sibling test directories share one flat namespace, so
a plain ``from conftest import ...`` would resolve unpredictably, while a fixture is looked
up per directory and cannot collide.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from tracker.content.loader import Content
from tracker.content.schema import (
    Capability,
    Item,
    KappaPresets,
    Milestone,
    Quest,
    ScoringProfile,
    ScoringWeights,
    Skill,
)
from tracker.db.models import Base, Player
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import GpSensitivity

#: A fixed clock. Aware UTC — see the module docstring.
NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)

#: An arbitrary but valid numeric OSRS item id, used wherever a test needs one (§10.5).
VOIDWAKER_ITEM_ID = 27_690

_PROFILE = ScoringProfile(
    version=1,
    kappa_gp=KappaPresets(high=8_000_000, normal=20_000_000, low=50_000_000),
    weights=ScoringWeights(
        pvp_value=1.0, leverage=0.8, proximity=0.6, effort_decay=0.7, cost_decay=0.5
    ),
)


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


def _index(objects: Iterable[Any]) -> dict[str, Any]:
    return {obj.id: obj for obj in objects}


def _build_content(
    *,
    capabilities: Sequence[Capability] = (),
    skills: Sequence[Skill] = (),
    quests: Sequence[Quest] = (),
    items: Sequence[Item] = (),
    milestones: Sequence[Milestone] = (),
) -> Content:
    """A corpus containing only what a test names, so a failure names one rule."""
    return Content(
        profile=_PROFILE,
        capabilities=_index(capabilities),
        skills=_index(skills),
        quests=_index(quests),
        items=_index(items),
        milestones=_index(milestones),
    )


@pytest.fixture
def new_player() -> Callable[..., int]:
    """Insert a ``Player`` row and return its id."""
    return _new_player


@pytest.fixture
def build_content() -> Callable[..., Content]:
    """Assemble a :class:`Content` from just the objects a test names."""
    return _build_content


@pytest.fixture
def now() -> datetime:
    return NOW
