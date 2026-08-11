"""Naming the tracked character from the settings page (§7.2's bootstrap, §6.11).

Until this existed, ``Player.username`` had exactly one writer — a RuneLite sync payload — so
Wise Old Man could never run on an install without the plugin, even though covering for the
plugin's absence is the only reason §7.2 puts WOM in the design at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import Settings
from tracker.db.models import Base, Player
from tracker.db.session import build_engine, build_session_factory
from tracker.ui.read_model import set_tracked_username, settings_view

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'settings.db'}")
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


def _settings() -> Settings:
    return Settings(bind_address="127.0.0.1", api_token="t0ken")


class TestTheBootstrap:
    def test_naming_a_character_with_no_player_creates_one(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions() as session:
            player_id = set_tracked_username(session, None, "zezima")
            session.commit()

            row = session.get(Player, player_id)
            assert row is not None
            assert row.username == "zezima"

    def test_a_created_row_leaves_last_sync_at_null(self, sessions: sessionmaker[Session]) -> None:
        """A6 — naming an account observes none of its scalars, so ``combat_level`` and
        ``quest_points`` must keep resolving ``unknown`` until a real sync says otherwise."""
        with sessions() as session:
            player_id = set_tracked_username(session, None, "zezima")
            session.commit()

            row = session.get(Player, player_id)
            assert row is not None
            assert row.last_sync_at is None
            assert row.combat_level is None
            assert row.quest_points is None

    def test_renaming_an_existing_player_does_not_create_a_second(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions() as session:
            first = set_tracked_username(session, None, "zezima")
            session.commit()
            second = set_tracked_username(session, first, "durial321")
            session.commit()

            assert second == first
            assert session.query(Player).count() == 1
            row = session.get(Player, first)
            assert row is not None
            assert row.username == "durial321"

    def test_naming_an_already_known_username_reuses_that_row(
        self, sessions: sessionmaker[Session]
    ) -> None:
        """§6.11 makes ``username`` the identity. Creating a second row for the same name
        would split one account's history across two ids with no way to merge them back."""
        with sessions() as session:
            session.add(Player(username="zezima", display_name="Zezima", created_at=_NOW))
            session.commit()

            resolved = set_tracked_username(session, None, "zezima")
            session.commit()

            assert session.query(Player).count() == 1
            row = session.get(Player, resolved)
            assert row is not None
            assert row.username == "zezima"

    def test_whitespace_is_stripped_and_blank_is_refused(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions() as session:
            player_id = set_tracked_username(session, None, "  zezima  ")
            session.commit()
            row = session.get(Player, player_id)
            assert row is not None
            assert row.username == "zezima"

            with pytest.raises(ValueError, match="must not be blank"):
                set_tracked_username(session, player_id, "   ")


class TestTheSettingsViewRendersWithoutAPlayer:
    def test_no_player_yields_a_view_rather_than_an_error(
        self, sessions: sessionmaker[Session]
    ) -> None:
        """The settings page is the one page that must render before a player exists — it is
        where the player gets created."""
        with sessions() as session:
            view = settings_view(session, None, _settings())

            assert view.tracked_username is None
            assert view.api_token_present is True

    def test_a_named_player_appears_in_the_view(self, sessions: sessionmaker[Session]) -> None:
        with sessions() as session:
            player_id = set_tracked_username(session, None, "zezima")
            session.commit()

            view = settings_view(session, player_id, _settings())

            assert view.tracked_username == "zezima"
