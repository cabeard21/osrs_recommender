"""The Wise Old Man importer (§7.2, §7.4) — precedence, honesty, and failure.

These tests exist because the gap they cover shipped once already: ``WiseOldManClient`` was
implemented and tested in Step 7 and then had **no production caller** through Steps 9–13.
Step 9's task list named a *"periodic WOM poll"*; its exit criteria did not, so nothing was
watching. The assertions here are deliberately about the wiring, not about the client — the
client's own parsing is covered in ``tests/integrations/wise_old_man/``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import WiseOldManSettings
from tracker.db.models import Base, Player
from tracker.db.repository import append_skill_snapshot, current_skill_snapshots
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Source
from tracker.integrations.wise_old_man.client import WiseOldManClient
from tracker.sync.wom_import import import_wom_skills

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
#: The timestamp inside the mocked WOM payload — six hours *before* ``_NOW``. Kept distinct
#: from the fetch clock on purpose: §4.5 says the observation time is the snapshot's, and a
#: test whose two clocks agreed could not tell the two apart.
_SNAPSHOT_AT = datetime(2026, 8, 11, 6, 12, 3, tzinfo=UTC)


def _wom_client(handler: httpx.MockTransport) -> WiseOldManClient:
    return WiseOldManClient(
        WiseOldManSettings(), transport=handler, sleep=lambda _: None, clock=lambda: _NOW
    )


def _snapshot_response(**skills: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "latestSnapshot": {
                    "createdAt": _SNAPSHOT_AT.isoformat().replace("+00:00", "Z"),
                    "data": {
                        "skills": {
                            name: {
                                "metric": name,
                                "experience": xp,
                                "rank": 1,
                                "level": 90,
                            }
                            for name, xp in skills.items()
                        },
                        "activities": {},
                    },
                }
            },
        )

    return httpx.MockTransport(handler)


def _unreachable() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("wom is down", request=request)

    return httpx.MockTransport(handler)


@pytest.fixture
def pipeline_sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'wom.db'}")
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


@pytest.fixture
def player(pipeline_sessions: sessionmaker[Session]) -> int:
    with pipeline_sessions() as session:
        row = Player(username="zezima", display_name="Zezima", created_at=_NOW)
        session.add(row)
        session.commit()
        return row.id


class TestTheImportRuns:
    def test_wom_skills_land_in_the_database(
        self, pipeline_sessions: sessionmaker[Session], player: int
    ) -> None:
        with pipeline_sessions() as session:
            with _wom_client(_snapshot_response(magic=7_195_629)) as client:
                outcome = import_wom_skills(session, player, client=client)
            session.commit()

            assert outcome.ran is True
            assert outcome.username == "zezima"
            assert outcome.skills_written == 1
            stored = {row.skill: row for row in current_skill_snapshots(session, player)}
            assert stored["magic"].xp == 7_195_629
            assert stored["magic"].source is Source.WISE_OLD_MAN

    def test_the_observation_time_is_woms_snapshot_not_the_fetch(
        self, pipeline_sessions: sessionmaker[Session], player: int
    ) -> None:
        """§4.5 / D10 one source over: fetching now does not make a six-hour-old read fresh."""
        with pipeline_sessions() as session:
            with _wom_client(_snapshot_response(magic=7_195_629)) as client:
                import_wom_skills(session, player, client=client)
            session.commit()

            stored = {row.skill: row for row in current_skill_snapshots(session, player)}
            assert stored["magic"].observed_at == _SNAPSHOT_AT
            assert stored["magic"].observed_at != _NOW


class TestG4PrecedenceHoldsForTheWomWriter:
    """§7.4 rule 3 — the rule WOM is the motivating example for."""

    def test_stale_wom_never_regresses_fresher_runelite_xp(
        self, pipeline_sessions: sessionmaker[Session], player: int
    ) -> None:
        with pipeline_sessions() as session:
            append_skill_snapshot(
                session,
                player,
                skill="magic",
                level=94,
                xp=8_000_000,
                source=Source.RUNELITE,
                observed_at=_SNAPSHOT_AT + timedelta(hours=2),
            )
            session.commit()

            with _wom_client(_snapshot_response(magic=7_195_629)) as client:
                outcome = import_wom_skills(session, player, client=client)
            session.commit()

            assert outcome.skills_ignored == 1
            assert outcome.skills_written == 0
            stored = {row.skill: row for row in current_skill_snapshots(session, player)}
            assert stored["magic"].xp == 8_000_000, "WOM rolled back a fresher RuneLite read"
            assert stored["magic"].source is Source.RUNELITE


class TestItDoesNotClaimWhatWomCannotKnow:
    def test_last_sync_at_stays_null_so_combat_level_remains_unknown(
        self, pipeline_sessions: sessionmaker[Session], player: int
    ) -> None:
        """A6 — ``last_sync_at`` means *the account's own scalars were observed*.

        WOM supplies neither ``combat_level`` nor ``quest_points``. Advancing the column
        would assert an observation that never happened and flip both leaves out of
        ``unknown`` on no evidence, which is the D8 defect §9.2 is built to prevent.
        """
        with pipeline_sessions() as session:
            with _wom_client(_snapshot_response(magic=7_195_629)) as client:
                import_wom_skills(session, player, client=client)
            session.commit()

            row = session.get(Player, player)
            assert row is not None
            assert row.last_sync_at is None
            assert row.combat_level is None


class TestFailureIsNotFatal:
    def test_an_unreachable_wom_reports_and_does_not_raise(
        self, pipeline_sessions: sessionmaker[Session], player: int
    ) -> None:
        """§7.5's posture for prices, applied to WOM: a scheduled refresh that dies because a
        third party is down must not take the recommendation run with it."""
        with pipeline_sessions() as session:
            with _wom_client(_unreachable()) as client:
                outcome = import_wom_skills(session, player, client=client)

            assert outcome.ran is False
            assert outcome.skipped_reason is not None
            assert "unreachable" in outcome.skipped_reason
            assert current_skill_snapshots(session, player) == []

    def test_an_unknown_player_is_skipped_without_a_fetch(
        self, pipeline_sessions: sessionmaker[Session]
    ) -> None:
        fetched: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not run
            fetched.append(str(request.url))
            return httpx.Response(200, json={})

        with pipeline_sessions() as session:
            with _wom_client(httpx.MockTransport(handler)) as client:
                outcome = import_wom_skills(session, 9999, client=client)

            assert outcome.ran is False
            assert fetched == [], "fetched WOM data for a player that does not exist"
