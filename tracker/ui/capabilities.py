"""The headline view — *"what can I actually do today?"* (§15).

Everything here exists to keep §4.4's three layers apart on screen:

* ``status`` renders as a state badge, from the same single implementation the unlocks view
  uses, so ``unknown`` cannot pick up ``locked``'s treatment in one view and not the other;
* ``readiness_confidence`` renders on its own row, as an em dash when the layer does not
  apply — never as "low", which would be a measurement we did not make;
* ``recommended_now`` renders with the engine's own reason.

There is no summary badge, and adding one later would be the mistake §4.4 names: *"collapsing
any two of these produces either backward progress or false confidence."* It is also why this
page has no filter that hides "not recommended" capabilities — a reader may collapse the
layers in their head, but only if all three were shown to them first.

Blockers and unknowns are separate lists with different ``data-testid``s and different CTAs,
per §15's *"separate lists with separate calls to action"*. They are never concatenated and
never merged into one severity-sorted list: "do this" and "sync this" are different requests,
and a merged list can only carry one verb.

**That same rule is what produces a third list.** A self-attested milestone is unknown for
want of a *prompt*, not for want of a sync (§6.6, A7) — so "Sync RuneLite to find out" is an
instruction that cannot succeed however many times it is followed. The unknowns list was
carrying two verbs, and :func:`split_unknowns` separates them rather than rewording the CTA
into something vague enough to cover both.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from nicegui import ui

from tracker.ui.components.badges import leaf_list, state_badge
from tracker.ui.shell import layer_row, section
from tracker.ui.states import UiState
from tracker.ui.view_model import (
    BLOCKERS_CTA,
    NO_BLOCKERS,
    NO_QUESTIONS,
    NO_UNKNOWNS,
    QUESTIONS_CTA,
    UNKNOWNS_CTA,
    CapabilityRow,
    LeafRow,
)

#: Bound by the caller to a write that opens its own session, as on the Practice view: the
#: page's read session has closed by the time a button is clicked.
AttestHandler = Callable[[LeafRow, bool], None]

#: The order capabilities are listed in. Unknown first, deliberately: §15 treats unknown as
#: a call to action ("sync RuneLite"), and an actionable item at the bottom of a list is an
#: item that never gets acted on. Within a state, the closest to unlocked comes first.
_STATE_ORDER = {
    UiState.UNKNOWN: 0,
    UiState.UNLOCKED: 1,
    UiState.AVAILABLE: 2,
    UiState.LOCKED: 3,
}


def sort_rows(rows: Sequence[CapabilityRow]) -> tuple[CapabilityRow, ...]:
    """Order for display. Pure, so the ordering policy is testable without a browser."""
    return tuple(
        sorted(rows, key=lambda row: (_STATE_ORDER[row.state], -row.unlock_fraction, row.name))
    )


def split_unknowns(leaves: Sequence[LeafRow]) -> tuple[tuple[LeafRow, ...], tuple[LeafRow, ...]]:
    """Unknowns a sync can resolve, and unknowns only the user can (§6.6, A7).

    Splitting on ``leaf_type == "milestone"`` alone is sufficient, and the reason is worth
    recording because it looks incomplete: a *derived* milestone never resolves ``unknown``.
    :meth:`tracker.progression.evaluate.Evaluator._milestone` returns ``unsatisfied`` for a
    missing derived row — a counter that has not reached its threshold is a measurement, not
    an unanswered question. So every milestone leaf that reaches an unknowns list is one the
    user can be asked about, and no content lookup is needed here to prove it.

    Pure, for :func:`sort_rows`'s reason: which verb a leaf gets is a policy worth testing
    without a browser.
    """
    questions = tuple(leaf for leaf in leaves if leaf.leaf_type == "milestone")
    sync = tuple(leaf for leaf in leaves if leaf.leaf_type != "milestone")
    return sync, questions


def _question_list(leaves: Sequence[LeafRow], on_attest: AttestHandler) -> None:
    """§15's third list: each unanswered milestone with Yes and No beside it.

    Both answers are buttons, and neither is preselected. "No" is a real write, not a
    dismissal — it moves the leaf from ``unknown`` to ``unsatisfied``, which is the
    difference between *"we should ask"* and *"you cannot do this yet"* (§4.5). Offering
    only "Yes" would leave the honest negative answer unsayable, and the leaf would keep
    asking forever.
    """
    container = ui.element("div").classes("w-full")
    container.props(f"data-testid=questions data-count={len(leaves)}")
    with container:
        ui.html(QUESTIONS_CTA).classes("cta")
        if not leaves:
            ui.html(NO_QUESTIONS).classes("text-xs opacity-60")
            return
        with ui.element("ul").classes("leaf-list"):
            for leaf in leaves:
                with ui.element("li").props(f"data-milestone={leaf.key}"):
                    ui.html(leaf.description or leaf.key)
                    with ui.element("span").classes("flex gap-1 ml-2"):
                        ui.button("Yes", on_click=lambda leaf=leaf: on_attest(leaf, True)).props(
                            f"data-testid=attest-yes data-milestone={leaf.key}"
                        ).classes("text-xs")
                        ui.button(
                            "Not yet", on_click=lambda leaf=leaf: on_attest(leaf, False)
                        ).props(f"data-testid=attest-no data-milestone={leaf.key}").classes(
                            "text-xs"
                        )


def render_capability(row: CapabilityRow, *, on_attest: AttestHandler) -> None:
    """One capability card: name, progress, three layers, then the three lists."""
    card = section(row.name, testid="capability")
    card.props(f"data-capability={row.capability_id}")
    with card:
        ui.linear_progress(row.unlock_fraction, show_value=False, size="6px").props(
            f"data-testid=unlock-fraction data-fraction={row.unlock_fraction:.4f}"
        )

        layer_row("Status", lambda: state_badge(row.state, label=row.status_label))
        layer_row("Readiness confidence", lambda: ui.html(row.readiness_label))
        layer_row("Recommended now", lambda: ui.html(row.recommended_label))

        for warning in row.warnings:
            # §6.9 attaches warnings to readiness, not to status. They render under the
            # layer block rather than inside the readiness row so that a capability with
            # five warnings cannot push the third layer off a phone screen.
            ui.html(warning).classes("text-xs opacity-70 block")

        sync_unknowns, questions = split_unknowns(row.unknowns)
        with ui.element("div").classes("tracker-grid mt-2"):
            leaf_list(row.blockers, testid="blockers", cta=BLOCKERS_CTA, empty=NO_BLOCKERS)
            leaf_list(sync_unknowns, testid="unknowns", cta=UNKNOWNS_CTA, empty=NO_UNKNOWNS)
            _question_list(questions, on_attest)


def render(rows: Sequence[CapabilityRow], *, on_attest: AttestHandler) -> None:
    """The whole view.

    Takes rows rather than a session: the page function opens the session, and this stays a
    pure function of its input so both the ordering and the markup can be exercised without
    a database.
    """
    for row in sort_rows(rows):
        render_capability(row, on_attest=on_attest)
