"""Drawing §22's conversation.

Every sentence here was composed on :class:`~tracker.ui.view_model.AdvisorMessageRow`, for the
reason :mod:`tracker.ui.guidance` gives: a sentence assembled inside a ``ui.html(...)`` call can
only be checked by driving a browser, and a rule that expensive to check stops being checked.

**One deliberate exception to this package's escaping habit.** An answer is markdown, and is
drawn with :func:`nicegui.ui.markdown` rather than escaped into a paragraph — it is the one
place in the application where model-authored text becomes markup. That is safe because
NiceGUI's markdown renderer escapes embedded HTML, and it is *worth it* because a wall of
unformatted prose is a materially worse answer than the same words with its lists intact. The
question the user typed is escaped as usual: it is their text, not the model's, and it has no
reason to render as anything.

Every failure draws as ordinary text inside the conversation, where the reader is already
looking. Never a toast and never anywhere else on the page: D14 promises an advisor failure
changes nothing else, and a modal that interrupts the whole screen would quietly break that
promise while the code underneath still kept it.
"""

from __future__ import annotations

import html
from collections.abc import Callable

from nicegui import ui

from tracker.ui.view_model import ADVISOR_EMPTY, AdvisorMessageRow, AdvisorThreadView


def render_thread(view: AdvisorThreadView) -> None:
    """Draw every stored message in order, or the empty state."""
    if view.is_empty:
        render_empty()
        return
    for message in view.messages:
        render_message(message)


def render_empty() -> None:
    """What the advisor can see, so the first question is an informed one."""
    element = ui.html(html.escape(ADVISOR_EMPTY)).classes("text-sm opacity-70")
    element.props("data-testid=advisor-empty")


def render_message(row: AdvisorMessageRow) -> None:
    """One question or one answer, with §22.8's attribution beneath it."""
    container = ui.element("div").classes("flex flex-col gap-1")
    container.props(f"data-testid=advisor-message data-role={row.role}")
    with container:
        ui.html(html.escape(row.role)).classes("layer-label")

        body = ui.element("div").classes("text-sm")
        body.props("data-testid=advisor-text")
        with body:
            if row.is_answer:
                # The one place model text becomes markup — see the module docstring.
                ui.markdown(row.text)
            else:
                ui.html(html.escape(row.text))

        # Drawn apart from the answer, because this is the model telling you which parts of
        # its own reply to check — a different request of the reader than the reply itself.
        if row.uncertainty_label is not None:
            uncertain = ui.element("div").classes("flex flex-col gap-1 opacity-80")
            uncertain.props("data-testid=advisor-uncertain")
            with uncertain:
                ui.html(html.escape(row.uncertainty_label)).classes("layer-label")
                for item in row.uncertain:
                    ui.html(f"- {html.escape(item)}").classes("text-sm block")

        _note(row.staleness_note, "advisor-stale")
        _note(row.truncation_note, "advisor-truncated")
        _note(row.sources_label, "advisor-sources")

        if row.provenance_label is not None:
            provenance = ui.html(html.escape(row.provenance_label)).classes("text-xs opacity-60")
            provenance.props("data-testid=advisor-provenance")


def render_pending(question: str) -> None:
    """The question, echoed immediately, with a spinner under it.

    Optimistic because the alternative is a second or more of a page that looks like it ignored
    the keypress. The row is drawn from the same view type as a stored one, so nothing about it
    is a special case except that its answer has not arrived.
    """
    render_message(AdvisorMessageRow(role="you", text=question))
    pending = ui.element("div").classes("flex items-center gap-2 text-sm opacity-70")
    pending.props("data-testid=advisor-pending")
    with pending:
        ui.spinner(size="sm")
        ui.html("Thinking…")


def render_error(message: str) -> None:
    """Say what happened, in the conversation, in plain text.

    Deliberately not an alert or a toast: the advisor is a terminal output (D14), so its
    failure changes nothing else, and dressing it up would imply otherwise.
    """
    element = ui.html(html.escape(message)).classes("text-sm opacity-80")
    element.props("data-testid=advisor-error")


def render_conversation_list(
    view: AdvisorThreadView, on_select: Callable[[int], None], on_new: Callable[[], None]
) -> None:
    """The threads beside this one, and the way to start another."""
    container = ui.element("div").classes("flex flex-wrap items-center gap-2")
    container.props("data-testid=advisor-conversations")
    with container:
        new = ui.button("New conversation", on_click=lambda _: on_new()).props("flat dense")
        new.props("data-testid=advisor-new")
        for row in view.conversations:
            button = ui.button(
                row.title,
                on_click=lambda _, identifier=row.conversation_id: on_select(identifier),
            )
            button.props("flat dense color=primary" if row.current else "flat dense")
            button.props(
                f"data-testid=advisor-conversation data-current={str(row.current).lower()}"
            )


def _note(text: str | None, testid: str) -> None:
    """A small aside, or nothing.

    Omitted rather than drawn empty for :mod:`tracker.ui.guidance`'s reason: a heading over no
    content reads as a claim, and each of these notes is an exception rather than a field.
    """
    if text is None:
        return
    element = ui.html(html.escape(text)).classes("text-xs opacity-70")
    element.props(f"data-testid={testid}")
