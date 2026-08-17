"""§15's dashboard: the current goal, character summary, readiness, and roadmap progress.

Three decisions worth recording, because each is a place the page could have invented state
the model does not have — or buried the one thing it exists to say.

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

**The goal is drawn first, and it is the only loud thing on the page.** It used to be the
fourth card, under character, readiness and roadmap progress — so the single question this
application exists to answer arrived below three cards of context for it. Context reads
perfectly well *after* the answer it contextualises, and it now does. Everything above the
goal was also competing with it at similar weight; the summary figures are one strip below
it now, which is what lets the goal be the thing the eye lands on.
"""

from __future__ import annotations

from nicegui import ui

from tracker.ui.components.badges import confidence_chip, staleness_note
from tracker.ui.shell import section
from tracker.ui.view_model import DashboardView, RecommendationRow

#: The hero, and the summary strip that had to get quieter for it to be one.
DASHBOARD_CSS = """
.goal-card {
  border-left: 2px solid var(--gold);
  background: linear-gradient(180deg, var(--panel-2), var(--panel) 60%);
}
.goal-eyebrow {
  font-size: 0.6875rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.09em; color: var(--gold); display: block; margin-bottom: 0.3rem;
}
.goal-name {
  font-size: 1.0625rem; font-weight: 600; line-height: 1.35; color: var(--ink);
}
.goal-estimate {
  font-family: var(--font-data); font-size: 0.8125rem; color: var(--ink-dim);
  display: block; margin-top: 0.3rem;
}
.goal-why { font-size: 0.8125rem; color: var(--ink-dim); margin: 0.45rem 0 0; }

.stat-strip { display: flex; flex-wrap: wrap; gap: 0.5rem 1.5rem; }
.stat { display: flex; flex-direction: column; }
.stat-label {
  font-size: 0.625rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--ink-faint); margin-top: 0.1rem;
}
.stat-name { font-size: 1rem; font-weight: 600; line-height: 1.4; color: var(--ink); }

.roadmap-row { margin-bottom: 0.55rem; }
.roadmap-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.roadmap-name { font-size: 0.8125rem; color: var(--ink); }
.roadmap-count { font-family: var(--font-data); font-size: 0.6875rem; color: var(--ink-faint); }
"""


def _stat(label: str, value: str, *, testid: str, figure: bool = True) -> None:
    """One figure in the summary strip.

    ``figure`` picks the type role. Numbers get the bitmap display face, which is what it is
    good at and what it stays crisp at; the account name does not, because a long username
    set in a bitmap face at this size is both harder to read and the most likely single
    string on the page to overflow a 390 px viewport.
    """
    element = ui.element("div").classes("stat")
    element.props(f"data-testid={testid}")
    with element:
        ui.html(value).classes("tracker-figure" if figure else "stat-name")
        ui.html(label).classes("stat-label")


def render_goal(goal: RecommendationRow) -> None:
    """§9.10's output shape, reduced to what fits above the fold on a phone.

    The "Why" line renders the persisted ``reason`` verbatim. Step 6 generated it from the
    largest log contributions (§9.5); composing new prose here is how a displayed reason
    starts describing a ranking that did not happen.
    """
    with ui.element("div").classes("flex flex-wrap items-baseline gap-2"):
        ui.html(goal.name).classes("goal-name")
        confidence_chip(goal.confidence, prefix="estimate: ")

    parts: list[str] = []
    if goal.estimated_hours is not None:
        parts.append(f"~{goal.estimated_hours:.1f} hours")
    if goal.estimated_gp is not None:
        parts.append(f"~{goal.estimated_gp:,} gp")
    if parts:
        ui.html(" · ".join(parts)).classes("goal-estimate")

    reason = ui.element("p").classes("goal-why")
    reason.props("data-testid=goal-reason")
    with reason:
        ui.html(f"Why: {goal.reason}")


def _render_roadmaps(view: DashboardView) -> None:
    if not view.roadmaps:
        ui.html("No roadmap selected yet.").classes("text-xs tracker-faint")
        return
    for roadmap in view.roadmaps:
        element = ui.element("div").classes("roadmap-row")
        element.props(f"data-testid=roadmap data-roadmap={roadmap.roadmap_id}")
        with element:
            with ui.element("div").classes("roadmap-head"):
                ui.html(roadmap.name).classes("roadmap-name")
                # §6.12 distinguishes the weights a run *used* from the live setting.
                # Showing the weight keeps a secondary roadmap's slow progress legible as a
                # deliberate choice rather than as a stalled goal.
                ui.html(
                    f"{roadmap.unlocked}/{roadmap.total} · weight {roadmap.selection_weight:g}"
                ).classes("roadmap-count")
            ui.linear_progress(roadmap.fraction, show_value=False, size="4px")


def render(view: DashboardView) -> None:
    """The whole dashboard, answer first."""
    ui.add_css(DASHBOARD_CSS)

    goal = ui.element("div").classes("tracker-card goal-card")
    goal.props("data-testid=current-goal")
    with goal:
        ui.html("Do this next").classes("goal-eyebrow")
        if view.current_goal is None:
            ui.html("No recommendation yet — sync RuneLite to generate one.").classes(
                "text-sm tracker-dim"
            )
        else:
            render_goal(view.current_goal)

    with section("Account", testid="account-summary"):
        # Two testids inside one card. They stay separate elements because §4.4's figures
        # and §4.5's are different claims and are asserted separately; they share a card
        # because five small numbers read as one strip and as five competing panels.
        character = ui.element("div").classes("stat-strip")
        character.props("data-testid=character-summary")
        with character:
            _stat("account", view.display_name, testid="stat-account", figure=False)
            _stat(
                "combat",
                str(view.combat_level) if view.combat_level is not None else "—",
                testid="stat-combat",
            )
            _stat(
                "quest points",
                str(view.quest_points) if view.quest_points is not None else "—",
                testid="stat-qp",
            )

        readiness = ui.element("div").classes("stat-strip mt-3")
        readiness.props("data-testid=readiness-summary")
        with readiness:
            _stat(
                "capabilities unlocked",
                f"{view.unlocked_capabilities}/{view.total_capabilities}",
                testid="stat-unlocked",
            )
            _stat("not yet observed", str(view.unknown_capabilities), testid="stat-unknown")

        ui.html(view.last_sync_at_label).classes("tracker-data block mt-3")
        if view.unknown_capabilities:
            # The unknown count is the one figure on this page that is a request rather than
            # a result, so it carries its own instruction (§15: unknown means "sync
            # RuneLite"). Without it the number reads as a score the user has done badly on.
            ui.html(
                "Open your bank and equipment in-game with RuneLite running to resolve these."
            ).classes("text-xs tracker-dim block mt-1")

    with section("Roadmap progress", testid="roadmap-progress"):
        _render_roadmaps(view)

    with section("What we have seen", testid="staleness"):
        for note in view.staleness_notes:
            staleness_note(note)
