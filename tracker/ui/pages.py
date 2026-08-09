"""Route registration — where the four Step 10 views meet the request.

This is the only module that opens a session for the UI, and the only one that knows a
route path. The views themselves are functions over frozen rows (§15's rules live in
:mod:`tracker.ui.view_model`), which is what lets them be tested without a browser and
without a database; the wiring that makes them a website is deliberately small and lives
here.

**Everything is read inside one session, then the session closes before rendering.** A
NiceGUI page body runs inside the event loop, and an ORM row that lazily loads there fails
as a blank card rather than as an exception. Reading first and rendering second makes that
impossible rather than unlikely.

**Pages are registered against an app object, not at import time.** NiceGUI's ``@ui.page``
decorator registers globally, so a second registration in one process — which is what a
second ``create_app`` in a test session does — would collide. :func:`register_pages` takes
the app and reads its dependencies off ``app.state``, matching :mod:`tracker.api.deps`, so
the UI has exactly one source for its session factory and corpus.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI
from nicegui import ui
from sqlalchemy.orm import Session, sessionmaker

from tracker.api.deps import CONTENT_ATTR, SESSION_FACTORY_ATTR
from tracker.content.loader import Content
from tracker.ui import capabilities as capabilities_view
from tracker.ui import dashboard as dashboard_view
from tracker.ui import read_model
from tracker.ui import skills as skills_view
from tracker.ui import unlocks as unlocks_view
from tracker.ui.shell import empty_state, page

#: Shown by every view when no player row exists. §15's views all answer questions about an
#: account, and before the first sync there is no account — which is a state to explain, not
#: an empty list to render.
NO_PLAYER = (
    "No account yet. Start RuneLite with the companion plugin and open your bank; "
    "the first sync creates it."
)


def register_pages(app: FastAPI, *, clock: Callable[[], datetime] | None = None) -> None:
    """Register the Step 10 views on ``app``.

    ``clock`` is injectable because the dashboard's staleness copy is a function of now
    (§6.5), and "last saw your bank 3 weeks ago" is not assertable against a moving clock.
    It defaults to the real one, so production wiring passes nothing.
    """
    now = clock or (lambda: datetime.now(UTC))

    def session_factory() -> sessionmaker[Session]:
        factory: sessionmaker[Session] | None = getattr(app.state, SESSION_FACTORY_ATTR, None)
        if factory is None:  # pragma: no cover — a wiring bug, not a request-time condition
            raise RuntimeError("no session factory on app.state; build with tracker.app.create_app")
        return factory

    def content() -> Content:
        loaded: Content | None = getattr(app.state, CONTENT_ATTR, None)
        if loaded is None:  # pragma: no cover — see above
            raise RuntimeError("no Content on app.state; build with tracker.app.create_app")
        return loaded

    @ui.page("/")
    def dashboard_page() -> None:
        with page("Dashboard", path="/"):
            with session_factory()() as session:
                player_id = read_model.first_player_id(session)
                view = (
                    read_model.dashboard_view(session, player_id, content(), now())
                    if player_id is not None
                    else None
                )
            if view is None:
                empty_state(NO_PLAYER)
                return
            dashboard_view.render(view)

    @ui.page("/capabilities")
    def capabilities_page() -> None:
        with page("Capabilities", path="/capabilities"):
            with session_factory()() as session:
                player_id = read_model.first_player_id(session)
                rows = (
                    read_model.capability_rows(session, player_id, content())
                    if player_id is not None
                    else ()
                )
            if player_id is None:
                empty_state(NO_PLAYER)
                return
            capabilities_view.render(rows)

    @ui.page("/unlocks")
    def unlocks_page() -> None:
        with page("Unlocks", path="/unlocks"):
            with session_factory()() as session:
                player_id = read_model.first_player_id(session)
                unlock_rows = (
                    read_model.unlock_rows(session, player_id, content())
                    if player_id is not None
                    else ()
                )
            if player_id is None:
                empty_state(NO_PLAYER)
                return
            unlocks_view.render(unlock_rows)

    @ui.page("/skills")
    def skills_page() -> None:
        with page("Skills", path="/skills"):
            with session_factory()() as session:
                player_id = read_model.first_player_id(session)
                skill_rows = (
                    read_model.skill_rows(session, player_id, content())
                    if player_id is not None
                    else ()
                )
            if player_id is None:
                empty_state(NO_PLAYER)
                return
            skills_view.render(skill_rows)
