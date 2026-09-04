"""§4.3, §6.12, §15's roadmap selector: one primary, any number of secondaries.

*"First-run is a simple choice of playstyle rather than an abstract weighting exercise"*
(§4.3) is the whole design brief for this page. The default surface is a radio button for
primary and a checkbox per secondary — no numbers anywhere. Selection weights (§4.3's
``1.00`` primary / ``0.25`` secondary defaults) are real and are what gets written to
``ActiveRoadmap`` (A13), but they are never the thing a first-run user is asked to set.

**Weights live behind "Advanced settings"** (§4.3, §15) — an expansion a player opens only
if they already know what a selection weight is. Nothing here defaults to a hand-picked
number: choosing a primary always writes ``1.00`` and a secondary always writes ``0.25``
unless the advanced panel is used to override it (§6.12: *"stored raw... normalized at read
time"*).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from nicegui import ui

from tracker.ui.shell import section
from tracker.ui.view_model import RoadmapOptionRow, mark_primary

PrimaryHandler = Callable[[str], None]
SecondaryHandler = Callable[[str, bool], None]
WeightHandler = Callable[[str, float], None]


def render(
    options: Sequence[RoadmapOptionRow],
    *,
    on_select_primary: PrimaryHandler,
    on_toggle_secondary: SecondaryHandler,
    on_set_weight: WeightHandler,
) -> None:
    """The whole view: a primary radio group, secondary checkboxes, and advanced weights."""
    with section("PvM bossing ladder", testid="pvm-ladder-card"):
        ui.html(
            "A six-tier, encounter-by-encounter guide based on your observed account readiness."
        ).classes("text-sm tracker-dim mb-2")
        link = ui.link("Open the granular ladder", "/roadmaps/pvm-ladder").classes("text-sm")
        link.style("color: var(--gold)")
        link.props("data-testid=pvm-ladder-link")

    primary = mark_primary(options)
    primary_id = primary[0].roadmap_id if primary else None

    with section("Primary roadmap", testid="roadmap-primary"):
        ui.html(
            "Your main goal. Weighted at 1.00 (§4.3) unless changed in advanced settings."
        ).classes("text-xs tracker-dim block mb-1")
        group = ui.radio(
            {option.roadmap_id: option.name for option in options},
            value=primary_id,
            on_change=lambda event: on_select_primary(event.value),
        )
        group.props("data-testid=primary-roadmap-radio")

    with section("Secondary roadmaps", testid="roadmap-secondary"):
        ui.html("Optional. Weighted at 0.25 (§4.3) unless changed in advanced settings.").classes(
            "text-xs tracker-dim block mb-1"
        )
        for option in options:
            if option.roadmap_id == primary_id:
                continue
            checkbox = ui.checkbox(
                option.name,
                value=option.selected,
                on_change=lambda event, roadmap_id=option.roadmap_id: on_toggle_secondary(
                    roadmap_id, event.value
                ),
            )
            checkbox.props(
                f"data-testid=secondary-roadmap-checkbox data-roadmap={option.roadmap_id}"
            )

    with ui.expansion("Advanced settings", icon="tune").props("data-testid=roadmap-advanced"):
        ui.html(
            "Raw selection weights (§6.12). Normalized to sum to 1 when the engine runs."
        ).classes("text-xs tracker-dim block mb-1")
        for option in options:
            if not option.selected:
                continue
            with ui.element("div").classes("layer-row"):
                ui.html(option.name).classes("layer-label")
                slider = ui.number(
                    value=option.selection_weight,
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    on_change=lambda event, roadmap_id=option.roadmap_id: on_set_weight(
                        roadmap_id, float(event.value)
                    ),
                )
                slider.props(f"data-testid=roadmap-weight-input data-roadmap={option.roadmap_id}")
