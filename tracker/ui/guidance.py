"""Drawing §21's generated guidance.

Every sentence this module shows was composed on :class:`~tracker.ui.view_model.GuidanceView`
or came straight from the model. Nothing is assembled inside a ``ui.html(...)`` call, for the
reason :mod:`tracker.ui.recommendations` gives: a sentence built in the renderer can only be
checked by driving a browser, and a rule that expensive to check stops being checked.

The two attribution details are §15's honesty discipline, not decoration. The provenance line
says who wrote the prose, because everything else on the page came from authored content and a
pure function and the reader should not have to infer which is which. The uncertainty section
is drawn apart from the warnings for the same reason it is stored apart: a hazard and a hedge
are different sentences.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from nicegui import ui

from tracker.ui.view_model import GuidanceView


def render_dialog(view: GuidanceView) -> None:
    """Draw one answer inside an already-open dialog card."""
    container = ui.element("div").classes("flex flex-col gap-2")
    container.props(f"data-testid=guidance data-candidate={view.candidate_id}")
    with container:
        ui.html(html.escape(view.task_name)).classes("text-base font-semibold")

        summary = ui.element("p").classes("text-sm m-0")
        summary.props("data-testid=guidance-summary")
        with summary:
            ui.html(html.escape(view.summary))

        _list_block("Before you start", view.prerequisites, "guidance-prerequisites")

        if view.steps:
            steps = ui.element("div").classes("flex flex-col gap-1")
            steps.props("data-testid=guidance-steps")
            with steps:
                ui.html("Steps").classes("layer-label")
                for step in view.steps:
                    item = ui.element("div").classes("text-sm")
                    item.props(f"data-testid=guidance-step data-order={step.order}")
                    with item:
                        ui.html(html.escape(step.label)).classes("font-medium block")
                        ui.html(html.escape(step.detail)).classes("opacity-80 block")

        _list_block("Watch out for", view.warnings, "guidance-warnings")

        # Kept visually distinct from the warnings above: this is the model telling you
        # which parts of its own answer to check, which is a different request of the reader.
        if view.uncertainty_label is not None:
            uncertain = ui.element("div").classes("flex flex-col gap-1 opacity-80")
            uncertain.props("data-testid=guidance-uncertain")
            with uncertain:
                ui.html(html.escape(view.uncertainty_label)).classes("layer-label")
                for item_text in view.uncertain:
                    ui.html(f"- {html.escape(item_text)}").classes("text-sm block")

        if view.session_label is not None:
            session = ui.html(html.escape(view.session_label)).classes("text-xs opacity-70")
            session.props("data-testid=guidance-session")

        provenance = ui.html(html.escape(view.provenance_label)).classes("text-xs opacity-60")
        provenance.props(f"data-testid=guidance-provenance data-cached={str(view.cached).lower()}")


def render_error(message: str) -> None:
    """Say what happened, in a place the user was already looking.

    Deliberately plain text rather than an alert: guidance is a terminal output (D14), so its
    absence changes nothing else on the page, and dressing the failure up would imply it did.
    """
    element = ui.html(html.escape(message)).classes("text-sm opacity-80")
    element.props("data-testid=guidance-error")


def _list_block(label: str, items: Sequence[str], testid: str) -> None:
    """A labelled list, or nothing at all when there is nothing to say.

    Omitted rather than drawn empty, matching :mod:`tracker.ui.recommendations`: a heading
    over no content reads as a claim that the list is empty, which is a stronger statement
    than "the model did not raise any".
    """
    if not items:
        return
    block = ui.element("div").classes("flex flex-col gap-1")
    block.props(f"data-testid={testid}")
    with block:
        ui.html(html.escape(label)).classes("layer-label")
        for item_text in items:
            ui.html(f"- {html.escape(item_text)}").classes("text-sm block")
