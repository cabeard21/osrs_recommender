"""§15's Skills view. Progress bars, and one rule that outranks all of them.

> Unranked skills render as unranked, not as level 1.

That rule is enforced in :mod:`tracker.ui.view_model`, not here: :class:`SkillRow` carries
``level=None`` for an unranked skill, so this module has no number available to print even
if it wanted one. What is left for the page is to make sure nothing *reconstructs* the
level — no ``or 1`` default, no ``max(level, 1)`` for the progress bar, no sort key that
falls back to a numeric level.

The temptation is real, because ``SkillSnapshot.level`` is not nullable and always holds
something. §6.2 is explicit that the meaningful column is ``xp``: *"``NULL`` means unranked,
never ``0``"*. An account that has never appeared on the hiscores has a level-1 row for every
skill, and rendering those as 1s would state 23 facts we do not have.
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from tracker.ui.shell import section
from tracker.ui.view_model import SkillRow

#: The note under the unranked group. Phrased as a fact about the hiscores rather than about
#: the player, because that is what it is: an unranked skill is one below the hiscores'
#: reporting floor, not one the player has neglected.
UNRANKED_NOTE = (
    "Below the hiscores' ranking threshold, so no experience figure exists for them yet. "
    "This is not the same as level 1."
)


def render_skill(row: SkillRow) -> None:
    """One skill row: name, level (or "unranked"), and a bar.

    The bar renders at zero width for an unranked skill rather than being omitted, so the
    list keeps a stable row height. It is *not* rendered at 1/99 — a hairline of progress
    would be the level-1 claim smuggled back in as pixels.
    """
    element = ui.element("div").classes("tracker-card")
    element.props(
        f"data-testid=skill data-skill={row.skill_id} "
        f"data-ranked={'true' if row.is_ranked else 'false'}"
    )
    with element:
        with ui.element("div").classes("flex items-baseline justify-between gap-2"):
            ui.html(row.name).classes("text-sm")
            ui.html(row.level_label).classes(
                "text-sm font-semibold" if row.is_ranked else "text-xs opacity-70 italic"
            )
        ui.linear_progress(row.progress, show_value=False, size="6px").props(
            "data-testid=skill-progress"
        )
        if row.is_ranked and row.xp is not None:
            ui.html(f"{row.xp:,} xp").classes("text-xs opacity-60 block")


def render(rows: Sequence[SkillRow]) -> None:
    """Ranked skills, then the unranked ones under their own heading.

    Two groups rather than one list with a footnote. Mixed in, an unranked skill has to be
    *read* to be distinguished from a low-level one; grouped, the distinction is structural
    and the note explaining it has somewhere to live.
    """
    ranked = tuple(row for row in rows if row.is_ranked)
    unranked = tuple(row for row in rows if not row.is_ranked)

    with section(f"Ranked ({len(ranked)})", testid="skills-ranked"):
        if not ranked:
            ui.html("No ranked skills observed yet.").classes("text-xs opacity-60")
        for row in ranked:
            render_skill(row)

    with section(f"Unranked ({len(unranked)})", testid="skills-unranked"):
        ui.html(UNRANKED_NOTE).classes("text-xs opacity-70 block mb-1")
        if not unranked:
            ui.html("None.").classes("text-xs opacity-50")
        for row in unranked:
            render_skill(row)
