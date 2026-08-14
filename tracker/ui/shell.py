"""The page shell: nav, responsive frame, and the one place the state CSS is injected.

**Mobile-first, not mobile-adapted** (§15: *"reached over Tailscale; responsive, phone-first
layout"*). Every container here is fluid by default and gains structure at wider viewports
rather than the other way round. That ordering is the whole reason this module exists as a
frame the pages fill in: a desktop layout retrofitted for phones acquires a horizontal
scrollbar somewhere, and the place a fixed width tends to survive is the chrome —
navigation, headers, tables — not the content.

The state stylesheet is added here, once per page, rather than by the badge component. A
component that injected CSS on every call would emit it once per badge; NiceGUI would
deduplicate it, but the ownership would be wrong — these classes are a property of the
application's visual language (§15), not of any one element.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from nicegui import ui

from tracker.ui.components import roadmap_selector
from tracker.ui.components.badges import CONFIDENCE_CSS
from tracker.ui.states import STATE_CSS
from tracker.ui.view_model import RoadmapSelectorModel


@dataclass(frozen=True, slots=True)
class NavItem:
    """One destination in the nav bar."""

    path: str
    label: str


#: Step 10's four views, plus Step 11's five. Added to this one tuple rather than to a
#: second nav, so there is one answer to "what can this app show me".
NAV: tuple[NavItem, ...] = (
    NavItem("/", "Dashboard"),
    NavItem("/capabilities", "Capabilities"),
    NavItem("/unlocks", "Unlocks"),
    NavItem("/skills", "Skills"),
    NavItem("/recommendations", "Recommendations"),
    NavItem("/advisor", "Advisor"),
    NavItem("/practice", "Practice"),
    NavItem("/roadmaps", "Roadmaps"),
    NavItem("/settings", "Settings"),
    NavItem("/history", "History"),
)

#: Layout rules that Quasar's utility classes do not cover. The ``overflow-wrap`` rule is
#: the one that keeps the 390 px assertion true: capability ids, unlock keys and generated
#: reasons are long unbroken tokens, and a single unbreakable string is the usual cause of
#: a page that scrolls sideways on a phone.
LAYOUT_CSS = """
html, body { overflow-x: hidden; }
.tracker-page { width: 100%; max-width: 60rem; margin: 0 auto; padding: 0.75rem; }
.tracker-page * { min-width: 0; overflow-wrap: anywhere; }
.tracker-card {
  width: 100%; border: 1px solid rgba(127, 127, 127, 0.3);
  border-radius: 0.5rem; padding: 0.75rem; margin-bottom: 0.6rem;
}
.tracker-grid { display: grid; grid-template-columns: 1fr; gap: 0.6rem; width: 100%; }
@media (min-width: 40rem) {
  .tracker-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.layer-row { display: grid; grid-template-columns: minmax(0, 9rem) minmax(0, 1fr);
             gap: 0.4rem; align-items: baseline; font-size: 0.85rem; }
.layer-label { opacity: 0.65; }
"""


def inject_styles() -> None:
    """Add the three stylesheets this application defines."""
    ui.add_css(LAYOUT_CSS)
    ui.add_css(STATE_CSS)
    ui.add_css(CONFIDENCE_CSS)


def _nav_bar(current: str) -> None:
    """A single scrollable row of links at every viewport.

    One nav rather than a drawer on phones and tabs on desktop: two navigations mean two
    places for a Step 11 view to be forgotten, and the row is short enough that scrolling
    it is cheaper than maintaining both.
    """
    with ui.element("nav").classes("w-full flex flex-nowrap gap-1 overflow-x-auto py-1") as element:
        element.props("data-testid=nav")
        for item in NAV:
            active = "font-bold underline" if item.path == current else "opacity-70"
            ui.link(item.label, item.path).classes(f"px-2 py-1 text-sm no-underline {active}")


@contextmanager
def page(title: str, *, path: str, roadmap: RoadmapSelectorModel | None = None) -> Iterator[None]:
    """Wrap a page body in the shared frame.

    A context manager rather than a decorator taking a render callable, so a page function
    reads top-to-bottom as the markup it produces. ``path`` is passed explicitly instead of
    being read from the request, because the nav highlight is a property of the page being
    built and NiceGUI rebuilds pages outside any request scope on reconnect.

    ``roadmap`` arrives as an already-read model with an already-bound callback, because
    this module opens no session and knows no read model — :mod:`tracker.ui.pages` builds
    it. ``None`` draws no selector, which is what a page with no player row gets: a
    dropdown before the first sync would imply a choice that has nothing to choose for
    (§4.5).
    """
    inject_styles()
    ui.page_title(f"{title} - OSRS tracker")
    with ui.element("div").classes("tracker-page"):
        _nav_bar(path)
        if roadmap is not None:
            roadmap_selector.render(roadmap)
        ui.html(title).classes("text-xl font-semibold mt-1 mb-2 block")
        yield


def empty_state(message: str, *, testid: str = "empty-state") -> None:
    """What a view shows before the first sync.

    Phrased as an instruction, never as a result. "No capabilities" would be a claim about
    the account; "no sync yet" is a claim about our records, and only the second is true
    (§4.5).
    """
    element = ui.element("div").classes("tracker-card text-sm opacity-75")
    element.props(f"data-testid={testid}")
    with element:
        ui.html(message)


def section(title: str, *, testid: str | None = None) -> ui.element:
    """A titled card. Returns the container so callers can nest with ``with``."""
    card = ui.element("div").classes("tracker-card")
    if testid is not None:
        card.props(f"data-testid={testid}")
    with card:
        ui.html(title).classes("text-sm font-semibold opacity-80 block mb-1")
    return card


def layer_row(label: str, render_value: Callable[[], object]) -> None:
    """One ``label: value`` line of §4.4's three-layer block.

    Every capability field goes through this, so the three layers are three rows with the
    same visual weight. A layout that gave ``status`` a heading and the other two a
    footnote would be the collapse §4.4 forbids, achieved by typography instead of by data.
    """
    with ui.element("div").classes("layer-row"):
        ui.html(label).classes("layer-label")
        with ui.element("div"):
            render_value()
