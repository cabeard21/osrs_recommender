"""The small pieces every status-bearing element is built from.

There is exactly one function that renders a state (:func:`state_badge`) and exactly one
that renders a leaf list (:func:`leaf_list`). That is deliberate. §15's rule — *"unknown
must never render as locked"* — is a property of the whole UI, and a property of the whole
UI can only be guaranteed by a single implementation. Four views each writing their own
badge would satisfy it four times and then stop satisfying it on the fifth.

Each badge emits both a ``data-state`` attribute and the class
:data:`~tracker.ui.states.STATE_CLASSES` assigns, so the distinction survives into the DOM
and is assertable by selector rather than by eye.
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from tracker.domain.types import Confidence
from tracker.ui.states import STATE_CLASSES, STATE_LABELS, UiState, state_props
from tracker.ui.view_model import LeafRow

#: Marker classes for the confidence chip. Confidence is an ordered scale (§6.9), so unlike
#: the state vocabulary these *are* meant to read as points on one axis.
CONFIDENCE_CLASSES = {
    Confidence.HIGH: "confidence-high",
    Confidence.MEDIUM: "confidence-medium",
    Confidence.LOW: "confidence-low",
}

#: Confidence resolves through the palette tokens rather than through its own hexadecimals,
#: so it inverts with the theme. The previous pastel fills were light-mode-only and became
#: three glowing blocks on a dark ground.
#:
#: Unlike the state vocabulary these still read as one axis, because they *are* one: §6.9's
#: confidence is ordered, so a low chip being louder than a high one is correct here — it is
#: the reading that most deserves a second look.
CONFIDENCE_CSS = """
.confidence-chip {
  display: inline-flex; align-items: center;
  padding: 0.05rem 0.4rem; border-radius: 0.2rem;
  font-family: var(--font-data);
  font-size: 0.6875rem; font-weight: 500; letter-spacing: 0.01em;
  border: 1px solid transparent;
}
.confidence-high   { color: var(--jade); border-color: var(--edge); }
.confidence-medium { color: var(--amber); border-color: var(--amber); }
.confidence-low    { color: var(--rust); border-color: var(--rust); }
.leaf-list { list-style: none; margin: 0; padding: 0; }
.leaf-list li {
  padding: 0.2rem 0 0.2rem 0.7rem; font-size: 0.8125rem;
  border-left: 1px solid var(--edge-soft);
}
.cta {
  font-size: 0.6875rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.07em; color: var(--ink-faint); display: block; margin-bottom: 0.2rem;
}
"""


def state_badge(state: UiState, *, label: str | None = None) -> ui.element:
    """One state pill, carrying ``data-state`` and exactly one state class.

    ``label`` overrides the default word for capabilities, whose §4.4 ``status`` is spelled
    ``unlocked | locked | unknown`` rather than in the unlock view's vocabulary. The
    *state* is unchanged either way — only the word — so overriding the label cannot make
    an unknown thing render as a locked one.
    """
    text = label if label is not None else STATE_LABELS[state]
    element = ui.element("span").classes(f"state-badge {STATE_CLASSES[state]}")
    element.props(state_props(state))
    with element:
        ui.html(text)
    return element


def confidence_chip(confidence: Confidence, *, prefix: str = "") -> ui.element:
    """§8.4's marker. Emits ``data-confidence`` so Step 11 can assert on it.

    Rendered for every level including ``high``, even though §8.4 only requires that
    *below* high be distinguished. An absent chip and a high-confidence chip would look the
    same, so a page that forgot the chip entirely would be indistinguishable from one that
    deliberately showed confidence — and the omission is the failure §8.4 is about.
    """
    element = ui.element("span").classes(f"confidence-chip {CONFIDENCE_CLASSES[confidence]}")
    element.props(f"data-confidence={confidence.name.lower()}")
    with element:
        ui.html(f"{prefix}{confidence.name.lower()}")
    return element


def leaf_list(leaves: Sequence[LeafRow], *, testid: str, cta: str, empty: str) -> ui.element:
    """One of §15's two lists, in its own DOM node with its own call to action.

    ``testid`` is required rather than optional because the separation of blockers from
    unknowns is checked by selector: two lists that render identically but for their
    contents are one merged list as far as a reader is concerned, and §15 is explicit that
    they demand different actions.

    The empty state renders the container anyway. Collapsing it would make "nothing is
    blocking this" and "we have not looked" the same absence on screen, which is the §4.5
    error the whole model exists to prevent.
    """
    container = ui.element("div").classes("w-full")
    container.props(f"data-testid={testid}")
    with container:
        ui.html(cta).classes("cta")
        if not leaves:
            ui.html(empty).classes("text-xs tracker-faint")
            return container
        with ui.element("ul").classes("leaf-list"):
            for leaf in leaves:
                with ui.element("li"):
                    ui.html(leaf.description or leaf.key)
    return container


def unknown_card(message: str, *, testid: str = "unknown-card") -> ui.element:
    """The "we have not looked" panel — hatched, and never phrased as a negative result.

    Shares :data:`~tracker.ui.states.STATE_CLASSES`'s ``unknown`` class with every other
    unknown element in the app, so it is caught by the same disjointness assertion rather
    than being a second, unchecked way of saying the same thing.
    """
    card = ui.element("div").classes(
        f"state-badge {STATE_CLASSES[UiState.UNKNOWN]} w-full justify-start"
    )
    card.props(f"{state_props(UiState.UNKNOWN)} data-testid={testid}")
    with card:
        ui.html(message)
    return card


def staleness_note(message: str) -> ui.element:
    """A §6.5 sentence, already phrased by :mod:`tracker.ui.staleness`.

    Takes the finished string rather than the container and timestamp on purpose: the
    phrasing rule lives in one pure module that can be tested without NiceGUI, and a
    component free to compose its own sentence would be a second place for it to be got
    wrong.
    """
    element = ui.element("p").classes("text-xs tracker-dim m-0")
    element.props("data-testid=staleness-note")
    with element:
        ui.html(message)
    return element
