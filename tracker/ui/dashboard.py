"""Account and Quest Cape observability for the Companion dashboard."""

from __future__ import annotations

from nicegui import ui

from tracker.ui.components.badges import staleness_note
from tracker.ui.shell import section
from tracker.ui.view_model import DashboardView


def render(view: DashboardView) -> None:
    with section("Account", testid="account-summary"):
        ui.label(view.display_name).classes("font-semibold")
        ui.label(
            f"Combat: {view.combat_level if view.combat_level is not None else 'unknown'} · "
            f"Quest points: {view.quest_points if view.quest_points is not None else 'unknown'}"
        ).classes("text-sm tracker-dim")
        ui.label(view.last_sync_at_label).classes("text-xs tracker-faint")

    with section("Quest Cape", testid="quest-cape-status"):
        ui.html(
            f"{view.quest_cape_completed}/{view.quest_cape_total} completed · "
            f"{view.quest_cape_available} available now · "
            f"{view.quest_cape_unknown} with unknown status"
        ).classes("text-sm tracker-data")
        ui.html("Availability is factual, not a recommended next action.").classes(
            "text-xs tracker-faint"
        )

    with section("What we have seen", testid="staleness"):
        for note in view.staleness_notes:
            staleness_note(note)
