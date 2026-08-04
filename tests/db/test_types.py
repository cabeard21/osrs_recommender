"""The UTC column boundary (:class:`tracker.db.types.UtcDateTime`).

These tests exist because the bug they pin was invisible to every other suite. The engine
tests build ``PlayerState`` in memory with aware datetimes; the persistence tests never
compared a stored value against an aware ``now``. Both were green while a stored timestamp
could not be subtracted from the clock at all — the two halves simply never met, and Step 9
is where they would have.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from tracker.db.models import Base, ContainerScan, Player
from tracker.db.types import UtcDateTime
from tracker.domain.types import Container, Source

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _player(session: Session, **overrides: object) -> Player:
    fields: dict[str, object] = {
        "username": "zezima",
        "display_name": "Zezima",
        "created_at": NOW,
        "last_sync_at": NOW,
    }
    fields.update(overrides)
    player = Player(**fields)  # type: ignore[arg-type]
    session.add(player)
    session.flush()
    return player


class TestRoundTrip:
    def test_a_stored_timestamp_reads_back_aware(self, session: Session) -> None:
        player = _player(session)
        session.commit()
        session.expunge_all()

        stored = session.get(Player, player.id)
        assert stored is not None
        assert stored.last_sync_at is not None
        assert stored.last_sync_at.tzinfo is not None
        assert stored.last_sync_at == NOW

    def test_the_stored_value_can_be_subtracted_from_an_aware_now(self, session: Session) -> None:
        """The actual defect. §4.5's argument is entirely about ``now − observed_at``, and
        every one of those subtractions crosses this boundary."""
        player = _player(session, last_sync_at=NOW - timedelta(days=3))
        session.commit()
        session.expunge_all()

        stored = session.get(Player, player.id)
        assert stored is not None
        assert stored.last_sync_at is not None
        assert NOW - stored.last_sync_at == timedelta(days=3)

    def test_two_offsets_naming_one_instant_store_identically(self, session: Session) -> None:
        """``timezone=True`` on SQLite does not merely drop the tag — it absorbs the offset
        into the number, so these two would land four hours apart."""
        as_edt = NOW.astimezone(timezone(timedelta(hours=-4)))
        assert as_edt.hour != NOW.hour  # the values really are written differently

        utc_player = _player(session, username="utc", last_sync_at=NOW)
        edt_player = _player(session, username="edt", last_sync_at=as_edt)
        session.commit()
        session.expunge_all()

        stored_utc = session.get(Player, utc_player.id)
        stored_edt = session.get(Player, edt_player.id)
        assert stored_utc is not None and stored_edt is not None
        assert stored_utc.last_sync_at == stored_edt.last_sync_at

    def test_null_survives_as_null(self, session: Session) -> None:
        """``last_sync_at IS NULL`` is load-bearing on its own (A6) — it must not become
        an epoch or a zero."""
        player = _player(session, last_sync_at=None)
        session.commit()
        session.expunge_all()

        stored = session.get(Player, player.id)
        assert stored is not None
        assert stored.last_sync_at is None


class TestNaiveInputIsRejected:
    def test_writing_a_naive_datetime_raises(self, session: Session) -> None:
        """Loudly, at the point of the mistake. A silent UTC assumption would turn a
        ``datetime.now()`` into a timestamp wrong by the machine's offset, permanently."""
        with pytest.raises(StatementError) as excinfo:
            _player(session, last_sync_at=datetime(2026, 8, 4, 12, 0))
            session.flush()

        assert "naive datetime" in str(excinfo.value)

    def test_the_message_names_the_fix(self, session: Session) -> None:
        with pytest.raises(StatementError) as excinfo:
            _player(session, created_at=datetime(2026, 8, 4))
            session.flush()

        assert "datetime.now(UTC)" in str(excinfo.value)

    def test_the_rule_applies_to_every_table_not_just_player(self, session: Session) -> None:
        """``type_annotation_map`` is what makes this true without eighteen edits."""
        player = _player(session)
        with pytest.raises(StatementError):
            session.add(
                ContainerScan(
                    player_id=player.id,
                    container=Container.BANK,
                    scanned_at=datetime(2026, 8, 4, 12, 0),
                    source=Source.RUNELITE,
                )
            )
            session.flush()


class TestTheSchemaIsUnchanged:
    def test_the_emitted_ddl_is_still_datetime(self) -> None:
        """Which is why adopting this needed no migration: only the Python-side contract
        moved. The on-disk representation is the same naive UTC string it always was."""
        column_types = {
            column.name: str(column.type)
            for column in Player.__table__.columns
            if column.name in {"created_at", "last_sync_at"}
        }
        assert column_types == {"created_at": "DATETIME", "last_sync_at": "DATETIME"}

    def test_every_datetime_column_in_the_schema_uses_the_type(self) -> None:
        """The guarantee ``type_annotation_map`` buys, asserted rather than assumed — a
        Step 8 or 9 column declared with a bare ``sa.DateTime`` would fail here."""
        offenders = [
            f"{table.name}.{column.name}"
            for table in Base.metadata.tables.values()
            for column in table.columns
            if isinstance(column.type, sa.DateTime) and not isinstance(column.type, UtcDateTime)
        ]
        assert offenders == []
