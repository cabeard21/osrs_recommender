"""§9.10's ranked list, rendered as the SDD's own worked output shape.

```
Next Recommendation

  Train Magic  87 → 94
  Unlocks      Ice Barrage
  Advances     Ice Barrage NH, Deep Wilderness NH
  Estimate     ~4.5 hours  ·  ~1.8M gp    [medium — price from a 3-day-old trade]
  Priority     ★★★★★

  Why: high PvP value (+0.61) · unblocks 2 capabilities (+0.44) · close to target (+0.30)
```

**The "Why" line renders ``RecommendationEntry.reason`` verbatim** (§9.5). Step 6 generated
it by reading off the largest log contributions; composing new prose here is exactly the
drift anti-pattern 9 names. The factor breakdown drawer is the same discipline one level
deeper — every number in it comes from the same ``factors`` JSON the reason was read from,
so the drawer and the sentence next to it can never disagree.

**G10, twice.** Step 6's engine already guarantees at most one refresher reaches the
persisted primary list (:func:`tracker.recommendations.refreshers.enforce_list_policy`).
:func:`render` calls :func:`~tracker.ui.view_model.assert_at_most_one_refresher` anyway,
as belt-and-braces: a future bug upstream should fail loudly on the page that would
otherwise quietly show two refreshers, rather than silently rendering a policy violation.
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from tracker.ui.components.badges import confidence_chip
from tracker.ui.shell import empty_state, section
from tracker.ui.view_model import (
    BlockedRecommendationRow,
    RecommendationEntryRow,
    assert_at_most_one_refresher,
)


def _estimate_line(row: RecommendationEntryRow) -> None:
    parts: list[str] = []
    if row.estimated_hours is not None:
        parts.append(f"~{row.estimated_hours:.1f} hours")
    if row.estimated_gp is not None:
        parts.append(f"~{row.estimated_gp:,} gp")
    with ui.element("div").classes("flex flex-wrap items-baseline gap-2"):
        ui.html("  -  ".join(parts) if parts else "no estimate").classes("text-sm")
        confidence_chip(row.confidence)


def _factor_breakdown(row: RecommendationEntryRow) -> None:
    """§8.4/§9.5's drawer: every factor's raw value and log contribution.

    An ``ui.expansion`` rather than always-open text: the ranked list is the thing a
    reader scans first, and a breakdown open by default for every one of a dozen entries
    is what pushes the list itself off a phone screen (§15). Rendered as a flex grid of
    small cards rather than an HTML ``<table>`` — NiceGUI's raw ``ui.element`` does not
    manage table semantics, and a grid keeps every value reachable by one stable
    ``data-testid`` per factor either way.
    """
    expansion = ui.expansion("Factors", icon="analytics")
    expansion.props("data-testid=factor-breakdown")
    with expansion, ui.element("div").classes("tracker-grid mt-1"):
        for factor in row.factors:
            card = ui.element("div").classes("text-xs")
            card.props(f"data-testid=factor data-factor={factor.name}")
            with card:
                ui.html(factor.name.replace("_", " ")).classes("opacity-70")
                ui.html(
                    f"value {factor.value:.2f} · weight {factor.weight:.2f} · "
                    f"contribution {factor.log_contribution:+.2f}"
                )


def render_entry(row: RecommendationEntryRow) -> None:
    """One §9.10 entry, refresher or progression, through the same markup either way."""
    card = section(row.name, testid="recommendation")
    card.props(f"data-candidate={row.candidate_id} data-kind={row.kind_label} data-rank={row.rank}")
    with card:
        if row.is_refresher and row.suggested_session:
            ui.html(f"Suggested session: {row.suggested_session}").classes(
                "text-xs opacity-70 block"
            )
        if row.unlocks:
            with ui.element("div").classes("layer-row"):
                ui.html("Unlocks").classes("layer-label")
                ui.html(", ".join(row.unlocks)).classes("text-sm")
        if row.advances:
            with ui.element("div").classes("layer-row"):
                ui.html("Advances").classes("layer-label")
                ui.html(", ".join(row.advances)).classes("text-sm")
        if row.is_refresher and row.practice_members:
            with ui.element("div").classes("layer-row"):
                ui.html("Practice").classes("layer-label")
                ui.html(", ".join(row.practice_members)).classes("text-sm")

        with ui.element("div").classes("layer-row"):
            ui.html("Estimate").classes("layer-label")
            _estimate_line(row)
        with ui.element("div").classes("layer-row"):
            ui.html("Priority").classes("layer-label")
            ui.html(row.priority_stars).classes("text-sm")

        reason = ui.element("p").classes("text-sm opacity-80 m-0 mt-1")
        reason.props("data-testid=recommendation-reason")
        with reason:
            ui.html(f"Why: {row.reason}")

        _factor_breakdown(row)


def render_blocked(rows: Sequence[BlockedRecommendationRow]) -> None:
    """§15's collapsed section — never mixed into the ranked list (§16.2)."""
    with ui.expansion(f"Blocked ({len(rows)})", icon="block").props("data-testid=blocked-section"):
        if not rows:
            ui.html("Nothing is blocked right now.").classes("text-xs opacity-60")
            return
        for row in rows:
            element = ui.element("div").classes("tracker-card")
            element.props(f"data-testid=blocked-candidate data-candidate={row.candidate_id}")
            with element:
                ui.html(row.name).classes("text-sm")


def render(
    rows: Sequence[RecommendationEntryRow], blocked: Sequence[BlockedRecommendationRow]
) -> None:
    """The whole view: the ranked primary list, then the collapsed blocked section."""
    assert_at_most_one_refresher(rows)

    if not rows:
        empty_state("No recommendation yet - sync RuneLite to generate one.")
    else:
        for row in rows:
            render_entry(row)

    render_blocked(blocked)
