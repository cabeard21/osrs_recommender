"""The attributed, account-aware PvM bossing ladder surface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from nicegui import ui

from tracker.domain.types import LeafRef
from tracker.ui.bossing_read_model import (
    BossingEncounterRow,
    BossingGuideView,
    BossingPreparationRow,
    BossingStatus,
)
from tracker.ui.components.badges import state_badge
from tracker.ui.states import UiState

BOSSING_CSS = """
.bossing-summary { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.6rem; }
.bossing-summary > div { padding:.65rem; background:var(--panel-2);
                         border:1px solid var(--edge-soft); }
.bossing-tier { width:100%; border:1px solid var(--edge-soft); border-radius:.375rem;
                margin-bottom:.65rem; overflow:hidden; }
.bossing-tier .q-item { min-height:3rem; padding:.55rem .7rem; }
.bossing-subhead { margin:.75rem 0 .4rem; color:var(--gold); font-size:.75rem;
                   font-weight:600; letter-spacing:.04em; text-transform:uppercase; }
.bossing-entry { width:100%; border-top:1px solid var(--edge-soft); padding:.75rem; }
.bossing-entry-head { display:flex; align-items:flex-start; justify-content:space-between;
                      gap:.5rem; margin-bottom:.45rem; }
.bossing-copy { font-size:.8125rem; color:var(--ink-dim); margin:.3rem 0; }
.bossing-copy strong { color:var(--ink); }
.bossing-source { display:inline-block; margin-top:.55rem; color:var(--gold); font-size:.75rem; }
@media (max-width:24.5rem) {
  .bossing-entry-head { flex-direction:column; }
  .bossing-summary { grid-template-columns:1fr; }
}
"""

_STATUS_UI = {
    BossingStatus.READY: (UiState.UNLOCKED, "Ready to try"),
    BossingStatus.BUILDING_TOWARD: (UiState.AVAILABLE, "Building toward"),
    BossingStatus.LOCKED: (UiState.LOCKED, "Locked"),
    BossingStatus.SYNC_NEEDED: (UiState.UNKNOWN, "Sync needed"),
}


def render(view: BossingGuideView, source: Any) -> None:
    """Render preparation before encounters in each source-ordered tier."""
    ui.add_css(BOSSING_CSS)
    with ui.element("div").classes("tracker-card bossing-summary") as summary:
        summary.props("data-testid=bossing-summary")
        _stat("Ready", view.ready_count)
        _stat("Building toward", view.building_toward_count)

    closest = ui.element("div").classes("tracker-card")
    closest.props("data-testid=bossing-closest-next")
    with closest:
        ui.html("Closest next encounter").classes("tracker-card-title")
        if view.closest_next is None:
            ui.html("Every encounter is ready to try.").classes("text-sm tracker-dim")
        else:
            ui.html(view.closest_next.name).classes("text-sm")
            percentage = round(view.closest_next.readiness_fraction * 100)
            ui.html(f"{percentage}% of the suggested setup observed").classes("tracker-data")

    for tier in view.tiers:
        expansion = ui.expansion(
            f"{tier.name}  ·  {tier.ready_count} ready  ·  {tier.building_toward_count} building",
            value=tier.id == view.default_expanded_tier_id,
        ).classes("bossing-tier")
        expansion.props(f"data-testid=bossing-tier data-tier={tier.id}")
        with expansion:
            if tier.preparation:
                ui.html("Preparation").classes("bossing-subhead")
                for step in tier.preparation:
                    _preparation(step)
            ui.html("Encounters").classes("bossing-subhead")
            for encounter in tier.encounters:
                _encounter(encounter)

    link = ui.link(
        f"Based on the Old School RuneScape Wiki Bossing Ladder, revision {source.revision}",
        source.url,
        new_tab=True,
    ).classes("bossing-source")
    link.props("data-testid=bossing-source rel=noopener")
    ui.html(f"Checked {source.checked_at}; {source.license}.").classes("text-xs tracker-faint")


def _stat(label: str, value: int) -> None:
    with ui.element("div"):
        ui.html(str(value)).classes("tracker-figure")
        ui.html(label).classes("tracker-data")


def _badge(status: BossingStatus) -> None:
    state, label = _STATUS_UI[status]
    state_badge(state, label=label)


def _preparation(step: BossingPreparationRow) -> None:
    entry = ui.element("article").classes("bossing-entry")
    entry.props(f"data-testid=bossing-preparation data-step={step.id}")
    with entry:
        with ui.element("div").classes("bossing-entry-head"):
            ui.html(step.name).classes("text-sm font-medium")
            if step.informational:
                ui.html("Guidance").classes("tracker-data")
            else:
                _badge(step.status)
        if not step.informational:
            _requirements(step.blockers, step.unknowns)


def _encounter(encounter: BossingEncounterRow) -> None:
    entry = ui.element("article").classes("bossing-entry")
    entry.props(f"data-testid=bossing-encounter data-encounter={encounter.id}")
    with entry:
        with ui.element("div").classes("bossing-entry-head"):
            link = ui.link(encounter.name, encounter.wiki_url, new_tab=True).classes(
                "text-sm font-medium"
            )
            link.props("rel=noopener")
            _badge(encounter.status)

        blockers = (*encounter.access_blockers, *encounter.recommendation_blockers)
        unknowns = (*encounter.access_unknowns, *encounter.recommendation_unknowns)
        _requirements(blockers, unknowns)
        _copy("Mechanics", encounter.mechanics, testid="bossing-mechanics")
        _copy("Rewards", encounter.rewards, testid="bossing-rewards")


def _requirements(blockers: Sequence[LeafRef], unknowns: Sequence[LeafRef]) -> None:
    _leaf_list(blockers, testid="bossing-blockers", cta="Work on these", empty="No blockers.")
    _leaf_list(unknowns, testid="bossing-unknowns", cta="Sync needed", empty="Nothing to sync.")


def _leaf_list(leaves: Sequence[LeafRef], *, testid: str, cta: str, empty: str) -> None:
    container = ui.element("div").classes("w-full")
    container.props(f"data-testid={testid}")
    with container:
        ui.html(cta).classes("cta")
        if not leaves:
            ui.html(empty).classes("text-xs tracker-faint")
            return
        with ui.element("ul").classes("leaf-list"):
            for leaf in leaves:
                with ui.element("li"):
                    ui.html(leaf.description or leaf.key)


def _copy(label: str, values: Sequence[str], *, testid: str) -> None:
    element = ui.element("p").classes("bossing-copy")
    element.props(f"data-testid={testid}")
    with element:
        ui.html(f"<strong>{label}:</strong> {'; '.join(values)}")
