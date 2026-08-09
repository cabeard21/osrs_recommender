"""§15's dashboard: character summary, readiness, roadmap progress, and the current goal.

Two decisions worth recording, because both are places the page could have invented state
the model does not have.

**"Current goal" is derived, not stored.** §15 names it and §6 defines no model for it, so
it is the top-ranked unblocked entry of the latest §6.10 snapshot — see
:func:`tracker.ui.read_model.current_goal`. A ``current_goal`` table would be a second
answer to a question the snapshot already answers, and the two would disagree the first time
a pipeline run finished without the user acknowledging it.

**Overall readiness is three numbers, not one.** The obvious dashboard metric is a single
percentage, and it cannot be computed honestly: §4.4 keeps ``unknown`` off the
locked-to-unlocked scale entirely, so any single figure has to either count unknowns as
locked (understating, and telling the user to go train when they should sync) or exclude
them (a percentage of a denominator that silently shrinks as evidence goes missing). The
unknown count is shown as its own figure with its own call to action instead.
"""

from __future__ import annotations

from nicegui import ui

from tracker.ui.components.badges import confidence_chip, staleness_note
from tracker.ui.shell import section
from tracker.ui.view_model import DashboardView, RecommendationRow


def _stat(label: str, value: str, *, testid: str) -> None:
    """One figure in the summary strip."""
    element = ui.element("div").classes("flex flex-col")
    element.props(f"data-testid={testid}")
    with element:
        ui.html(value).classes("text-lg font-semibold leading-tight")
        ui.html(label).classes("text-xs opacity-65")


def render_goal(goal: RecommendationRow) -> None:
    """§9.10's output shape, reduced to what fits above the fold on a phone.

    The "Why" line renders the persisted ``reason`` verbatim. Step 6 generated it from the
    largest log contributions (§9.5); composing new prose here is how a displayed reason
    starts describing a ranking that did not happen.
    """
    with ui.element("div").classes("flex flex-wrap items-baseline gap-2"):
        ui.html(goal.name).classes("text-base font-semibold")
        confidence_chip(goal.confidence, prefix="estimate: ")

    parts: list[str] = []
    if goal.estimated_hours is not None:
        parts.append(f"~{goal.estimated_hours:.1f} hours")
    if goal.estimated_gp is not None:
        parts.append(f"~{goal.estimated_gp:,} gp")
    if parts:
        ui.html("  -  ".join(parts)).classes("text-sm block")

    reason = ui.element("p").classes("text-sm opacity-80 m-0 mt-1")
    reason.props("data-testid=goal-reason")
    with reason:
        ui.html(f"Why: {goal.reason}")


def _render_roadmaps(view: DashboardView) -> None:
    if not view.roadmaps:
        ui.html("No roadmap selected yet.").classes("text-xs opacity-60")
        return
    for roadmap in view.roadmaps:
        element = ui.element("div").classes("mb-2")
        element.props(f"data-testid=roadmap data-roadmap={roadmap.roadmap_id}")
        with element:
            with ui.element("div").classes("flex items-baseline justify-between gap-2"):
                ui.html(roadmap.name).classes("text-sm")
                # §6.12 distinguishes the weights a run *used* from the live setting.
                # Showing the weight keeps a secondary roadmap's slow progress legible as a
                # deliberate choice rather than as a stalled goal.
                ui.html(
                    f"{roadmap.unlocked}/{roadmap.total} - weight {roadmap.selection_weight:g}"
                ).classes("text-xs opacity-65")
            ui.linear_progress(roadmap.fraction, show_value=False, size="6px")


def render(view: DashboardView) -> None:
    """The whole dashboard."""
    with section("Character", testid="character-summary"):
        with ui.element("div").classes("flex flex-wrap gap-6"):
            _stat("account", view.display_name, testid="stat-account")
            _stat(
                "combat level",
                str(view.combat_level) if view.combat_level is not None else "unknown",
                testid="stat-combat",
            )
            _stat(
                "quest points",
                str(view.quest_points) if view.quest_points is not None else "unknown",
                testid="stat-qp",
            )
        ui.html(view.last_sync_at_label).classes("text-xs opacity-65 block mt-1")

    with section("Readiness", testid="readiness-summary"):
        with ui.element("div").classes("flex flex-wrap gap-6"):
            _stat(
                "capabilities unlocked",
                f"{view.unlocked_capabilities} / {view.total_capabilities}",
                testid="stat-unlocked",
            )
            _stat("not yet observed", str(view.unknown_capabilities), testid="stat-unknown")
        if view.unknown_capabilities:
            # The unknown count is the one figure on this page that is a request rather than
            # a result, so it carries its own instruction (§15: unknown means "sync
            # RuneLite"). Without it the number reads as a score the user has done badly on.
            ui.html(
                "Open your bank and equipment in-game with RuneLite running to resolve these."
            ).classes("text-xs opacity-70 block mt-1")

    with section("Roadmap progress", testid="roadmap-progress"):
        _render_roadmaps(view)

    with section("Current goal", testid="current-goal"):
        if view.current_goal is None:
            ui.html("No recommendation yet - sync RuneLite to generate one.").classes(
                "text-sm opacity-70"
            )
        else:
            render_goal(view.current_goal)

    with section("What we have seen", testid="staleness"):
        for note in view.staleness_notes:
            staleness_note(note)
