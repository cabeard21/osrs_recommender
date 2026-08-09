"""Fixtures for the merge tests (§7.4).

A real SQLite file under ``tmp_path`` with the schema built from the models, matching
``tests/db/conftest.py``. The merge layer's whole job is comparing what a payload claims
against what is stored, so a test double for the store would assert nothing.

Payloads are built by a callable fixture rather than an importable function, for the same
reason as everywhere else in this tree: sibling ``conftest`` modules share one flat
namespace and ``from conftest import ...`` resolves unpredictably.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from tracker.db.models import Base
from tracker.db.session import build_engine, build_session_factory

#: A fixed clock, aware UTC — §4.5 comparisons need an offset.
NOW = datetime(2026, 8, 4, 15, 18, 41, tzinfo=UTC)

#: An hour before ``NOW``. The mid-session RuneLite observation in the G4 tests.
EARLIER = NOW - timedelta(hours=1)

VOIDWAKER_ITEM_ID = 27_690


def iso(moment: datetime) -> str:
    """A contract-shaped timestamp. Always aware — the schema's pattern requires it."""
    return moment.isoformat()


def minimal_payload(observed_at: datetime = NOW, **overrides: Any) -> dict[str, Any]:
    """A payload carrying identity and nothing else, plus whatever a test names.

    Deliberately minimal — the inverse of ``tests/api/conftest.py``'s canonical payload.
    These tests assert what one merge rule does to one table, and an unrelated populated
    array is a second thing that could explain a row count.
    """
    payload: dict[str, Any] = {
        "payload_version": 1,
        "observed_at": iso(observed_at),
        "player": {"username": "zezima", "display_name": "Zezima"},
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    """A session on an empty database with the real schema."""
    engine = build_engine(f"sqlite:///{tmp_path / 'merge.db'}")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def build_payload() -> Callable[..., dict[str, Any]]:
    return minimal_payload


@pytest.fixture
def to_iso() -> Callable[[datetime], str]:
    return iso


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def earlier() -> datetime:
    return EARLIER
