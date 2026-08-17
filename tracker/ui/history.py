"""§6.10, §15's History view: XP charts, ranked-run history, and a snapshot diff.

§6.10 gives two reasons this table exists at all — *"required by the History UI, and more
importantly, by engine debuggability: two runs can be diffed to see which factor moved."*
This module is where both halves land: the snapshot list is the History UI itself, and
:func:`render_diff` is the debuggability half turned into a page.

Every snapshot in the list carries its own ``scoring_profile_version`` (§6.10, §9.7) —
never assumed constant, since a retune bumps it and an old run's ranking is only
interpretable against the profile that actually produced it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import plotly.graph_objects as go
from nicegui import ui

from tracker.ui.shell import empty_state, section
from tracker.ui.view_model import FactorDiffRow, HistorySnapshotRow, SkillXpPoint


def _xp_chart(series: Mapping[str, Sequence[SkillXpPoint]]) -> go.Figure:
    """One line per skill, oldest observation first (§6.2, §15).

    Built even when ``series`` is empty — an empty figure with axes is what tells a reader
    "no history yet" is a fact about our records, not a broken chart.
    """
    figure = go.Figure()
    for skill, points in sorted(series.items()):
        figure.add_trace(
            go.Scatter(
                x=[point.observed_at for point in points],
                y=[point.xp for point in points],
                mode="lines+markers",
                name=skill,
            )
        )
    figure.update_layout(
        margin={"l": 40, "r": 10, "t": 10, "b": 40},
        xaxis_title="observed",
        yaxis_title="xp",
        legend={"orientation": "h"},
    )
    return figure


def render_xp_chart(series: Mapping[str, Sequence[SkillXpPoint]]) -> None:
    with section("XP history", testid="history-xp-chart"):
        if not series:
            ui.html("No XP history yet - it builds up as syncs arrive.").classes(
                "text-xs tracker-faint"
            )
            return
        plot = ui.plotly(_xp_chart(series)).classes("w-full")
        plot.props("data-testid=xp-chart")


def render_snapshots(rows: Sequence[HistorySnapshotRow]) -> None:
    with section("Recommendation history", testid="history-snapshots"):
        if not rows:
            empty_state("No runs recorded yet.", testid="history-empty")
            return
        for row in rows:
            element = ui.element("div").classes("tracker-card")
            element.props(
                f"data-testid=history-snapshot data-snapshot={row.snapshot_id} "
                f"data-profile-version={row.scoring_profile_version}"
            )
            with element:
                with ui.element("div").classes(
                    "flex flex-wrap items-baseline justify-between gap-2"
                ):
                    ui.html(row.run_at.isoformat()).classes("text-xs tracker-dim")
                    ui.html(f"scoring profile v{row.scoring_profile_version}").classes(
                        "text-xs tracker-dim"
                    )
                if row.top_candidate_name is not None:
                    ui.html(row.top_candidate_name).classes("text-sm font-semibold block")
                    if row.top_reason:
                        ui.html(f"Why: {row.top_reason}").classes("text-xs tracker-dim block")
                else:
                    ui.html("No unblocked recommendation this run.").classes(
                        "text-xs tracker-faint"
                    )


def render_diff(
    before: HistorySnapshotRow | None,
    after: HistorySnapshotRow | None,
    rows: Sequence[FactorDiffRow],
) -> None:
    """§6.10's diff view: which factor moved between two runs."""
    with section("Compare two runs", testid="history-diff"):
        if before is None or after is None:
            ui.html("Pick two runs above to compare them.").classes("text-xs tracker-faint")
            return
        ui.html(f"Snapshot {before.snapshot_id} -> Snapshot {after.snapshot_id}").classes(
            "text-xs tracker-dim block mb-1"
        )
        if not rows:
            ui.html("No shared candidates between these two runs.").classes("text-xs tracker-faint")
            return
        for diff in rows:
            element = ui.element("div").classes("layer-row")
            element.props(
                f"data-testid=factor-diff data-candidate={diff.candidate_id} "
                f"data-factor={diff.factor}"
            )
            with element:
                ui.html(f"{diff.candidate_id} · {diff.factor.replace('_', ' ')}").classes(
                    "layer-label"
                )
                moved = "-" if diff.delta is None else f"{diff.delta:+.2f}"
                ui.html(
                    f"{diff.before if diff.before is not None else '—'} -> "
                    f"{diff.after if diff.after is not None else '—'}  ({moved})"
                )


def render(
    snapshots: Sequence[HistorySnapshotRow],
    xp: Mapping[str, Sequence[SkillXpPoint]],
    *,
    diff_before: HistorySnapshotRow | None = None,
    diff_after: HistorySnapshotRow | None = None,
    diff_rows: Sequence[FactorDiffRow] = (),
) -> None:
    """The whole view."""
    render_xp_chart(xp)
    render_snapshots(snapshots)
    render_diff(diff_before, diff_after, diff_rows)
