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

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from fastapi import FastAPI
from nicegui import ui
from sqlalchemy.orm import Session, sessionmaker

from tracker.api.deps import CONTENT_ATTR, SESSION_FACTORY_ATTR, SETTINGS_ATTR
from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.domain.types import AccountType, GpSensitivity
from tracker.ui import capabilities as capabilities_view
from tracker.ui import dashboard as dashboard_view
from tracker.ui import history as history_view
from tracker.ui import practice as practice_view
from tracker.ui import read_model
from tracker.ui import recommendations as recommendations_view
from tracker.ui import roadmaps as roadmaps_view
from tracker.ui import settings as settings_view
from tracker.ui import skills as skills_view
from tracker.ui import unlocks as unlocks_view
from tracker.ui.shell import empty_state, page
from tracker.ui.view_model import (
    LeafRow,
    PracticeGroupRow,
    RoadmapSelectorModel,
    roadmap_selector_model,
)

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

    def settings() -> Settings:
        loaded: Settings | None = getattr(app.state, SETTINGS_ATTR, None)
        if loaded is None:  # pragma: no cover — see above
            raise RuntimeError("no Settings on app.state; build with tracker.app.create_app")
        return loaded

    def selector(session: Session, player_id: int | None) -> RoadmapSelectorModel | None:
        """The header roadmap selector's model, read on the page's own session.

        Built here rather than in :mod:`tracker.ui.shell` because binding the write needs a
        session factory, and this is the only module that has one. The write takes its own
        session, as every other handler on this page does — the read session is closed
        before anything renders, so a handler firing later cannot use it.

        Every page passes this, which is why it is a helper rather than nine copies: a page
        that forgot it would silently lose the selector, and nothing but a browser test
        would notice.
        """
        if player_id is None:
            return None
        options = read_model.roadmap_options(session, player_id, content())

        def choose(roadmap_id: str) -> None:
            with session_factory()() as write_session:
                read_model.select_primary_roadmap(write_session, player_id, roadmap_id)
            ui.navigate.reload()

        return roadmap_selector_model(options, choose)

    @ui.page("/")
    def dashboard_page() -> None:
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            view = (
                read_model.dashboard_view(session, player_id, content(), now())
                if player_id is not None
                else None
            )
        with page("Dashboard", path="/", roadmap=roadmap):
            if view is None:
                empty_state(NO_PLAYER)
                return
            dashboard_view.render(view)

    @ui.page("/capabilities")
    def capabilities_page() -> None:
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            rows = (
                read_model.capability_rows(session, player_id, content())
                if player_id is not None
                else ()
            )
        with page("Capabilities", path="/capabilities", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return

            def attest(leaf: LeafRow, achieved: bool) -> None:
                with session_factory()() as write_session:
                    read_model.attest_milestone(
                        write_session,
                        player_id,
                        leaf.key,
                        achieved=achieved,
                        content=content(),
                        now=now(),
                    )
                ui.notify(f"Recorded: {leaf.description or leaf.key}")
                ui.navigate.reload()

            capabilities_view.render(rows, on_attest=attest)

    @ui.page("/unlocks")
    def unlocks_page() -> None:
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            unlock_rows = (
                read_model.unlock_rows(session, player_id, content())
                if player_id is not None
                else ()
            )
        with page("Unlocks", path="/unlocks", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return
            unlocks_view.render(unlock_rows)

    @ui.page("/skills")
    def skills_page() -> None:
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            skill_rows = (
                read_model.skill_rows(session, player_id, content())
                if player_id is not None
                else ()
            )
        with page("Skills", path="/skills", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return
            skills_view.render(skill_rows)

    @ui.page("/recommendations")
    def recommendations_page() -> None:
        # The early return lives below ``with page(...)``, not inside the session block. A
        # ``return`` taken before the frame opens renders an empty document, so the one
        # case that most needs an explanation — no account yet — would be the one case that
        # gets a blank screen.
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            rows = (
                read_model.recommendation_rows(session, player_id, content(), now())
                if player_id is not None
                else ()
            )
            blocked = (
                read_model.blocked_recommendation_rows(session, player_id, content())
                if player_id is not None
                else ()
            )
        with page("Recommendations", path="/recommendations", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return
            recommendations_view.render(rows, blocked)

    @ui.page("/practice")
    def practice_page() -> None:
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            groups = (
                read_model.practice_freshness_rows(session, player_id, content(), now())
                if player_id is not None
                else ()
            )
        with page("Practice", path="/practice", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return

            def mark_complete(group: PracticeGroupRow, keys: Sequence[str]) -> None:
                with session_factory()() as write_session:
                    read_model.refresh_milestones(write_session, player_id, keys, now=now())
                ui.notify(f"Marked {group.name} complete")
                ui.navigate.reload()

            def review(group: PracticeGroupRow, keys: Sequence[str]) -> None:
                with session_factory()() as write_session:
                    read_model.refresh_milestones(write_session, player_id, keys, now=now())
                ui.notify(f"Refreshed {len(keys)} skill(s)")
                ui.navigate.reload()

            practice_view.render(groups, on_mark_complete=mark_complete, on_review=review)

    @ui.page("/roadmaps")
    def roadmaps_page() -> None:
        # This page keeps its radio group as well as gaining the header selector. Both
        # write through ``select_primary_roadmap`` and both reload, so the two controls
        # cannot disagree; what the page adds is the secondaries and the raw weights, which
        # §4.3 deliberately keeps out of the one-choice surface.
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            options = (
                read_model.roadmap_options(session, player_id, content())
                if player_id is not None
                else ()
            )
        with page("Roadmaps", path="/roadmaps", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return

            def select_primary(roadmap_id: str) -> None:
                with session_factory()() as write_session:
                    read_model.select_primary_roadmap(write_session, player_id, roadmap_id)
                ui.navigate.reload()

            def toggle_secondary(roadmap_id: str, enabled: bool) -> None:
                with session_factory()() as write_session:
                    read_model.set_secondary_roadmap(
                        write_session, player_id, roadmap_id, enabled=enabled
                    )
                ui.navigate.reload()

            def set_weight(roadmap_id: str, weight: float) -> None:
                with session_factory()() as write_session:
                    read_model.set_roadmap_weight(write_session, player_id, roadmap_id, weight)

            roadmaps_view.render(
                options,
                on_select_primary=select_primary,
                on_toggle_secondary=toggle_secondary,
                on_set_weight=set_weight,
            )

    @ui.page("/settings")
    def settings_page() -> None:
        # Deliberately **not** gated on ``NO_PLAYER`` like every other page. Naming the
        # character is what a fresh install does *before* it has a player row, so the one
        # page that can create one must render without it — otherwise a user with no
        # RuneLite plugin has no way in at all, which is the §7.2 bootstrap gap. It is also
        # the page that makes ``roadmap=None`` necessary rather than defensive: before the
        # first sync there is no account, so there is no roadmap to choose for.
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            view = read_model.settings_view(session, player_id, settings())

        with page("Settings", path="/settings", roadmap=roadmap):

            def set_sensitivity(sensitivity: GpSensitivity) -> None:
                if player_id is None:
                    return
                with session_factory()() as write_session:
                    read_model.set_gp_sensitivity(write_session, player_id, sensitivity)
                ui.navigate.reload()

            def set_username(username: str) -> None:
                if not username.strip():
                    return
                with session_factory()() as write_session:
                    read_model.set_tracked_username(write_session, player_id, username)
                    write_session.commit()
                ui.navigate.reload()

            def set_account_type(account_type: AccountType | None) -> None:
                with session_factory()() as write_session:
                    read_model.set_account_type(write_session, player_id, account_type)
                ui.navigate.reload()

            def set_members(members: bool | None) -> None:
                with session_factory()() as write_session:
                    read_model.set_members(write_session, player_id, members)
                ui.navigate.reload()

            settings_view.render(
                view,
                on_set_sensitivity=set_sensitivity,
                on_set_username=set_username,
                on_set_account_type=set_account_type,
                on_set_members=set_members,
            )

    @ui.page("/history")
    def history_page() -> None:
        # Early return below the frame, for the reason ``/recommendations`` states.
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            snapshots = (
                read_model.history_snapshots(session, player_id, content())
                if player_id is not None
                else ()
            )
            xp = read_model.xp_series(session, player_id) if player_id is not None else {}
        with page("History", path="/history", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return
            history_view.render(snapshots, xp)
