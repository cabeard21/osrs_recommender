"""Engine and session factory (§6.13, §14.1).

Two SQLite pragmas matter enough to be non-optional here rather than left to whoever opens
a connection later:

* ``foreign_keys = ON`` — SQLite ships with foreign key *enforcement* off by default for
  backward compatibility. Without this, every ``ondelete=`` clause in
  ``tracker.db.models`` (the ``SyncEvent.player_id`` ``SET NULL`` on player deletion, the
  ``CASCADE``s elsewhere) is silently a no-op and the schema's stated referential rules
  are decorative.
* ``journal_mode = WAL`` — the app is a single long-lived ``uvicorn`` process (§5) with a
  background sync worker and a UI both touching the same database; WAL lets readers and a
  writer proceed concurrently instead of serializing on SQLite's default rollback journal.

Both are set via a ``connect`` event listener rather than a raw ``PRAGMA`` string executed
once at startup, because pragmas are per-*connection* state in SQLite — a pool that opens a
second connection later would silently run without them otherwise.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import load_settings


def build_engine(database_url: str | None = None) -> Engine:
    """Build an engine for ``database_url``, defaulting to ``Settings.database_url``.

    Kept a plain function rather than a module-level singleton so tests can point at an
    isolated file (or ``sqlite:///:memory:``) without reaching for global state or
    monkeypatching a cached engine.
    """
    url = database_url if database_url is not None else load_settings().database_url
    engine = create_engine(url)

    if engine.dialect.name == "sqlite":
        # Guarded on dialect name rather than assumed: §14.1 names SQLite as the v1
        # choice, but nothing else in this module should hard-fail if that ever changes.
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL is silently ignored (falls back to the default journal) for
            # ``:memory:`` databases — harmless to always issue it.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """A ``sessionmaker`` bound to ``engine``. ``expire_on_commit=False`` because the
    projection layer (Step 3b) reads attributes off ORM objects after the transaction
    that loaded them has committed, and the default expiry would force a second query
    for every attribute access.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on a clean exit, roll back and re-raise on any exception.

    A thin convenience wrapper — callers that need finer-grained transaction control
    (e.g. batching several writes with one commit) can still use ``session_factory()``
    directly.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
