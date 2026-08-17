"""§15's four-state unlock cards, grouped so that ``unknown`` is impossible to overlook.

§15's rendering table has four rows, and the fourth is the one with a rule attached:
unlocked is green, available yellow, locked gray, and **unknown outlined / hatched** —

> Unknown must never render as locked. It means "sync RuneLite", not "go do this."

Two things enforce that here. The badge comes from the single implementation in
:mod:`tracker.ui.components.badges`, which draws its class from
:data:`~tracker.ui.states.STATE_CLASSES` — an injective mapping, so no two states can share
markup. And ``unknown`` is its own **group**, rendered first with its own explanation,
rather than a differently-coloured card mixed in among the rest. A hatched card sitting
between grey ones still reads as "one of the ones I don't have"; a section headed *"not yet
observed"* does not.

``available`` keeps its own group for the reason §6.3 spells out: the word reads as
positive, §9.1 resolves it to *unsatisfied*, and it is the single most likely place for an
implementation to go wrong.
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from tracker.ui.components.badges import state_badge
from tracker.ui.shell import section
from tracker.ui.states import UiState
from tracker.ui.view_model import UnlockRow

#: Group headings, in render order. ``unknown`` leads because it is the only one of the four
#: that asks something of the user right now.
GROUPS: tuple[tuple[UiState, str, str], ...] = (
    (
        UiState.UNKNOWN,
        "Not yet observed",
        "No sync has told us about these. Launch RuneLite with the companion plugin.",
    ),
    (UiState.UNLOCKED, "Unlocked", "Confirmed on your account."),
    (
        UiState.AVAILABLE,
        "Available",
        "Attainable but not held yet - visible to you, not yet yours.",
    ),
    (UiState.LOCKED, "Locked", "Not available yet."),
)


def group_rows(rows: Sequence[UnlockRow]) -> dict[UiState, tuple[UnlockRow, ...]]:
    """Partition rows by state, alphabetically within each group. Pure and testable."""
    grouped: dict[UiState, list[UnlockRow]] = {state: [] for state, _, _ in GROUPS}
    for row in rows:
        grouped[row.state].append(row)
    return {state: tuple(sorted(items, key=lambda r: r.name)) for state, items in grouped.items()}


def render_card(row: UnlockRow) -> None:
    """One unlock card. The ``data-state`` lives on the card *and* on its badge.

    Both, because the two answer different questions. The badge's attribute is what proves
    the four visual treatments are disjoint; the card's is what lets a test ask "is this
    unlock rendered as unknown?" without depending on where inside the card the badge sits.
    """
    card = ui.element("div").classes("tracker-card flex items-center justify-between gap-2")
    card.props(f"data-testid=unlock data-unlock={row.key} data-state={row.state.value}")
    with card:
        ui.html(row.name).classes("text-sm")
        state_badge(row.state)


def render(rows: Sequence[UnlockRow]) -> None:
    """The whole view: four groups, each rendered even when empty.

    Empty groups still render their heading and note. An absent "Not yet observed" section
    is indistinguishable from a page that does not model unknown at all, and the difference
    between those two is the entire subject of §4.5.
    """
    grouped = group_rows(rows)
    for state, heading, note in GROUPS:
        items = grouped[state]
        container = section(f"{heading} ({len(items)})", testid=f"unlock-group-{state.value}")
        with container:
            ui.html(note).classes("text-xs tracker-dim block mb-1")
            if not items:
                ui.html("None.").classes("text-xs tracker-faint")
                continue
            with ui.element("div").classes("tracker-grid"):
                for row in items:
                    render_card(row)
