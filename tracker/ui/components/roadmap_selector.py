"""The header roadmap selector — the one control that appears on every page.

The roadmap decides what every other view recommends (§4.3, §9.3), and until now it could
only be changed on ``/roadmaps``. A setting that reframes eight other pages belongs in the
chrome those pages share, for the same reason :data:`~tracker.ui.shell.NAV` is one tuple:
so there is one place it can be found and one place it can be forgotten.

**It switches the primary roadmap only.** §4.3 calls first-run *"a simple choice of
playstyle rather than an abstract weighting exercise"* — a single-value dropdown is that
choice, and secondaries and raw selection weights stay on ``/roadmaps`` where the exercise
lives. Both controls write through ``read_model.select_primary_roadmap`` and both reload,
so the header and the page cannot disagree.

Like every component here this renders a frozen model and calls a bound callback; it opens
no session and imports no read model, which is what lets :mod:`tracker.ui.shell` use it
without acquiring either.
"""

from __future__ import annotations

from nicegui import ui

from tracker.ui.view_model import RoadmapSelectorModel


def render(model: RoadmapSelectorModel) -> None:
    """Draw the selector. Call only with a model; ``None`` means *draw nothing* (§4.5)."""
    select = ui.select(
        {option.roadmap_id: option.name for option in model.options},
        value=model.value,
        label="Roadmap",
        on_change=lambda event: model.on_select(event.value),
    )
    # The width clamp is not decoration: this widget is now on all nine paths, and
    # ``test_no_horizontal_scroll_at_390px`` asserts none of them scrolls sideways on a
    # phone. An unclamped select grows to its longest option's label.
    select.props("data-testid=global-roadmap-select dense options-dense outlined")
    select.classes("w-full max-w-[14rem] text-sm mb-1")
