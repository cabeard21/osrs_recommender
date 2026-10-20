"""Factual Account Companion dashboard routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI
from nicegui import ui
from sqlalchemy.orm import Session, sessionmaker

from tracker.accounts.service import AccountService
from tracker.api.deps import CONTENT_ATTR, SESSION_FACTORY_ATTR, SETTINGS_ATTR
from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.db.gear_prices import DatabaseGearPrices
from tracker.domain.types import AccountType, GpSensitivity
from tracker.gear.service import GearService
from tracker.quest_cape.catalog import load_catalog
from tracker.quest_cape.service import QuestCapeService
from tracker.ui import dashboard as dashboard_view
from tracker.ui import gear as gear_view
from tracker.ui import read_model
from tracker.ui import settings as settings_view
from tracker.ui import skills as skills_view
from tracker.ui import unlocks as unlocks_view
from tracker.ui.shell import empty_state, page

NO_PLAYER = (
    "No account yet. Start RuneLite with the companion plugin and open your bank; "
    "the first sync creates it."
)


def register_pages(app: FastAPI, *, clock: Callable[[], datetime] | None = None) -> None:
    now = clock or (lambda: datetime.now(UTC))

    def sessions() -> sessionmaker[Session]:
        factory: sessionmaker[Session] | None = getattr(app.state, SESSION_FACTORY_ATTR, None)
        if factory is None:
            raise RuntimeError("no session factory on app.state")
        return factory

    def content() -> Content:
        loaded: Content | None = getattr(app.state, CONTENT_ATTR, None)
        if loaded is None:
            raise RuntimeError("no Content on app.state")
        return loaded

    def settings() -> Settings:
        loaded: Settings | None = getattr(app.state, SETTINGS_ATTR, None)
        if loaded is None:
            raise RuntimeError("no Settings on app.state")
        return loaded

    quests = QuestCapeService(load_catalog(settings().content_dir / "quest_cape/catalog.json"))
    gear = GearService(content(), equipment_root=settings().content_dir / "equipment")

    @ui.page("/")
    def dashboard_page() -> None:
        with sessions()() as session:
            player_id = read_model.first_player_id(session)
        view = None
        if player_id is not None:
            snapshot = AccountService(sessions()).get_snapshot(player_id)
            status = quests.get_goal_status(snapshot, quest_limit=1)
            with sessions()() as session:
                view = read_model.dashboard_view(
                    session,
                    player_id,
                    now(),
                    quest_cape_completed=status.completed,
                    quest_cape_total=status.total,
                    quest_cape_unknown=status.unknown,
                    quest_cape_available=status.available_now,
                )
        with page("Dashboard", path="/"):
            if view is None:
                empty_state(NO_PLAYER)
            else:
                dashboard_view.render(view)

    @ui.page("/unlocks")
    def unlocks_page() -> None:
        with sessions()() as session:
            player_id = read_model.first_player_id(session)
            rows = read_model.unlock_rows(session, player_id, content()) if player_id else ()
        with page("Unlocks", path="/unlocks"):
            if player_id is None:
                empty_state(NO_PLAYER)
            else:
                unlocks_view.render(rows)

    @ui.page("/skills")
    def skills_page() -> None:
        with sessions()() as session:
            player_id = read_model.first_player_id(session)
            rows = read_model.skill_rows(session, player_id, content()) if player_id else ()
        with page("Skills", path="/skills"):
            if player_id is None:
                empty_state(NO_PLAYER)
            else:
                skills_view.render(rows)

    @ui.page("/gear")
    def gear_page() -> None:
        with sessions()() as session:
            player_id = read_model.first_player_id(session)
        with page("Gear", path="/gear"):
            if player_id is None:
                empty_state(NO_PLAYER)
            else:

                def gear_context():
                    return (
                        AccountService(sessions()).get_snapshot(player_id),
                        DatabaseGearPrices(sessions()).get_prices(),
                        now(),
                    )

                gear_view.render_optimizer(gear, gear_context)

    @ui.page("/settings")
    def settings_page() -> None:
        with sessions()() as session:
            player_id = read_model.first_player_id(session)
            view = read_model.settings_view(session, player_id, settings())
        with page("Settings", path="/settings"):

            def set_sensitivity(sensitivity: GpSensitivity) -> None:
                if player_id is not None:
                    with sessions()() as session:
                        read_model.set_gp_sensitivity(session, player_id, sensitivity)
                    ui.navigate.reload()

            def set_username(username: str) -> None:
                with sessions()() as session:
                    read_model.set_tracked_username(session, player_id, username)
                    session.commit()
                ui.navigate.reload()

            def set_account_type(account_type: AccountType | None) -> None:
                with sessions()() as session:
                    read_model.set_account_type(session, player_id, account_type)
                ui.navigate.reload()

            def set_members(members: bool | None) -> None:
                with sessions()() as session:
                    read_model.set_members(session, player_id, members)
                ui.navigate.reload()

            settings_view.render(
                view,
                on_set_sensitivity=set_sensitivity,
                on_set_username=set_username,
                on_set_account_type=set_account_type,
                on_set_members=set_members,
            )
