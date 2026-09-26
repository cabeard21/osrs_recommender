"""Fixtures for the sync API tests (§11, §12).

The application under test is the real one — ``tracker.api.app.create_app`` over a real
SQLite file under ``tmp_path``, with the schema built from the models. Nothing is
monkeypatched and no route is stubbed, because the properties these tests assert are
*wiring* properties: that authentication is inherited by construction (§11.2), that a
rejection reaches the audit table (§11.3). A test double for either would assert only that
the double behaves as written.

Builders are handed out as fixtures returning callables rather than as importable module
functions, matching ``tests/db/conftest.py``: sibling ``conftest`` modules share one flat
namespace, so ``from conftest import ...`` resolves unpredictably.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from tracker.app import create_app
from tracker.config.settings import Settings
from tracker.content.loader import Content, load_content
from tracker.db.models import Base, SyncEvent
from tracker.db.session import build_engine, build_session_factory

#: The token the test application is configured with. A literal, not a generated value:
#: a failing test should print a token whose identity is obvious.
API_TOKEN = "test-token-1234567890"

#: A fixed clock, aware UTC — §4.5 comparisons need an offset (see tests/db/conftest.py).
NOW = datetime(2026, 8, 4, 15, 18, 41, tzinfo=UTC)


def canonical_payload(**overrides: Any) -> dict[str, Any]:
    """A payload that satisfies the contract in full, with per-test overrides.

    Every optional array is populated, so a test asserting *rejection* can point at one
    edited field and know nothing else contributed. ``practice_events`` carries exactly
    §7.6's four keys — the shape G8 exists to keep closed.
    """
    payload: dict[str, Any] = {
        "payload_version": 1,
        "observed_at": "2026-08-04T15:18:41+00:00",
        "player": {
            "username": "zezima",
            "display_name": "Zezima",
            "combat_level": 126,
            "quest_points": 300,
        },
        "skills": [
            {"skill": "magic", "level": 94, "xp": 7_195_629},
            {"skill": "construction", "level": 1, "xp": None},
        ],
        "quests": [
            {"quest_id": "desert_treasure_i", "status": "complete"},
            {"quest_id": "dragon_slayer_ii", "status": "in_progress"},
        ],
        "unlocks": [
            {"key": "ancient_magicks", "state": "unlocked"},
            {"key": "rigour", "state": "available"},
            {"key": "spellbook_ancient", "state": "unlocked"},
            {"key": "diary_varrock_hard", "state": "locked"},
            {"key": "ca_grandmaster", "state": "unknown"},
        ],
        "observed_items": [
            {"item_id": 27690, "quantity": 1, "container": "bank"},
        ],
        "container_scans": [
            {"container": "bank", "scanned_at": "2026-08-04T15:10:00+00:00"},
            {"container": "equipment", "scanned_at": "2026-08-04T15:18:00+00:00"},
        ],
        "practice_events": [
            {
                "domain": "lms",
                "started_at": "2026-08-04T15:12:00+00:00",
                "ended_at": "2026-08-04T15:18:41+00:00",
                "evidence_type": "lms_match_completed",
            }
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """An engine on an empty database with the real schema."""
    built = build_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(built)
    yield built
    built.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


@pytest.fixture
def settings() -> Settings:
    """Settings for the test application.

    ``bind_address`` is passed explicitly because §11.1 gives it no default, and
    ``TRACKER_CONFIG_FILE`` is not set here — the application under test must not depend
    on a developer's local ``config.yaml``.
    """
    return Settings(bind_address="127.0.0.1", api_token=API_TOKEN)


@pytest.fixture(scope="session")
def content() -> Content:
    """The real seed corpus.

    Loaded once for the whole session so accepted syncs exercise the shipped factual
    content alongside the real merge and price scope.
    """
    return load_content()


@pytest.fixture
def app(settings: Settings, session_factory: sessionmaker[Session], content: Content) -> FastAPI:
    """The whole application, minus the UI.

    ``mount_ui=False`` because NiceGUI registers its page routes at import time and a
    second mount inside one process is an error; these tests are about the API surface.
    """
    return create_app(settings, session_factory=session_factory, content=content, mount_ui=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """An unauthenticated client. Tests add the header when they mean to authenticate."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.fixture
def sync_events(session_factory: sessionmaker[Session]) -> Callable[[], list[SyncEvent]]:
    """Every ``SyncEvent`` row, oldest first — read in a fresh session.

    Fresh on purpose: the endpoint commits its audit row in its own transaction, and a
    session opened before the request would be free to serve its cached identity map
    instead of showing what was actually committed.
    """

    def _read() -> list[SyncEvent]:
        with session_factory() as session:
            return list(session.scalars(select(SyncEvent).order_by(SyncEvent.id)))

    return _read


@pytest.fixture
def build_payload() -> Callable[..., dict[str, Any]]:
    return canonical_payload


@pytest.fixture
def now() -> datetime:
    return NOW
