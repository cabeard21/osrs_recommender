"""The assertions that genuinely need a DOM (§15).

Everything else about the UI is checked without a browser, in ``test_view_model.py`` and
``test_read_model.py``. What is left here is the set of claims that are only true of rendered
markup:

1. the ``unknown`` and ``locked`` selectors are **disjoint**, in both views;
2. blockers and unknowns are **separate DOM nodes** with different calls to action;
3. an unranked skill's rendered text carries no level;
4. at a 390 px viewport the document does not scroll sideways.

The first is §15's hardest requirement — *"unknown must never render as locked"* — turned
into something assertable. "Visually distinct" is a human judgment; *"these two selectors
return disjoint, non-empty element sets"* is a test. The non-emptiness half matters as much
as the disjointness: two selectors that both match nothing are trivially disjoint, which is
why the seeded account puts an unknown and a locked item on the same page.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from playwright.sync_api import Page, ViewportSize

from tracker.api.router import API_PREFIX

#: The viewport the plan names. A common small-phone width, and narrow enough that a single
#: unbroken capability id or generated reason will overflow it if nothing wraps.
PHONE = ViewportSize(width=390, height=844)


@pytest.fixture
def phone(page: Page) -> Page:
    """A page sized like a phone, since §15 calls the layout phone-first."""
    page.set_viewport_size(PHONE)
    return page


def _open(page: Page, base: str, path: str) -> Page:
    """Navigate and wait for NiceGUI's element tree to arrive.

    NiceGUI delivers the body over a websocket after the initial document, so a bare
    ``goto`` returns a shell with none of the markup under test in it. Waiting on the nav —
    which every page in the shell renders — is what makes these assertions about the page
    rather than about a race.
    """
    page.goto(f"{base}{path}")
    page.wait_for_selector("[data-testid=nav]", timeout=15_000)
    return page


def _classes(page: Page, selector: str) -> set[str]:
    attribute = page.locator(selector).first.get_attribute("class")
    return set((attribute or "").split())


# ---------------------------------------------------------------------------
# §15's hardest rule: unknown is not locked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/capabilities", "/unlocks"])
def test_unknown_and_locked_select_disjoint_elements(
    phone: Page, ui_base_url: str, path: str
) -> None:
    """Both views, because the rule is about the whole UI and not about one page."""
    _open(phone, ui_base_url, path)

    assert phone.locator('[data-state="unknown"]').count() > 0, "no unknown on this page"
    assert phone.locator('[data-state="locked"]').count() > 0, "no locked item on this page"
    assert phone.locator('[data-state="unknown"][data-state="locked"]').count() == 0


@pytest.mark.parametrize("path", ["/capabilities", "/unlocks"])
def test_unknown_and_locked_render_with_different_css_classes(
    phone: Page, ui_base_url: str, path: str
) -> None:
    """The visual half of the same rule, without asking anything about colour.

    Reads the class list off the badges rather than comparing computed styles: a screenshot
    comparison would fail on a font change, and a colour assertion would pass for two
    indistinguishable greys.
    """
    _open(phone, ui_base_url, path)

    unknown_classes = _classes(phone, '.state-badge[data-state="unknown"]')
    locked_classes = _classes(phone, '.state-badge[data-state="locked"]')
    assert "state-unknown" in unknown_classes
    assert "state-locked" in locked_classes
    assert "state-locked" not in unknown_classes
    assert "state-unknown" not in locked_classes


def test_all_four_unlock_states_are_on_screen_together(phone: Page, ui_base_url: str) -> None:
    """§6.3's four states, so the disjointness above is checked against a full house."""
    _open(phone, ui_base_url, "/unlocks")
    for state in ("unlocked", "available", "locked", "unknown"):
        assert phone.locator(f'[data-testid=unlock][data-state="{state}"]').count() > 0, state


# ---------------------------------------------------------------------------
# §15: blockers and unknowns are separate lists with separate calls to action
# ---------------------------------------------------------------------------


def test_blockers_and_unknowns_are_separate_dom_nodes(phone: Page, ui_base_url: str) -> None:
    _open(phone, ui_base_url, "/capabilities")

    assert phone.locator("[data-testid=blockers]").count() > 0
    assert phone.locator("[data-testid=unknowns]").count() > 0

    # Neither may contain the other: nesting would put both lists under one call to action,
    # which is the merge §15 forbids, achieved through the DOM rather than through the data.
    assert phone.locator("[data-testid=blockers] [data-testid=unknowns]").count() == 0
    assert phone.locator("[data-testid=unknowns] [data-testid=blockers]").count() == 0


def test_the_two_lists_carry_different_calls_to_action(phone: Page, ui_base_url: str) -> None:
    """ "Do this" against "sync this" — §15's whole reason for keeping them apart."""
    _open(phone, ui_base_url, "/capabilities")
    blockers_cta = phone.locator("[data-testid=blockers] .cta").first.inner_text()
    unknowns_cta = phone.locator("[data-testid=unknowns] .cta").first.inner_text()
    assert blockers_cta != unknowns_cta
    assert "sync" in unknowns_cta.lower()


def test_three_status_layers_render_as_three_labelled_rows(phone: Page, ui_base_url: str) -> None:
    """§4.4, on screen: never collapsed into one badge."""
    _open(phone, ui_base_url, "/capabilities")
    text = phone.locator("[data-testid=capability]").first.inner_text()
    assert "Status" in text
    assert "Readiness confidence" in text
    assert "Recommended now" in text


# ---------------------------------------------------------------------------
# §6.2: unranked is not level 1
# ---------------------------------------------------------------------------


def test_an_unranked_skill_renders_no_level(phone: Page, ui_base_url: str) -> None:
    """The seeded account's Construction row stores ``level = 1`` and ``xp = NULL``.

    Asserted as "no digits at all" rather than as "not the token 1": a future formatting
    change rendering ``01`` or ``lvl 1`` would slip past the narrower check while committing
    exactly the error §15 names.
    """
    _open(phone, ui_base_url, "/skills")
    row = phone.locator('[data-testid=skill][data-ranked="false"]').first
    text = row.inner_text()
    assert "unranked" in text.lower()
    assert not any(character.isdigit() for character in text)


def test_a_ranked_skill_still_shows_its_level(phone: Page, ui_base_url: str) -> None:
    """The complement, so the test above cannot be satisfied by rendering nothing."""
    _open(phone, ui_base_url, "/skills")
    text = phone.locator('[data-testid=skill][data-ranked="true"]').first.inner_text()
    assert "94" in text


# ---------------------------------------------------------------------------
# §15: mobile-first
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/capabilities", "/unlocks", "/skills"])
def test_no_horizontal_scroll_at_390px(phone: Page, ui_base_url: str, path: str) -> None:
    """Every view, not a sample: the layout is shared but the content that overflows is not.

    Capability ids, unlock keys and generated reasons are long unbroken tokens, and a single
    unbreakable string is the usual cause of a page that scrolls sideways on a phone.
    """
    _open(phone, ui_base_url, path)
    overflow = phone.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"{path} overflows its viewport by {overflow}px at 390px"


def test_the_dashboard_shows_the_persisted_reason(phone: Page, ui_base_url: str) -> None:
    """§9.5's "Why" line is read from storage, never recomposed in the UI."""
    _open(phone, ui_base_url, "/")
    text = phone.locator("[data-testid=goal-reason]").inner_text()
    assert "high PvP value (+0.61)" in text


# ---------------------------------------------------------------------------
# §5 — one process, one port
# ---------------------------------------------------------------------------


def test_the_ui_and_the_api_answer_on_one_port(page: Page, ui_base_url: str, app: FastAPI) -> None:
    """§5: *"the UI and the sync API are one process on one port. There is no second
    service."*

    Asserted here rather than in ``tests/test_app.py`` because it needs a *mounted* UI, and
    NiceGUI allows one of those per interpreter — this package owns it. The API surface and
    the pages are checked against the same running server: the sync endpoint answers (401,
    since no token is sent — §11.2), health answers, and the dashboard renders, all on one
    origin.
    """
    assert f"{API_PREFIX}/sync" in set(app.openapi()["paths"])

    assert page.request.get(f"{ui_base_url}/healthz").status == 200
    assert page.request.post(f"{ui_base_url}{API_PREFIX}/sync", data={}).status == 401
    _open(page, ui_base_url, "/")
    assert page.locator("[data-testid=character-summary]").count() == 1
