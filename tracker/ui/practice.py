"""§9.8, §15's Practice freshness view — every stale group, and its two completion actions.

This is where refreshers beyond the primary list's one live (G10), so decaying practice
never crowds objective progression out of the ranked list.

**Two behaviourally distinct actions**, because a single tap must not silently attest to
five separate skills (§9.8):

| Action | Effect |
|---|---|
| **Mark session complete** | Refreshes every milestone listed in that session |
| **Review individual skills** | Lets the user refresh a subset |

Both call :func:`tracker.ui.read_model.refresh_milestones` with a different key set — the
two actions can never disagree about what "refreshed" means, only about which milestones
reach it. "Mark session complete" is a single button with no selection step, by design:
choosing which milestones to refresh is exactly what "review individual skills" is for, and
giving the session button a checklist too would blur the two into one action wearing two
labels.

**A RuneLite-derived LMS session needs no confirmation at all.** §9.8: *"A RuneLite-derived
LMS session refreshes all milestones whose ``practiced_by`` includes ``lms`` without any
prompt — derived evidence needs no confirmation."* That refresh already happened by the time
this page renders — :mod:`tracker.freshness.service` applies it during the sync pipeline —
so there is nothing for this view to prompt for; a milestone practiced via LMS simply is not
stale here, and never reaches this page's action buttons at all.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from nicegui import ui

from tracker.ui.shell import empty_state, section
from tracker.ui.view_model import PracticeGroupRow

#: Bound by the caller (§15's page function) to a write that opens its own session — the
#: page's own read session has already closed by the time a button is clicked (see
#: ``tracker.ui.pages``'s module docstring on reading before rendering).
CompletionHandler = Callable[[PracticeGroupRow, Sequence[str]], None]


def _member_checklist(group: PracticeGroupRow, on_review: CompletionHandler) -> None:
    """ "Review individual skills": an explicit checklist, unchecked by default.

    Nothing is pre-selected. §9.8's whole complaint is a tap that silently attests to
    milestones the user did not mean to confirm, and a checklist that starts fully ticked
    reproduces exactly that — the user would have to actively *un*-select what they did not
    practice, rather than actively select what they did.
    """
    selected: set[str] = set()

    def _toggle(key: str, *, value: bool) -> None:
        if value:
            selected.add(key)
        else:
            selected.discard(key)

    with ui.expansion("Review individual skills", icon="checklist").props(
        f"data-testid=review-individual data-group={group.template_id}"
    ):
        for member in group.members:
            ui.checkbox(
                member.name, on_change=lambda event, key=member.key: _toggle(key, value=event.value)
            ).props(f"data-testid=review-skill-checkbox data-skill={member.key}")

        def _submit() -> None:
            if selected:
                on_review(group, tuple(sorted(selected)))

        ui.button("Refresh selected", on_click=_submit).props(
            f"data-testid=review-submit data-group={group.template_id}"
        ).classes("text-xs")


def render_group(
    group: PracticeGroupRow, *, on_mark_complete: CompletionHandler, on_review: CompletionHandler
) -> None:
    """One stale practice group: its members, and the two §9.8 actions."""
    card = section(group.name, testid="practice-group")
    card.props(f"data-group={group.template_id} data-urgency={group.urgency:.2f}")
    with card:
        ui.html(f"Suggested session: {group.suggested_session}").classes("text-xs opacity-70 block")
        with ui.element("ul").classes("leaf-list"):
            for member in group.members:
                with ui.element("li"):
                    ui.html(member.name)

        with ui.element("div").classes("flex flex-wrap gap-2 mt-1"):
            ui.button(
                "Mark session complete",
                on_click=lambda group=group: on_mark_complete(group, group.member_keys),
            ).props(f"data-testid=mark-session-complete data-group={group.template_id}").classes(
                "text-xs"
            )
        _member_checklist(group, on_review)


def render(
    groups: Sequence[PracticeGroupRow],
    *,
    on_mark_complete: CompletionHandler,
    on_review: CompletionHandler,
) -> None:
    """The whole view: every stale group not already shown in the primary list (§9.8)."""
    if not groups:
        empty_state("Nothing needs a refresher right now.", testid="practice-freshness-empty")
        return
    for group in groups:
        render_group(group, on_mark_complete=on_mark_complete, on_review=on_review)
