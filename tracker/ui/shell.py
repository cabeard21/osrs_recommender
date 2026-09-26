"""The page shell: design tokens, nav, responsive frame, and the state CSS injection point.

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

**The tokens are the visual language, and they are grounded in the game.** The palette is a
warm stone ramp — the colour of the game's own interface chrome — rather than a neutral
grey one, with parchment-coloured text and the item-name gold used only on the display
face. Dark is the default because that is the condition this app is read in: a phone,
beside a dark game window, often at night. Light is a real second theme rather than an
afterthought, because the same phone gets used outdoors.

Three type roles, and the split is functional rather than decorative. The display face is a
bitmap one, used only at sizes where a bitmap face is crisp — the page title and the stat
figures, nothing smaller. The data face is monospaced because rung positions, prices and
level requirements are tabular and should align down a column. Everything else is the body
face. Between them they replace the five different ``opacity`` values that were previously
doing a type scale's job.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from nicegui import ui

from tracker.ui.states import STATE_CSS


@dataclass(frozen=True, slots=True)
class NavItem:
    """One destination in the nav bar.

    ``primary`` decides which side of the phone-sized split this item falls on, and it is a
    field on the one nav tuple rather than a second list. Two lists would be two places for
    a view to be forgotten — the failure the single tuple exists to prevent — whereas a flag
    cannot omit anything: every item is still rendered, and ``primary`` only decides whether
    a phone shows it in the bar or behind *More*.
    """

    path: str
    label: str
    primary: bool = False


#: One navigation for the factual Account Companion surfaces.
NAV: tuple[NavItem, ...] = (
    NavItem("/", "Dashboard", primary=True),
    NavItem("/unlocks", "Unlocks"),
    NavItem("/gear", "Gear", primary=True),
    NavItem("/skills", "Skills"),
    NavItem("/settings", "Settings"),
)

#: Loaded from Google Fonts with a full system fallback stack behind every role, because
#: this app is reached over Tailscale and the device on the other end may have no route to
#: the public internet. A missing webfont then costs the personality of the page and nothing
#: else — the scale, the weights and the monospaced data column all still hold.
FONT_HTML = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
    "?family=Silkscreen:wght@400;700"
    "&family=IBM+Plex+Sans:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500"
    '&display=swap">'
)

#: The dark ramp — the resting state of this application, for the reason the module docstring
#: gives: a phone, beside a dark game window, often at night.
_DARK_TOKENS = """
  color-scheme: dark;
  --ground:     #17140f;
  --panel:      #211b14;
  --panel-2:    #2b241a;
  --edge:       #3e352a;
  --edge-soft:  #2f281f;
  --ink:        #ded2ba;
  --ink-dim:    #9d917c;
  --ink-faint:  #776c58;
  --gold:       #ffb83f;
  --jade:       #6bd06b;
  --jade-ink:   #0f2a0f;
  --amber:      #e0a83c;
  --amber-ink:  #2a1d05;
  --rust:       #d4623c;
"""

#: The same ramp for daylight. Not an inversion — the accent hues are re-picked rather than
#: lightened, because `--gold` and `--jade` are used as *text* and the dark values would fail
#: against a pale ground at the sizes this application sets them.
_LIGHT_TOKENS = """
  color-scheme: light;
  --ground:     #efe9dc;
  --panel:      #faf6ec;
  --panel-2:    #ebe3d2;
  --edge:       #c6b99e;
  --edge-soft:  #ded3bd;
  --ink:        #2a231a;
  --ink-dim:    #5c5142;
  --ink-faint:  #7c7160;
  --gold:       #8a5c0c;
  --jade:       #276e2c;
  --jade-ink:   #eaf7ea;
  --amber:      #7d5a10;
  --amber-ink:  #fdf3dd;
  --rust:       #9c3c1c;
"""

#: The faces, which do not vary by theme and so are stated once.
_FONT_TOKENS = """
  --font-display: "Silkscreen", ui-monospace, "Courier New", monospace;
  --font-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-data: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
"""

#: The whole palette, three times, and nothing else. Every colour in the application resolves
#: through one of these names, so a theme is this block re-stated rather than a second set of
#: rules scattered across the views.
#:
#: **Three blocks rather than two, because a theme is a choice and not only a device setting.**
#: ``prefers-color-scheme`` on its own is an OS mirror: it serves the reader whose phone
#: already agrees with them and has nothing at all to offer the one whose phone does not. So
#: *auto* stays the default and keeps following the device, and two explicit modes sit beside
#: it.
#:
#: The ``:not([data-theme])`` guard is the whole mechanism. Without it, a device set to light
#: would re-assert itself over a reader who chose dark on every page load, and the control
#: would read as broken rather than as absent. The explicit blocks are stated *after* the
#: media query so they win at equal specificity whatever the device prefers.
TOKENS_CSS = f"""
:root {{{_DARK_TOKENS}{_FONT_TOKENS}}}

@media (prefers-color-scheme: light) {{
  :root:not([data-theme]) {{{_LIGHT_TOKENS}}}
}}

:root[data-theme="light"] {{{_LIGHT_TOKENS}}}
:root[data-theme="dark"] {{{_DARK_TOKENS}}}
"""

#: Applied in ``<head>``, before the body paints.
#:
#: Synchronous and ahead of everything else, deliberately. A theme restored *after* first
#: paint is a white flash on a page whose whole reason for being dark is that it is read at
#: night — and NiceGUI mounts its Vue tree over a websocket, far too late to be the thing
#: that decides what colour the screen starts.
#:
#: The click handler is delegated from ``document`` for the same timing reason: the button it
#: acts on is mounted by Vue long after this script runs, and is re-created on reconnect.
#: Nothing here reads the DOM in order to *display* the current mode — that is done in CSS
#: off ``[data-theme]`` (see :data:`THEME_CSS`), so there is no state to keep in sync and no
#: frame in which the label and the palette disagree.
#:
#: Every ``localStorage`` touch is guarded. It throws outright in a browser with site data
#: blocked, and an exception here would take the theme *and* the click handler down with it.
#: The failure mode when storage is unavailable is that the choice lasts only for the page,
#: which is the most this can honestly promise on such a device.
THEME_SCRIPT_HTML = """
<script>
(function () {
  var KEY = 'tracker-theme';
  var ORDER = ['auto', 'dark', 'light'];

  function read() {
    try { return localStorage.getItem(KEY) || 'auto'; } catch (e) { return 'auto'; }
  }
  function apply(mode) {
    var root = document.documentElement;
    if (mode === 'dark' || mode === 'light') { root.setAttribute('data-theme', mode); }
    else { root.removeAttribute('data-theme'); }
  }

  apply(read());

  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    if (!target.closest('[data-testid=theme-toggle]')) { return; }
    var next = ORDER[(ORDER.indexOf(read()) + 1) % ORDER.length];
    try { localStorage.setItem(KEY, next); } catch (e) { /* lasts this page only */ }
    apply(next);
  });
})();
</script>
"""

#: The theme control: one button, showing the mode it is currently in.
#:
#: All three faces sit in the DOM and CSS reveals one, rather than script rewriting a label.
#: That removes the only race this feature could have had — the palette and the word are
#: driven by the same ``[data-theme]`` attribute, so they cannot disagree even for a frame,
#: including on the reconnect that re-creates the button.
#:
#: The dot is drawn in CSS rather than set as a glyph. ``☾`` and ``☀`` are in neither webfont,
#: so they would fall back to whatever symbol font the device happens to carry and render at a
#: different size and weight on every platform — and this app is reached from a phone over
#: Tailscale, where the webfonts may not resolve at all.
THEME_CSS = """
.theme-toggle {
  display: inline-flex; align-items: center; gap: 0.4rem;
  flex: 0 0 auto; padding: 0.3rem 0.6rem; min-height: 2rem;
  background: none; border: 1px solid var(--edge-soft); border-radius: 999px;
  font-family: var(--font-body); font-size: 0.75rem; font-weight: 500;
  color: var(--ink-dim); cursor: pointer; white-space: nowrap;
}
.theme-toggle:hover { border-color: var(--edge); color: var(--ink); }

.theme-face { display: none; align-items: center; gap: 0.35rem; }
:root:not([data-theme]) .theme-face-auto,
:root[data-theme="dark"] .theme-face-dark,
:root[data-theme="light"] .theme-face-light { display: inline-flex; }

.theme-dot {
  width: 0.6rem; height: 0.6rem; border-radius: 999px; flex: 0 0 auto;
  border: 1px solid currentColor; background: transparent;
}
.theme-face-dark .theme-dot { background: currentColor; }
.theme-face-auto .theme-dot {
  background: linear-gradient(90deg, currentColor 50%, transparent 50%);
}

/* Available to assistive technology, absent from the layout. The button's accessible name is
   its visible face plus this, so it announces both the state and what activating it does —
   neither of which the word "Dark" on its own says. */
.sr-only {
  position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
"""

#: Layout rules that Quasar's utility classes do not cover.
#:
#: ``overflow-wrap: break-word`` is the rule that keeps the 390 px assertion true: capability
#: ids, unlock keys and generated reasons are long unbroken tokens, and a single unbreakable
#: string is the usual cause of a page that scrolls sideways on a phone. It is ``break-word``
#: rather than ``anywhere`` so that ordinary prose is only broken when it would otherwise
#: overflow, instead of at any convenient point in a narrow column; the ``min-width: 0``
#: beside it is what makes that sufficient inside flex and grid children.
LAYOUT_CSS = """
html, body { overflow-x: hidden; }
body {
  background: var(--ground);
  color: var(--ink);
  font-family: var(--font-body);
  -webkit-font-smoothing: antialiased;
}
.tracker-page {
  width: 100%; max-width: 60rem; margin: 0 auto;
  padding: 0.75rem 0.75rem 5.5rem;
}
.tracker-page * { min-width: 0; overflow-wrap: break-word; }

/* The title and the theme control share one line. The control sits here rather than in the
   nav because the nav is a thumb bar with four fixed cells on a phone, and a fifth would
   shrink all of them to buy a switch that is pressed roughly twice in the life of an
   install. Beside the title it is app-wide, quiet, and out of the way of the tap targets
   that actually get used. */
.tracker-titlebar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 0.75rem; margin: 0.25rem 0 0.5rem;
}
.tracker-title {
  font-family: var(--font-display);
  font-size: 1.25rem; line-height: 1.6; font-weight: 400;
  color: var(--gold); letter-spacing: 0.01em;
}
.tracker-figure {
  font-family: var(--font-display);
  font-size: 1.375rem; line-height: 1.5; color: var(--ink);
}
.tracker-data { font-family: var(--font-data); font-size: 0.75rem; color: var(--ink-dim); }
.tracker-dim { color: var(--ink-dim); }
.tracker-faint { color: var(--ink-faint); }

.tracker-card {
  width: 100%; background: var(--panel);
  border: 1px solid var(--edge-soft); border-left: 2px solid var(--edge);
  border-radius: 0.375rem; padding: 0.75rem; margin-bottom: 0.6rem;
}
/* No `text-transform` here, and none on `.layer-label` either. Both classes carry content
   as often as they carry chrome: `section()` is given capability names and gear slots,
   `.layer-label` is given roadmap names in `roadmaps.py` and a whole sentence in
   `advisor.py`. Uppercasing a proper noun or a sentence is a typographic claim about text
   that has not agreed to it — and because CSS case is applied at render, it also silently
   changes what `inner_text()` and some screen readers report. Case transformation is
   reserved for the fixed strings this codebase authors itself: `.cta`, `.goal-eyebrow`
   and `.stat-label`. These two get their label quality from size, weight and colour. */
.tracker-card-title {
  font-size: 0.8125rem; font-weight: 600; letter-spacing: 0.01em;
  color: var(--ink); display: block; margin-bottom: 0.4rem;
}
.tracker-grid { display: grid; grid-template-columns: 1fr; gap: 0.6rem; width: 100%; }
@media (min-width: 40rem) {
  .tracker-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

/* Two columns, on a plain div. Never apply this to a `ui.row()`: Quasar's own
   `display: flex` and this rule have equal specificity, this stylesheet is injected last,
   and the row's children then flow into two grid columns instead of one flex line. */
.layer-row { display: grid; grid-template-columns: minmax(0, 9rem) minmax(0, 1fr);
             gap: 0.4rem; align-items: baseline; font-size: 0.85rem; }
.layer-label { font-size: 0.75rem; font-weight: 500; color: var(--ink-faint); }

/* Quasar components, brought onto the palette.

   Quasar's surfaces ship an opaque white ground and do not inherit one, so every container
   the app puts content inside has to be listed here or it renders as a white sheet on the
   dark theme. This is the whole set the views use; a new Quasar container needs adding to
   it, and the symptom if it is forgotten is unmistakable. */
/* The bar is recoloured on the model and track rather than through `color`, because
   NiceGUI defaults these to `color="primary"` and Quasar's `.text-primary` carries
   `!important` — so the inherited-colour route loses however late this sheet is injected,
   and the bars stayed Quasar blue. `background` is not contested, so it simply wins. */
.q-linear-progress { border-radius: 999px; overflow: hidden; }
.q-linear-progress__model { background: var(--jade); }
.q-linear-progress__track { background: var(--edge-soft); opacity: 1; }
.q-field__native, .q-field__input, .q-item__label { color: var(--ink); }
.q-field__label { color: var(--ink-faint); }
.q-field__native::placeholder, .q-field__input::placeholder { color: var(--ink-faint); }

/* An outlined field draws its resting border on `::before` and its focused one on `::after`,
   and the focused one is `currentColor` under Quasar's `.text-primary` — which is why every
   text box in this app lit up blue the moment it was clicked. Both are recoloured here, once,
   rather than per field: this is the application's one input treatment.

   No `!important` on any of these. Quasar's own border rules are ordinary declarations inside
   its cascade layer, and an unlayered *normal* declaration outranks every layered one — so
   these win as they stand. `!important` would be worse than redundant here: the cascade
   reverses layer order for important declarations, so adding it would drop these below the
   layer they are trying to beat.

   The `::after` rule must stay scoped to `.q-field--focused`. Quasar leaves that border
   transparent at rest and reveals it only on focus, so recolouring it unconditionally rings
   every select and text box on the page in permanent gold — which is precisely what it did. */
.q-field--outlined .q-field__control::before { border-color: var(--edge-soft); }
.q-field--outlined .q-field__control:hover::before { border-color: var(--edge); }
.q-field--outlined.q-field--focused .q-field__control::after { border-color: var(--gold); }
.q-field--outlined .q-field__control { background: var(--panel); border-radius: 0.375rem; }
.q-tab-panels, .q-tab-panel, .q-card, .q-expansion-item__content, .q-expansion-item {
  background: transparent; color: var(--ink);
}
.q-menu, .q-dialog__inner > * {
  background: var(--panel-2); color: var(--ink); border: 1px solid var(--edge);
}
.q-checkbox__label, .q-radio__label { color: var(--ink); font-size: 0.8125rem; }

/* A11y floor: a focus ring that is visible on both themes, and motion that can be
   switched off. Neither existed before, and the advisor is driven from the keyboard. */
:focus-visible {
  outline: 2px solid var(--gold); outline-offset: 2px; border-radius: 2px;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important; scroll-behavior: auto !important;
  }
}
"""

#: The nav, which is one element and two layouts.
#:
#: On a phone it is a fixed bar at the thumb end of the screen carrying the four primary
#: destinations plus *More*; the previous single scrolling row showed about three of eleven
#: links at 390 px with nothing on screen to suggest the other eight existed. From 48 rem
#: every link is inline at the top and *More* is gone, because at that width they all fit.
#: Both layouts render from :data:`NAV`, so neither can omit a view the other has.
NAV_CSS = """
[data-testid=nav] {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 40;
  display: flex; align-items: stretch; gap: 1px;
  background: var(--panel-2); border-top: 1px solid var(--edge);
  padding-bottom: env(safe-area-inset-bottom, 0);
}
.nav-link, .nav-more {
  flex: 1 1 0; min-width: 0; min-height: 3rem;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.1rem; padding: 0.35rem 0.15rem;
  font-size: 0.6875rem; font-weight: 500; line-height: 1.2; text-align: center;
  color: var(--ink-dim); text-decoration: none; background: none; border: 0;
  border-top: 2px solid transparent; cursor: pointer;
}
.nav-link[aria-current=page] {
  color: var(--gold); border-top-color: var(--gold); background: var(--panel);
}
.nav-secondary { display: none; }

@media (min-width: 48rem) {
  [data-testid=nav] {
    position: static; flex-wrap: wrap; gap: 0.15rem;
    background: none; border-top: 0;
    border-bottom: 1px solid var(--edge-soft); padding: 0 0 0.4rem;
  }
  .nav-link {
    flex: 0 0 auto; min-height: 2.25rem; flex-direction: row;
    padding: 0.35rem 0.6rem; font-size: 0.8125rem;
    border-top: 0; border-bottom: 2px solid transparent; border-radius: 0.25rem 0.25rem 0 0;
  }
  .nav-link[aria-current=page] { border-top: 0; border-bottom-color: var(--gold); }
  .nav-secondary { display: contents; }
  .nav-more { display: none; }
  .tracker-page { padding-bottom: 1.5rem; }
}
"""


def inject_styles() -> None:
    """Add the stylesheets, the webfonts and the theme script this application defines."""
    ui.add_head_html(FONT_HTML)
    ui.add_head_html(THEME_SCRIPT_HTML)
    ui.add_css(TOKENS_CSS)
    ui.add_css(LAYOUT_CSS)
    ui.add_css(NAV_CSS)
    ui.add_css(THEME_CSS)
    ui.add_css(STATE_CSS)


def theme_toggle() -> None:
    """The Auto / Dark / Light control.

    A plain ``<button>`` with no Python callback, because there is nothing for the server to
    decide: the choice is a property of *this device* — the same account is read on a phone
    at night and a desktop in daylight, and a server-side preference would force one of those
    two to be wrong. Handling it in the browser also means the switch survives a dropped
    websocket, which the app is reached over Tailscale and therefore does.

    All three faces are rendered and CSS shows the live one; see :data:`THEME_CSS`.
    """
    with ui.element("button").classes("theme-toggle") as button:
        button.props("data-testid=theme-toggle type=button")
        for mode, word in (("auto", "Auto"), ("dark", "Dark"), ("light", "Light")):
            with ui.element("span").classes(f"theme-face theme-face-{mode}"):
                ui.element("span").classes("theme-dot")
                ui.html(word)
        ui.html("theme — activate to change").classes("sr-only")


def _nav_link(item: NavItem, current: str) -> None:
    """One destination, marked current for assistive technology as well as for the eye.

    ``aria-current`` carries the active state and the styling hangs off it, rather than the
    active class being applied independently — one source, so a link cannot look current
    without announcing it, or announce it without looking it.
    """
    link = ui.link(item.label, item.path).classes("nav-link")
    is_current = item.path == current or (item.path != "/" and current.startswith(f"{item.path}/"))
    if is_current:
        link.props("aria-current=page")


def _nav_bar(current: str) -> None:
    """The application's one navigation, rendered for whichever viewport is asking.

    Every item is in the DOM at every width. What changes is where the non-primary ones sit:
    inline from 48 rem, and behind *More* below it. The alternative — a drawer on phones and
    tabs on desktop — means two navigations and therefore two places for a view to be
    forgotten, which is what :data:`NAV` exists to prevent.
    """
    with ui.element("nav").classes("w-full") as element:
        element.props("data-testid=nav aria-label=Views")
        for item in NAV:
            if item.primary:
                _nav_link(item, current)

        with ui.element("span").classes("nav-secondary"):
            for item in NAV:
                if not item.primary:
                    _nav_link(item, current)

        with ui.element("button").classes("nav-more") as more:
            more.props("data-testid=nav-more aria-label=More views")
            ui.html("More")
            with ui.menu().props("data-testid=nav-more-menu"):
                for item in NAV:
                    if item.primary:
                        continue
                    ui.menu_item(
                        item.label, on_click=lambda path=item.path: ui.navigate.to(path)
                    ).props(f"data-nav={item.path}")


@contextmanager
def page(title: str, *, path: str) -> Iterator[None]:
    """Wrap a page body in the shared frame.

    A context manager rather than a decorator taking a render callable, so a page function
    reads top-to-bottom as the markup it produces. ``path`` is passed explicitly instead of
    being read from the request, because the nav highlight is a property of the page being
    built and NiceGUI rebuilds pages outside any request scope on reconnect.

    The nav has moved
    to the foot of a phone screen, so the first thing at the top of the document is now the
    first thing the reader sees, and that should be the name of the view they asked for.

    The theme control shares the title's line on every page, because it is a property of the
    application rather than of any view — putting it on Settings would make the one control
    a reader wants at dusk the one they have to navigate to find.
    """
    inject_styles()
    ui.page_title(f"{title} - OSRS tracker")
    with ui.element("div").classes("tracker-page"):
        _nav_bar(path)
        with ui.element("div").classes("tracker-titlebar"):
            ui.html(title).classes("tracker-title block")
            theme_toggle()
        yield


def empty_state(message: str, *, testid: str = "empty-state") -> None:
    """What a view shows before the first sync.

    Phrased as an instruction, never as a result. "No account data" would be a claim about
    the account; "no sync yet" is a claim about our records, and only the second is true
    (§4.5).
    """
    element = ui.element("div").classes("tracker-card text-sm tracker-dim")
    element.props(f"data-testid={testid}")
    with element:
        ui.html(message)


def section(title: str, *, testid: str | None = None) -> ui.element:
    """A titled card. Returns the container so callers can nest with ``with``."""
    card = ui.element("div").classes("tracker-card")
    if testid is not None:
        card.props(f"data-testid={testid}")
    with card:
        ui.html(title).classes("tracker-card-title")
    return card


def layer_row(label: str, render_value: Callable[[], object]) -> None:
    """One ``label: value`` line of §4.4's three-layer block.

    Factual status fields go through this, so related facts are rows with the
    same visual weight. A layout that gave ``status`` a heading and the other two a
    footnote would be the collapse §4.4 forbids, achieved by typography instead of by data.
    """
    with ui.element("div").classes("layer-row"):
        ui.html(label).classes("layer-label")
        with ui.element("div"):
            render_value()
