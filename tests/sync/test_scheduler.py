"""The periodic refresh driver (§5, §7.5).

``SingleFlightRefresher`` shipped in Step 9 and was **never instantiated outside a test** —
so the "background sync worker" §5 names did not exist in the running app, and neither the
price TTL refresh nor the WOM poll ever fired on a schedule. These tests pin the two
properties that absence hid: every tracked account gets refreshed, and one failure does not
stop the schedule.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tracker.db.models import Base, Player
from tracker.db.session import build_engine, build_session_factory
from tracker.sync.scheduler import RefreshScheduler, tracked_player_ids
from tracker.sync.worker import RefreshOutcome

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'sched.db'}")
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


def _add_players(factory: sessionmaker[Session], *usernames: str) -> list[int]:
    with factory() as session:
        rows = [Player(username=name, display_name=name, created_at=_NOW) for name in usernames]
        session.add_all(rows)
        session.commit()
        return [row.id for row in rows]


class _RecordingRefresher:
    """Stands in for ``SingleFlightRefresher``: records calls, optionally explodes."""

    def __init__(self, *, fail_on: set[int] | None = None) -> None:
        self.calls: list[int] = []
        self._fail_on = fail_on or set()

    def refresh(self, player_id: int, *, manual: bool = False) -> RefreshOutcome:
        self.calls.append(player_id)
        if player_id in self._fail_on:
            raise RuntimeError("WOM exploded")
        return RefreshOutcome(ran=True)


class TestItRefreshesEveryTrackedAccount:
    def test_tracked_player_ids_returns_all_of_them_in_order(
        self, sessions: sessionmaker[Session]
    ) -> None:
        expected = _add_players(sessions, "zezima", "durial321")
        with sessions() as session:
            assert list(tracked_player_ids(session)) == expected

    def test_a_tick_refreshes_each_player_once(self, sessions: sessionmaker[Session]) -> None:
        """§6.1 supports multiple characters; §17 keeps them out of the *UI* only. A second
        account whose prices silently never refreshed would be indistinguishable from one
        whose prices were current."""
        expected = _add_players(sessions, "zezima", "durial321")
        refresher = _RecordingRefresher()
        scheduler = RefreshScheduler(refresher, sessions)  # type: ignore[arg-type]

        scheduler._refresh_all()

        assert refresher.calls == expected

    def test_no_players_is_a_no_op_not_an_error(self, sessions: sessionmaker[Session]) -> None:
        refresher = _RecordingRefresher()
        scheduler = RefreshScheduler(refresher, sessions)  # type: ignore[arg-type]

        scheduler._refresh_all()

        assert refresher.calls == []


class TestOneFailureDoesNotStopTheSchedule:
    @pytest.mark.anyio
    async def test_a_raising_refresh_is_logged_and_the_loop_continues(
        self, sessions: sessionmaker[Session]
    ) -> None:
        """An app that stopped refreshing because one WOM call threw would look identical,
        from the outside, to one that was simply idle — which is why the loop swallows and
        the *refresh* does not."""
        ids = _add_players(sessions, "zezima")
        refresher = _RecordingRefresher(fail_on={ids[0]})
        scheduler = RefreshScheduler(
            refresher,  # type: ignore[arg-type]
            sessions,
            interval=timedelta(milliseconds=10),
        )

        scheduler.start()
        await asyncio.sleep(0.08)
        await scheduler.stop()

        assert len(refresher.calls) >= 2, "the loop stopped after the first failure"

    @pytest.fixture
    def anyio_backend(self) -> str:
        return "asyncio"
