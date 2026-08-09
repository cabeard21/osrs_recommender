"""The headline view — *"what can I actually do today?"* (§15).

Everything here exists to keep §4.4's three layers apart on screen:

* ``status`` renders as a state badge, from the same single implementation the unlocks view
  uses, so ``unknown`` cannot pick up ``locked``'s treatment in one view and not the other;
* ``readiness_confidence`` renders on its own row, as an em dash when the layer does not
  apply — never as "low", which would be a measurement we did not make;
* ``recommended_now`` renders with the engine's own reason.

There is no summary badge, and adding one later would be the mistake §4.4 names: *"collapsing
any two of these produces either backward progress or false confidence."* It is also why this
page has no filter that hides "not recommended" capabilities — a reader may collapse the
layers in their head, but only if all three were shown to them first.

Blockers and unknowns are two calls to :func:`~tracker.ui.components.badges.leaf_list` with
different ``data-testid``s and different CTAs, per §15's *"separate lists with separate calls
to action"*. They are never concatenated and never merged into one severity-sorted list:
"do this" and "sync this" are different requests, and a merged list can only carry one verb.
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from tracker.ui.components.badges import leaf_list, state_badge
from tracker.ui.shell import layer_row, section
from tracker.ui.states import UiState
from tracker.ui.view_model import (
    BLOCKERS_CTA,
    NO_BLOCKERS,
    NO_UNKNOWNS,
    UNKNOWNS_CTA,
    CapabilityRow,
)

#: The order capabilities are listed in. Unknown first, deliberately: §15 treats unknown as
#: a call to action ("sync RuneLite"), and an actionable item at the bottom of a list is an
#: item that never gets acted on. Within a state, the closest to unlocked comes first.
_STATE_ORDER = {
    UiState.UNKNOWN: 0,
    UiState.UNLOCKED: 1,
    UiState.AVAILABLE: 2,
    UiState.LOCKED: 3,
}


def sort_rows(rows: Sequence[CapabilityRow]) -> tuple[CapabilityRow, ...]:
    """Order for display. Pure, so the ordering policy is testable without a browser."""
    return tuple(
        sorted(rows, key=lambda row: (_STATE_ORDER[row.state], -row.unlock_fraction, row.name))
    )


def render_capability(row: CapabilityRow) -> None:
    """One capability card: name, progress, three layers, then the two lists."""
    card = section(row.name, testid="capability")
    card.props(f"data-capability={row.capability_id}")
    with card:
        ui.linear_progress(row.unlock_fraction, show_value=False, size="6px").props(
            f"data-testid=unlock-fraction data-fraction={row.unlock_fraction:.4f}"
        )

        layer_row("Status", lambda: state_badge(row.state, label=row.status_label))
        layer_row("Readiness confidence", lambda: ui.html(row.readiness_label))
        layer_row("Recommended now", lambda: ui.html(row.recommended_label))

        for warning in row.warnings:
            # §6.9 attaches warnings to readiness, not to status. They render under the
            # layer block rather than inside the readiness row so that a capability with
            # five warnings cannot push the third layer off a phone screen.
            ui.html(warning).classes("text-xs opacity-70 block")

        with ui.element("div").classes("tracker-grid mt-2"):
            leaf_list(row.blockers, testid="blockers", cta=BLOCKERS_CTA, empty=NO_BLOCKERS)
            leaf_list(row.unknowns, testid="unknowns", cta=UNKNOWNS_CTA, empty=NO_UNKNOWNS)


def render(rows: Sequence[CapabilityRow]) -> None:
    """The whole view.

    Takes rows rather than a session: the page function opens the session, and this stays a
    pure function of its input so both the ordering and the markup can be exercised without
    a database.
    """
    for row in sort_rows(rows):
        render_capability(row)
