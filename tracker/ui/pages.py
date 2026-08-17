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
from nicegui import run, ui
from sqlalchemy.orm import Session, sessionmaker

from tracker.api.deps import (
    ADVISOR_SERVICE_ATTR,
    CONTENT_ATTR,
    GUIDANCE_SERVICE_ATTR,
    SESSION_FACTORY_ATTR,
    SETTINGS_ATTR,
)
from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.domain.types import AccountType, GpSensitivity
from tracker.integrations.llm import LlmRefused, LlmUnavailable
from tracker.sync.advisor import AdvisorNotFound, AdvisorThrottled
from tracker.sync.guidance import GuidanceNotFound, GuidanceThrottled
from tracker.ui import advisor as advisor_view
from tracker.ui import capabilities as capabilities_view
from tracker.ui import dashboard as dashboard_view
from tracker.ui import gear as gear_view
from tracker.ui import guidance as guidance_view
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
    ADVISOR_DISABLED,
    ADVISOR_REFUSED,
    ADVISOR_UNAVAILABLE,
    GUIDANCE_DISABLED,
    GUIDANCE_UNAVAILABLE,
    NEW_CONVERSATION_ID,
    LeafRow,
    PracticeGroupRow,
    RoadmapSelectorModel,
    roadmap_selector_model,
)

#: Shown by every view when no player row exists. §15's views all answer questions about an
#: account, and before the first sync there is no account — which is a state to explain, not
#: an empty list to render.
#: Shown when the provider answered and declined. Its own message rather than the
#: unavailable one: a retry cannot fix a refusal, and saying "try again" would be false.
GUIDANCE_REFUSED = (
    "The guidance provider declined to answer this one. The recommendation and its "
    "estimate are unaffected."
)

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

    @ui.page("/gear")
    def gear_page() -> None:
        """§23.5. Read-only: this page changes no fact and feeds no ranking."""
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            view = read_model.gear_view(session, player_id, content())
        with page("Gear", path="/gear", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return
            gear_view.render(view)

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
    async def recommendations_page() -> None:
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
        # "Next up" rather than "Recommendations", and the same word in the nav: the label
        # has to survive a 78 px slot in the phone bar, and the plainer name is the one a
        # reader would use for it anyway. One name through the whole flow, so the tab you
        # tapped and the heading you land on agree.
        with page("Next up", path="/recommendations", roadmap=roadmap):
            if player_id is None:
                empty_state(NO_PLAYER)
                return

            async def show_guidance(candidate_id: str, *, player_id: int = player_id) -> None:
                """§21's affordance: ask how, in a dialog, without leaving the list.

                Opens its own session by way of the service, exactly as ``attest`` and
                ``choose`` do — the page's read-close-render pass is finished by the time
                anything here runs, and holding that session open across a network call
                would be a transaction held open for the length of a model's answer.
                """
                service = getattr(app.state, GUIDANCE_SERVICE_ATTR, None)
                with ui.dialog() as dialog, ui.card().classes("max-w-xl"):
                    if service is None or not service.enabled:
                        guidance_view.render_error(GUIDANCE_DISABLED)
                        dialog.open()
                        return
                    spinner = ui.spinner()
                    dialog.open()
                    try:
                        # `run.io_bound` keeps the blocking provider call off the event loop
                        # that is also serving /api/sync in this same process (§5). Without
                        # it, one click freezes every other tab and the RuneLite plugin.
                        stored = await run.io_bound(service.guidance_for, player_id, candidate_id)
                    except GuidanceThrottled as declined:
                        spinner.delete()
                        guidance_view.render_error(str(declined))
                        return
                    except LlmRefused:
                        spinner.delete()
                        guidance_view.render_error(GUIDANCE_REFUSED)
                        return
                    except LlmUnavailable:
                        spinner.delete()
                        guidance_view.render_error(GUIDANCE_UNAVAILABLE)
                        return
                    except GuidanceNotFound as missing:
                        spinner.delete()
                        guidance_view.render_error(str(missing))
                        return
                    spinner.delete()
                    if stored is None:
                        # NiceGUI hands back `None` when the browser disconnected while the
                        # call was in flight. The note is already stored either way, so the
                        # next click is a cache hit — there is nothing to draw and nothing
                        # to apologise for.
                        return
                    guidance_view.render_dialog(read_model.guidance_view_of(stored, candidate_id))

            recommendations_view.render(rows, blocked, on_guidance=show_guidance)

    @ui.page("/advisor")
    async def advisor_page(conversation: int | None = None) -> None:
        """§22's surface: a thread, and a box to ask into.

        The conversation id lives in the query string rather than in tab storage so a reload
        returns to the same thread — a conversation that vanishes on refresh is worse than no
        conversation, because the user has already spent money on it.
        """
        with session_factory()() as session:
            player_id = read_model.first_player_id(session)
            roadmap = selector(session, player_id)
            view = (
                read_model.advisor_thread(session, player_id, conversation)
                if player_id is not None
                else None
            )

        with page("Advisor", path="/advisor", roadmap=roadmap):
            if player_id is None or view is None:
                empty_state(NO_PLAYER)
                return

            service = getattr(app.state, ADVISOR_SERVICE_ATTR, None)
            if service is None or not service.enabled:
                advisor_view.render_error(ADVISOR_DISABLED)
                return

            advisor_view.inject_styles()

            current_id = view.conversation_id

            def open_conversation(identifier: int) -> None:
                ui.navigate.to(f"/advisor?conversation={identifier}")

            def start_conversation() -> None:
                ui.navigate.to(f"/advisor?conversation={NEW_CONVERSATION_ID}")

            def remove_conversation(identifier: int) -> None:
                """Delete a thread, then land wherever the reader still has a right to be.

                Deleting the thread you are *reading* has to move you; deleting another one
                from the list must not. Both are covered by asking for the current thread
                again — unless that is the one that just went, in which case the bare path
                falls back to the most recent survivor, which is the honest answer to "where
                now".
                """
                with session_factory()() as write_session:
                    read_model.delete_advisor_conversation(write_session, player_id, identifier)
                if identifier == current_id:
                    ui.navigate.to("/advisor")
                    return
                ui.navigate.to(f"/advisor?conversation={current_id or NEW_CONVERSATION_ID}")

            advisor_view.render_conversation_list(
                view,
                on_select=open_conversation,
                on_new=start_conversation,
                on_delete=remove_conversation,
            )

            def use_prompt(text: str) -> None:
                """Put a suggested question in the box, and leave the sending to the reader.

                Deliberately not "ask it immediately". These prompts are starting points, and
                most are worth a word of editing before they are spent — every question here
                costs a call to a paid provider, so a click that silently committed one would
                be the wrong default for a control whose whole job is to be easy to press.
                """
                box.value = text
                box.run_method("focus")

            transcript = ui.element("div").classes("advisor-thread")
            transcript.props("data-testid=advisor-thread")
            with transcript:
                advisor_view.render_thread(view, on_prompt=use_prompt)

            # Outside the transcript, and empty until something happens. See
            # `advisor_view.render_live_region` for why it is one persistent element rather
            # than `aria-live` on the conversation itself.
            status = advisor_view.render_live_region()

            async def ask(*, player_id: int = player_id) -> None:
                question = str(box.value or "").strip()
                if not question:
                    return
                box.value = ""
                box.disable()
                # Two elements, not one wrapper around both: the spinner is always removed and
                # the question survives, unless the turn failed — in which case nothing was
                # asked and both go. Wrapping them together is what previously deleted the
                # question along with the spinner on every turn but the first.
                with transcript:
                    asked = advisor_view.render_question(question)
                    pending = advisor_view.render_pending()
                advisor_view.announce(status, advisor_view.PENDING_ANNOUNCEMENT)
                advisor_view.scroll_to_latest()

                def failed(message: str) -> None:
                    """Take the unasked question back, and say why, in the conversation.

                    The echoed question goes with the spinner because it was optimistic: the
                    turn was never stored, so leaving it on screen would promise a reload that
                    will not show it. It goes back into the box instead, which makes *Ask* a
                    retry rather than a request to retype a paragraph — the composer was
                    cleared on send and a throttle is the failure most likely to be worth
                    trying again immediately.
                    """
                    asked.delete()
                    pending.delete()
                    box.value = question
                    with transcript:
                        advisor_view.render_error(message)
                    advisor_view.announce(status, message)
                    advisor_view.scroll_to_latest()

                try:
                    # `run.io_bound` keeps the blocking turn off the event loop that is also
                    # serving /api/sync in this process (§5). A tool-using turn is several
                    # round trips; without this, one question freezes the RuneLite plugin.
                    reply = await run.io_bound(
                        service.ask,
                        player_id,
                        question,
                        conversation_id=current_id or None,
                    )
                except (AdvisorThrottled, AdvisorNotFound) as declined:
                    failed(str(declined))
                    return
                except LlmRefused:
                    failed(ADVISOR_REFUSED)
                    return
                except LlmUnavailable:
                    failed(ADVISOR_UNAVAILABLE)
                    return
                finally:
                    box.enable()

                pending.delete()
                if reply is None:
                    # NiceGUI hands back `None` when the browser disconnected mid-call. The
                    # turn is already stored, so the next page load shows it; there is nothing
                    # to draw and nothing to apologise for.
                    return
                with transcript:
                    advisor_view.render_message(read_model.advisor_reply_row(reply))
                advisor_view.announce(status, advisor_view.ANSWER_ANNOUNCEMENT)
                if not current_id:
                    ui.navigate.to(f"/advisor?conversation={reply.conversation_id}")
                    return
                # Only when the page is staying put. A navigate replaces the document, and
                # scrolling the one it is about to discard is at best wasted work.
                advisor_view.scroll_to_latest()

            # A plain div rather than `ui.row()`, because this one is `position: sticky` and a
            # Quasar row brings margins that fight a sticky offset. Declared after `ask` and
            # `use_prompt` close over `box`: both run on a click, long after this has bound.
            with ui.element("div").classes("advisor-composer"):
                with ui.element("div").classes("advisor-composer-row"):
                    box = ui.textarea(placeholder="Ask about your account, or about the game…")
                    box.classes("grow").props("autogrow outlined data-testid=advisor-input")
                    # Enter inserts a newline, as it should in a box that grows — a question
                    # here is often several lines, and a surface that sent on Enter would
                    # spend a paid call every time someone reached for a paragraph break.
                    box.on("keydown.ctrl.enter", ask)
                    box.on("keydown.meta.enter", ask)
                    # `color=None` is what keeps this button on the palette, and it is not
                    # optional — see the note above `.q-btn[data-testid="advisor-send"]` in
                    # `advisor.ADVISOR_CSS`. NiceGUI's default of `color="primary"` attaches
                    # `bg-primary`, whose `!important` sits in a cascade layer that no
                    # stylesheet this app adds can outrank. Removing the class is the fix;
                    # overriding it is not available.
                    send = ui.button("Ask", on_click=ask, color=None)
                    send.props("data-testid=advisor-send")
                # Inside the sticky block, so it travels with the control it describes rather
                # than scrolling away underneath it.
                ui.html("Ctrl + Enter to send").classes("advisor-hint")

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
