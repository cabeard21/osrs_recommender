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

import html
from collections.abc import Sequence
from typing import Protocol

from nicegui import ui

from tracker.ui.components.badges import confidence_chip, leaf_list
from tracker.ui.shell import empty_state, section
from tracker.ui.view_model import (
    BLOCKERS_CTA,
    NO_BLOCKERS,
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


def _method_lines(row: RecommendationEntryRow) -> None:
    """§15's "How" line: for each §8.2 band, the method and where it is trained.

    Rendered from the **persisted** band, never a re-selection — see
    :func:`tracker.ui.read_model._band_rows` for why that distinction is load-bearing.

    A band whose method fell back still renders, saying so in words. §8.4 requires the
    conservative default to be qualified rather than presented as a measurement, and
    hiding the row entirely would leave the reader with an hours figure and no way to know
    it was invented — which is worse than an ugly line.
    """
    container = ui.element("div").classes("flex flex-col gap-1")
    container.props(f"data-testid=method-detail data-bands={len(row.bands)}")
    with container:
        for band in row.bands:
            entry = ui.element("div").classes("flex flex-wrap items-baseline gap-2 text-sm")
            entry.props(
                f"data-band={band.level_label} data-method={band.method_id or ''} "
                f"data-fallback={str(band.fallback).lower()}"
            )
            with entry:
                ui.html(band.level_label).classes("opacity-60 text-xs")
                classes = "text-sm opacity-70 italic" if band.fallback else "text-sm"
                ui.html(html.escape(band.method_label)).classes(classes)
                if band.place_label:
                    ui.html(html.escape(band.place_label)).classes("text-xs opacity-70")
            if band.gear or band.inventory:
                # Free text, never `item:` leaves — see MethodDetail. Escaped for the same
                # reason every other authored string here is: content is trusted, but a
                # stray ampersand in a gear name should render as an ampersand.
                kit = " · ".join(
                    part
                    for part in (
                        ", ".join(band.gear),
                        "runes/supplies: " + ", ".join(band.inventory) if band.inventory else "",
                    )
                    if part
                )
                ui.html(html.escape(kit)).classes("text-xs opacity-60 block pl-6")
            if band.notes:
                ui.html(html.escape(band.notes)).classes("text-xs opacity-60 block pl-6")


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


class _Labelled(Protocol):
    """Anything carrying a rendered ``label`` — the four §9.10 consequence row types.

    A protocol rather than a union so this module never has to name them one by one, and so
    adding a fifth kind of consequence is a change in ``view_model`` alone. The contract is
    exactly what the renderer needs and nothing more: *the row knows its own words.*
    """

    @property
    def label(self) -> str: ...


def _consequence_row(heading: str, rows: Sequence[_Labelled], testid: str) -> None:
    """One §9.10 consequence line, or nothing at all when there is nothing to report.

    ``html.escape`` because these labels carry **content names** — a capability or candidate
    title straight out of the corpus — where the two lines above render ids and engine prose.
    A corpus is authored, so an ampersand in a quest name is a matter of time.
    """
    if not rows:
        return
    with ui.element("div").classes("layer-row"):
        ui.html(heading).classes("layer-label")
        line = ui.html(html.escape(", ".join(row.label for row in rows))).classes("text-sm")
        line.props(f"data-testid={testid}")


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

        # §9.10's consequences. Each label is composed on its row type in `view_model`, for
        # this module's standing rule: a sentence assembled inside a `ui.html(...)` call can
        # only be tested by driving a browser, and a rule that expensive to check stops being
        # checked. Here they are joined and drawn, and nothing else.
        #
        # Every block is conditional and several are routinely empty. That is the honest
        # rendering of an engine that found nothing to say — an entry showing no consequence
        # rows at all earned its place on cheapness alone, and the blank space says so more
        # usefully than a filler line would.
        _consequence_row("Unblocks", row.unblocks, "unblocks")
        _consequence_row("Needed for", row.needed_for, "needed-for")
        _consequence_row("Works toward", row.works_toward, "works-toward")
        _consequence_row("Speeds up", row.speeds_up, "speeds-up")

        if row.is_refresher and row.practice_members:
            with ui.element("div").classes("layer-row"):
                ui.html("Practice").classes("layer-label")
                ui.html(", ".join(row.practice_members)).classes("text-sm")

        with ui.element("div").classes("layer-row"):
            ui.html("Estimate").classes("layer-label")
            _estimate_line(row)
        if row.affordability_note:
            note = ui.html(html.escape(row.affordability_note))
            note.classes("text-xs opacity-70 block")
            note.props("data-testid=affordability")
        if row.has_method_detail:
            with ui.element("div").classes("layer-row"):
                ui.html("How").classes("layer-label")
                _method_lines(row)
        with ui.element("div").classes("layer-row"):
            ui.html("Priority").classes("layer-label")
            ui.html(row.priority_stars).classes("text-sm")

        reason = ui.element("p").classes("text-sm opacity-80 m-0 mt-1")
        reason.props("data-testid=recommendation-reason")
        with reason:
            ui.html(f"Why: {row.reason}")

        _factor_breakdown(row)


def render_blocked(rows: Sequence[BlockedRecommendationRow]) -> None:
    """§15's collapsed section — never mixed into the ranked list (§16.2).

    Each entry names **what** blocks it, not just that something does. A bare name is a
    goal with no path: "Complete Lunar Diplomacy — blocked" tells a reader nothing they can
    act on, and the Capabilities page has answered the same question since it was built.

    ``BLOCKERS_CTA`` is reused verbatim rather than reworded, so the two pages ask for the
    same thing in the same words — a reader who learns what "Do these to unlock it" means
    on one page should not have to learn it again on the other.
    """
    with ui.expansion(f"Blocked ({len(rows)})", icon="block").props("data-testid=blocked-section"):
        if not rows:
            ui.html("Nothing is blocked right now.").classes("text-xs opacity-60")
            return
        for row in rows:
            element = ui.element("div").classes("tracker-card")
            element.props(f"data-testid=blocked-candidate data-candidate={row.candidate_id}")
            with element:
                ui.html(row.name).classes("text-sm")
                if row.blockers:
                    leaf_list(
                        row.blockers,
                        testid="blocked-by",
                        cta=BLOCKERS_CTA,
                        empty=NO_BLOCKERS,
                    )


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
