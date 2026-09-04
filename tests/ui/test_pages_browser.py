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

from typing import Any

import pytest
from fastapi import FastAPI
from playwright.sync_api import Page, ViewportSize

from tracker.api.router import API_PREFIX
from tracker.integrations.llm.types import LlmRefused, LlmUnavailable
from tracker.sync.advisor import AdvisorThrottled
from tracker.ui.shell import NAV
from tracker.ui.view_model import BLOCKERS_CTA

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

    ``document.fonts.ready`` is the second half of the same argument. The shell loads three
    webfonts, and a page measured between the fallback metrics and the real ones is being
    measured mid-reflow — which surfaced exactly as that would be expected to: as a width
    assertion that failed under some orderings of this module and not others.
    """
    page.goto(f"{base}{path}")
    page.wait_for_selector("[data-testid=nav]", timeout=15_000)
    page.evaluate("() => document.fonts.ready")
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
# §15: the theme control
# ---------------------------------------------------------------------------


def _ground(page: Page) -> str:
    """The page's actual background, which is what "the theme changed" means to a reader."""
    return page.evaluate("() => getComputedStyle(document.body).backgroundColor")


def test_the_theme_control_cycles_auto_dark_light(phone: Page, ui_base_url: str) -> None:
    """Three states, not two.

    A plain dark/light switch cannot express *follow the device*, which is the default and the
    setting most readers should stay on. Asserting the whole cycle — including that it returns
    to auto — is what stops a later edit quietly reducing this to a boolean.
    """
    _open(phone, ui_base_url, "/")
    phone.evaluate("() => localStorage.removeItem('tracker-theme')")
    _open(phone, ui_base_url, "/")

    toggle = phone.locator("[data-testid=theme-toggle]").first
    assert phone.evaluate("() => document.documentElement.hasAttribute('data-theme')") is False

    toggle.click()
    assert phone.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark"
    toggle.click()
    assert phone.evaluate("() => document.documentElement.getAttribute('data-theme')") == "light"
    toggle.click()
    assert phone.evaluate("() => document.documentElement.hasAttribute('data-theme')") is False


def test_choosing_a_theme_repaints_the_page(phone: Page, ui_base_url: str) -> None:
    """The attribute is the mechanism; the ground colour is the promise.

    Asserting only that ``data-theme`` flips would pass just as happily if the two token
    blocks were identical — which is how this would most plausibly break, since the tokens
    and the switch live in different constants.
    """
    _open(phone, ui_base_url, "/")
    phone.evaluate("() => localStorage.setItem('tracker-theme', 'dark')")
    _open(phone, ui_base_url, "/")
    dark = _ground(phone)

    phone.locator("[data-testid=theme-toggle]").first.click()

    assert _ground(phone) != dark, f"both themes painted the same ground: {dark}"


def test_a_chosen_theme_survives_a_reload(phone: Page, ui_base_url: str) -> None:
    """And beats the device, which is the whole reason the control exists.

    The test browser reports ``prefers-color-scheme: light``, so a stored *dark* that survives
    a load is also proof the ``:not([data-theme])`` guard holds — without it the media query
    would re-assert the device's preference every time and the control would read as broken.
    """
    _open(phone, ui_base_url, "/")
    phone.evaluate("() => localStorage.setItem('tracker-theme', 'dark')")

    _open(phone, ui_base_url, "/advisor")
    assert phone.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark"
    dark = _ground(phone)

    phone.evaluate("() => localStorage.setItem('tracker-theme', 'light')")
    _open(phone, ui_base_url, "/advisor")

    assert _ground(phone) != dark


def test_every_page_offers_the_theme_control(phone: Page, ui_base_url: str) -> None:
    """It belongs to the application, so it is not somewhere a reader has to navigate to."""
    for item in NAV:
        _open(phone, ui_base_url, item.path)
        assert phone.locator("[data-testid=theme-toggle]").count() == 1, item.path


# ---------------------------------------------------------------------------
# §15: mobile-first
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/capabilities",
        "/unlocks",
        "/gear",
        "/skills",
        "/recommendations",
        "/practice",
        "/roadmaps",
        "/roadmaps/pvm-ladder",
        "/settings",
        "/history",
    ],
)
def test_no_horizontal_scroll_at_390px(phone: Page, ui_base_url: str, path: str) -> None:
    """Every view, not a sample: the layout is shared but the content that overflows is not.

    Capability ids, unlock keys and generated reasons are long unbroken tokens, and a single
    unbreakable string is the usual cause of a page that scrolls sideways on a phone.

    ``/gear`` was missing from this list, which is the page most able to overflow: it is the
    densest, it carries item names beside two badges and a price on one line, and it is the
    one whose layout was actually broken — a grid rule colliding with a flex row, wrapping
    every rung across three lines. The one view not covered here was the one that needed it.
    """
    _open(phone, ui_base_url, path)
    overflow = phone.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"{path} overflows its viewport by {overflow}px at 390px"


def test_no_element_is_both_a_flex_row_and_the_layer_grid(phone: Page, ui_base_url: str) -> None:
    """The gear page's original defect, generalised into a rule the whole app is held to.

    ``.layer-row`` sets ``display: grid`` with two columns and Quasar's ``.nicegui-row``
    sets ``display: flex``. They have equal specificity and the application stylesheet is
    injected last, so an element carrying both silently becomes a two-column grid and every
    child past the second wraps onto a new line. Nothing about the source looks wrong —
    both classes are individually correct and the call reads as an ordinary styled row — so
    this is not catchable by review, only by asserting the two never co-occur.

    It cost the gear page three lines per rung, which at five rungs a slot is most of a
    phone screen for one piece of equipment.
    """
    for path in ("/gear", "/capabilities", "/recommendations", "/settings", "/roadmaps"):
        _open(phone, ui_base_url, path)
        assert phone.locator(".nicegui-row.layer-row").count() == 0, path


def test_a_gear_slot_draws_each_rung_once_and_marks_at_most_one_best(
    phone: Page, ui_base_url: str
) -> None:
    """The ladder is an ordered set, so a rung appears on it exactly once.

    The four source fields overlap by design — the rung you hold is frequently also the best
    you can equip — and the previous layout drew the overlap twice under two headings, which
    reads as a distinction and sends the reader looking for one that is not there.
    """
    _open(phone, ui_base_url, "/gear")
    slot = phone.locator("[data-testid^=gear-slot-]").first
    rungs = slot.locator("[data-testid=gear-rung]")

    assert rungs.count() > 0, "no rungs rendered, so this asserts nothing"
    tiers = [rungs.nth(i).get_attribute("data-tier") for i in range(rungs.count())]
    assert len(tiers) == len(set(tiers)), tiers
    # Descending: the ladder is drawn as one, top rung first.
    assert tiers == sorted(tiers, key=lambda tier: -int(tier or 0))
    # "Best you can equip" is a single answer, so it cannot mark two rungs of one slot.
    assert slot.locator('[data-testid=gear-rung][data-role*="best"]').count() <= 1


def test_the_dashboard_shows_the_persisted_reason(phone: Page, ui_base_url: str) -> None:
    """§9.5's "Why" line is read from storage, never recomposed in the UI."""
    _open(phone, ui_base_url, "/")
    text = phone.locator("[data-testid=goal-reason]").inner_text()
    assert "high PvP value (+0.61)" in text


# ---------------------------------------------------------------------------
# Step 11 — Recommendations: G10 and the confidence marker (§8.4, §9.8)
# ---------------------------------------------------------------------------


def test_the_recommendations_page_shows_the_persisted_reason_and_confidence(
    phone: Page, ui_base_url: str
) -> None:
    _open(phone, ui_base_url, "/recommendations")
    text = phone.locator("[data-testid=recommendation-reason]").first.inner_text()
    assert "high PvP value (+0.61)" in text
    # §8.4: the seeded top entry is `medium` confidence, which must carry the marker.
    assert phone.locator('[data-confidence="medium"]').count() > 0


def test_at_most_one_refresher_renders_in_the_primary_list(phone: Page, ui_base_url: str) -> None:
    """G10, on the actual DOM: the seed triggers two practice groups (§9.8)."""
    _open(phone, ui_base_url, "/recommendations")
    assert phone.locator('[data-testid=recommendation][data-kind="refresher"]').count() == 1


def test_blocked_candidates_render_in_their_own_collapsed_section(
    phone: Page, ui_base_url: str
) -> None:
    _open(phone, ui_base_url, "/recommendations")
    assert phone.locator("[data-testid=blocked-section]").count() == 1
    # Never mixed into the ranked list (§16.2).
    assert (
        phone.locator("[data-testid=recommendation] [data-testid=blocked-candidate]").count() == 0
    )


# ---------------------------------------------------------------------------
# Step 11 — Practice freshness: the rest of G10's split (§9.8)
# ---------------------------------------------------------------------------


def test_the_seed_accounts_second_stale_group_lives_in_practice_freshness(
    phone: Page, ui_base_url: str
) -> None:
    """The seed triggers two groups; one is the primary list's refresher, the other lands
    here — never both places at once."""
    _open(phone, ui_base_url, "/practice")
    groups = phone.locator('[data-testid="practice-group"]')
    assert groups.count() >= 1
    ids = {groups.nth(i).get_attribute("data-group") for i in range(groups.count())}
    assert "refresh_nh_fundamentals" not in ids
    assert "refresh_vengeance_fundamentals" in ids


def test_mark_session_complete_and_review_individual_skills_are_distinct_controls(
    phone: Page, ui_base_url: str
) -> None:
    """§9.8: two separate actions, never one tap standing in for both."""
    _open(phone, ui_base_url, "/practice")
    assert phone.locator("[data-testid=mark-session-complete]").count() >= 1
    assert phone.locator("[data-testid=review-individual]").count() >= 1
    assert phone.locator("[data-testid=review-skill-checkbox]").count() >= 1


# ---------------------------------------------------------------------------
# Step 11 — Settings: user language only (§9.6)
# ---------------------------------------------------------------------------


def test_settings_never_says_kappa_or_gp_sensitivity(phone: Page, ui_base_url: str) -> None:
    _open(phone, ui_base_url, "/settings")
    text = phone.locator("body").inner_text()
    assert "κ" not in text
    assert "kappa" not in text.lower()
    assert "gp sensitivity" not in text.lower()
    assert "How strongly should expensive upgrades be deprioritized?" in text


def test_settings_shows_token_presence_never_its_value(phone: Page, ui_base_url: str) -> None:
    _open(phone, ui_base_url, "/settings")
    presence = phone.locator("[data-testid=token-presence]")
    assert presence.get_attribute("data-present") == "true"
    assert "ui-test-token-1234567890" not in phone.locator("body").inner_text()


# ---------------------------------------------------------------------------
# Step 11 — Roadmaps: writes to ActiveRoadmap, never a hardcoded selection (A13)
# ---------------------------------------------------------------------------


def test_the_roadmap_selector_shows_the_players_live_selection(
    phone: Page, ui_base_url: str
) -> None:
    _open(phone, ui_base_url, "/roadmaps")
    assert phone.locator("[data-testid=primary-roadmap-radio]").count() == 1
    assert phone.locator("[data-testid=secondary-roadmap-checkbox]").count() >= 1
    # The page's own control and the header selector coexist: the header offers §4.3's one
    # choice, the page offers the weighting exercise. Both write through the same handler.
    assert phone.locator("[data-testid=global-roadmap-select]").count() == 1


def test_the_roadmaps_page_links_to_the_granular_pvm_ladder(phone: Page, ui_base_url: str) -> None:
    _open(phone, ui_base_url, "/roadmaps")

    link = phone.locator("[data-testid=pvm-ladder-link]")
    assert link.count() == 1
    assert link.get_attribute("href") == "/roadmaps/pvm-ladder"


def test_the_pvm_ladder_marks_roadmaps_as_the_current_view(phone: Page, ui_base_url: str) -> None:
    _open(phone, ui_base_url, "/roadmaps/pvm-ladder")

    roadmaps_link = phone.locator('[data-testid=nav] a[href="/roadmaps"]')
    assert roadmaps_link.get_attribute("aria-current") == "page"


def test_the_pvm_ladder_renders_the_complete_attributed_guide(
    phone: Page, ui_base_url: str
) -> None:
    _open(phone, ui_base_url, "/roadmaps/pvm-ladder")

    summary = phone.locator("[data-testid=bossing-summary]")
    assert summary.count() == 1
    assert "Ready" in summary.inner_text()
    assert "Building toward" in summary.inner_text()
    assert phone.locator("[data-testid=bossing-closest-next]").count() == 1

    tiers = phone.locator("[data-testid=bossing-tier]")
    assert tiers.count() == 6
    assert phone.locator("[data-testid=bossing-preparation]").count() > 0
    assert phone.locator("[data-testid=bossing-encounter]").count() == 71
    assert phone.locator("[data-testid=bossing-mechanics]").count() == 71
    assert phone.locator("[data-testid=bossing-rewards]").count() == 71

    source = phone.locator("[data-testid=bossing-source]")
    assert source.count() == 1
    assert "Old School RuneScape Wiki" in source.inner_text()
    assert "oldid=15319480" in (source.get_attribute("href") or "")


def test_the_pvm_ladder_keeps_blockers_and_sync_needed_facts_distinct(
    phone: Page, ui_base_url: str
) -> None:
    _open(phone, ui_base_url, "/roadmaps/pvm-ladder")

    assert phone.locator("[data-testid=bossing-blockers]").count() > 0
    assert phone.locator("[data-testid=bossing-unknowns]").count() > 0
    assert "Sync needed" in phone.locator("[data-testid=bossing-unknowns]").first.inner_text()


@pytest.mark.parametrize("path", [item.path for item in NAV])
def test_the_roadmap_selector_is_on_every_page(phone: Page, ui_base_url: str, path: str) -> None:
    """The roadmap reframes every view, so it is reachable from every view.

    Parametrized over :data:`~tracker.ui.shell.NAV` rather than over a copied list of paths,
    so a tenth page added to the nav is covered the day it is added — the same argument the
    nav's own docstring makes about there being one tuple.
    """
    _open(phone, ui_base_url, path)
    selector = phone.locator("[data-testid=global-roadmap-select]")

    assert selector.count() == 1, f"{path} has no roadmap selector"
    # *Which* roadmap is primary belongs to the test below, which is also the test that can
    # change it. Asserting a specific name here would make every page's coverage depend on
    # the order the suite happens to run in.
    assert selector.inner_text().strip() in {"Main NH", "Anti-PKer"}, f"{path} shows no selection"


def test_switching_the_primary_roadmap_from_the_header_persists(
    phone: Page, ui_base_url: str
) -> None:
    """A13: the header writes to ``ActiveRoadmap``, and ``/roadmaps`` agrees afterwards.

    The options are asserted through the accessibility role rather than through a scoped
    locator on purpose — NiceGUI's ``ui.select`` is a Quasar ``QSelect`` and renders its
    popup into a ``.q-menu`` portal appended to ``<body>``, outside the element carrying the
    testid. A locator scoped to the select finds zero options and the test would fail for a
    reason that has nothing to do with the feature.
    """
    _open(phone, ui_base_url, "/")
    phone.locator("[data-testid=global-roadmap-select]").click()
    phone.get_by_role("option", name="Anti-PKer").click()

    # The handler reloads, so wait for the shell to come back rather than for a timeout.
    phone.wait_for_selector("[data-testid=nav]", timeout=15_000)
    # ...and then wait for the reload to *finish*. The nav selector reappears as soon as
    # NiceGUI has re-rendered over the websocket, which is before the reload's own document
    # navigation has necessarily settled. Navigating away inside that window makes Chromium
    # abort the new request in favour of the one already in flight — `net::ERR_ABORTED`, on a
    # page that is perfectly healthy. The failure is timing-dependent, so it surfaces only
    # when something unrelated changes how long the preceding tests take.
    phone.wait_for_load_state("networkidle")

    _open(phone, ui_base_url, "/roadmaps")
    # ``roadmaps.py`` omits the primary from the secondary list, so which roadmap is primary
    # is assertable by which checkbox exists — a stronger claim than the radio group's text,
    # which names every option whichever one is selected.
    secondary = "[data-testid=secondary-roadmap-checkbox]"
    assert phone.locator(f"{secondary}[data-roadmap=main_nh]").count() == 1
    assert phone.locator(f"{secondary}[data-roadmap=anti_pk]").count() == 0
    assert "Anti-PKer" in phone.locator("[data-testid=global-roadmap-select]").inner_text()

    # Restore the seeded primary. The database is shared across this module, and a test that
    # leaves the account on a different roadmap makes every later assertion order-dependent.
    phone.locator("[data-testid=global-roadmap-select]").click()
    phone.get_by_role("option", name="Main NH").click()
    phone.wait_for_selector("[data-testid=nav]", timeout=15_000)


# ---------------------------------------------------------------------------
# Step 11 — History: scoring_profile_version alongside every snapshot (§6.10)
# ---------------------------------------------------------------------------


def test_history_shows_the_scoring_profile_version_with_each_snapshot(
    phone: Page, ui_base_url: str
) -> None:
    _open(phone, ui_base_url, "/history")
    snapshot = phone.locator("[data-testid=history-snapshot]").first
    assert snapshot.count() == 1
    assert snapshot.get_attribute("data-profile-version") == "1"
    assert "scoring profile v1" in snapshot.inner_text()


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


# ---------------------------------------------------------------------------
# Step 8 — the "How" line (§8.2, §15)
# ---------------------------------------------------------------------------


def test_a_skill_training_entry_names_the_method_its_hours_came_from(
    phone: Page, ui_base_url: str
) -> None:
    """§15's "How" line. The estimator has always chosen a method; now the page says which.

    Asserted on the DOM rather than only on the row, because the whole failure this closes
    was a value that existed in memory and never reached a template.
    """
    _open(phone, ui_base_url, "/recommendations")
    detail = phone.locator('[data-candidate="train_magic_87_to_94"] [data-testid=method-detail]')

    assert detail.count() == 1
    assert detail.locator('[data-method="magic_bursting"]').count() == 1
    assert "Magic bursting" in detail.inner_text()
    # MethodDetail's descriptive half, which is why the type exists at all.
    assert "Catacombs of Kourend" in detail.inner_text()


def test_a_fallback_band_is_qualified_rather_than_left_blank(phone: Page, ui_base_url: str) -> None:
    """§8.4 — the conservative default is a claim the UI is required to qualify.

    An empty cell reads as "no information"; the truth is "a number we invented".
    """
    _open(phone, ui_base_url, "/recommendations")
    fallback = phone.locator('[data-candidate="train_magic_87_to_94"] [data-fallback="true"]')

    assert fallback.count() == 1
    assert "upper bound" in fallback.inner_text()


def test_an_entry_with_no_bands_renders_no_how_block(phone: Page, ui_base_url: str) -> None:
    """A refresher has no level bands, and an empty "How" row would be noise.

    The seeded refresher is the case: §9.8 sizes it in hours, but there is no skill being
    trained through a level range, so there is nothing for this block to say.
    """
    _open(phone, ui_base_url, "/recommendations")
    refresher = phone.locator('[data-candidate="refresh_nh_fundamentals"]')

    assert refresher.count() == 1
    assert refresher.locator("[data-testid=method-detail]").count() == 0


# ---------------------------------------------------------------------------
# Step 9 — account type and membership (§4.2, §4.5)
# ---------------------------------------------------------------------------


def test_account_mode_defaults_to_unset_rather_than_to_main(phone: Page, ui_base_url: str) -> None:
    """§4.5 on the page itself: "nobody has said" is an option, and it is the one selected.

    A radio group without it would force an assertion the moment the page renders, and the
    assertion it would force — "main" — is exactly the one that makes the app recommend
    purchases to an ironman.
    """
    _open(phone, ui_base_url, "/settings")
    group = phone.locator("[data-testid=account-type-radio]")

    assert group.count() == 1
    assert group.get_attribute("data-configured") == "false"
    assert "Not set" in group.inner_text()


def test_the_account_section_explains_what_leaving_it_unset_costs(
    phone: Page, ui_base_url: str
) -> None:
    """An honest default needs an explanation, or it reads as the app ignoring the answer."""
    _open(phone, ui_base_url, "/settings")
    text = phone.locator("[data-testid=settings-account]").inner_text()

    assert "purchases are still suggested" in text
    assert "does not guess" in text


def test_membership_is_asked_separately_from_account_mode(phone: Page, ui_base_url: str) -> None:
    """Two questions, two answers: an ironman may be free-to-play and a main may not be."""
    _open(phone, ui_base_url, "/settings")
    members = phone.locator("[data-testid=members-radio]")

    assert members.count() == 1
    assert members.get_attribute("data-configured") == "false"


# ---------------------------------------------------------------------------
# Step 10 — the price cache, made visible (§8.3, §4.5)
# ---------------------------------------------------------------------------


def test_settings_says_whether_prices_have_ever_been_fetched(phone: Page, ui_base_url: str) -> None:
    """ "Never fetched" and "0 items priced" are different sentences (§4.5).

    Until this line existed there was no way to tell a price feed that had never run from
    one that ran and found nothing: both showed as estimates falling back to the authored
    hint, which §8.4 marks ``low`` either way. That is how a scheduler whose first tick was
    an hour away went unnoticed.
    """
    _open(phone, ui_base_url, "/settings")
    cache = phone.locator("[data-testid=price-cache]")

    assert cache.count() == 1
    assert cache.get_attribute("data-fetched") == "false"
    assert "never fetched" in cache.inner_text()


# ---------------------------------------------------------------------------
# Blocked rows say why (§15)
# ---------------------------------------------------------------------------


def test_a_blocked_entry_names_what_blocks_it(phone: Page, ui_base_url: str) -> None:
    """A bare name is a goal with no path.

    "Complete Lunar Diplomacy — blocked" tells a reader nothing they can act on, and the
    Capabilities page has answered the same question since it was built. This closes the
    gap the earlier design missed by assuming the capability views already carried these —
    which stopped being true once a candidate could be gated on quests no capability names.
    """
    _open(phone, ui_base_url, "/recommendations")
    entry = phone.locator('[data-testid=blocked-candidate][data-candidate="buy_high_risk_gear"]')

    assert entry.count() == 1
    blockers = entry.locator("[data-testid=blocked-by]")
    assert blockers.count() == 1
    assert "Magic 94" in blockers.inner_text()
    assert "Desert Treasure I" in blockers.inner_text()


def test_the_blocked_list_asks_for_the_same_thing_as_the_capabilities_page(
    phone: Page, ui_base_url: str
) -> None:
    """One verb, one wording (§15).

    A reader who learns what "Do these to unlock it" means on Capabilities should not have
    to learn it again here, so the CTA constant is shared rather than reworded.
    """
    _open(phone, ui_base_url, "/recommendations")
    text = phone.locator("[data-testid=blocked-candidate] [data-testid=blocked-by]").inner_text()

    assert BLOCKERS_CTA in text


def test_the_recommendations_page_names_what_an_entry_unblocks(
    phone: Page, ui_base_url: str
) -> None:
    """§9.10's consequences reach the DOM as their own labelled row, not folded into the
    Why line. A reader scanning the list must be able to find "what is this for" in the same
    place on every card."""
    _open(phone, ui_base_url, "/recommendations")

    assert "Ice Barrage NH" in phone.locator("[data-testid=unblocks]").first.inner_text()


def test_the_recommendations_page_shows_what_an_entry_is_needed_for(
    phone: Page, ui_base_url: str
) -> None:
    """The user's own complaint, asserted where they would have seen it: a task that looks
    pointless on its own, shown with the task it is a prerequisite of and how far along that
    gate it gets them."""
    _open(phone, ui_base_url, "/recommendations")
    text = phone.locator("[data-testid=needed-for]").first.inner_text()

    assert "Complete Desert Treasure I" in text
    assert "1 of 3 remaining" in text


def test_a_goal_outside_the_selected_roadmap_is_labelled_as_such(
    phone: Page, ui_base_url: str
) -> None:
    """The diagnostic half of the feature. An entry serving a goal the player did not pick
    must say so on the card, because that is the fact that explains an otherwise baffling
    recommendation."""
    _open(phone, ui_base_url, "/recommendations")

    assert "not on your roadmap" in phone.locator("[data-testid=needed-for]").first.inner_text()


def test_the_consequence_rows_are_separate_nodes_from_the_reason(
    phone: Page, ui_base_url: str
) -> None:
    """They answer different questions — "how did this score" against "what is it for" —
    and a single merged node would leave the page no way to style or hide one of them."""
    _open(phone, ui_base_url, "/recommendations")

    assert (
        phone.locator("[data-testid=recommendation-reason] [data-testid=works-toward]").count() == 0
    )
    assert phone.locator("[data-testid=works-toward]").count() >= 1


def test_every_recommendation_offers_guidance(phone: Page, ui_base_url: str) -> None:
    """§21's affordance sits on each entry, keyed to the candidate it explains.

    Asserted in the browser because the pairing is what matters: a button that renders but
    carries the wrong candidate would ask about the wrong task, and only the DOM says which
    button belongs to which card.
    """
    _open(phone, ui_base_url, "/recommendations")

    cards = phone.locator('[data-testid="recommendation"]')
    buttons = phone.locator('[data-testid="guidance-button"]')

    assert cards.count() > 0
    assert buttons.count() == cards.count()


def test_the_guidance_button_does_not_shadow_the_candidate_selector(
    phone: Page, ui_base_url: str
) -> None:
    """The button carries ``data-guidance-for``, never a second ``data-candidate``.

    Its own test because the failure is invisible in the rendered page and shows up only as
    every pre-existing ``[data-candidate=...]`` locator quietly matching twice.
    """
    _open(phone, ui_base_url, "/recommendations")
    first = phone.locator('[data-testid="guidance-button"]').first
    candidate = first.get_attribute("data-guidance-for")

    assert candidate
    assert phone.locator(f'[data-candidate="{candidate}"]').count() == 1


def test_guidance_reports_itself_unconfigured_rather_than_failing(
    phone: Page, ui_base_url: str
) -> None:
    """D14 — with no provider the feature explains itself and nothing else changes.

    The seeded app has no API key, which is the state most installs are in. The button still
    appears, because a feature the user cannot discover is a feature they cannot switch on.
    """
    _open(phone, ui_base_url, "/recommendations")
    phone.locator('[data-testid="guidance-button"]').first.click()

    error = phone.locator('[data-testid="guidance-error"]')
    error.first.wait_for(state="visible")

    assert "not configured" in (error.first.inner_text() or "")
    assert phone.locator('[data-testid="recommendation"]').count() > 0


# ---------------------------------------------------------------------------
# §22 — the advisor
# ---------------------------------------------------------------------------


def _ask(page: Page, base: str, question: str) -> Page:
    """Type a question and send it.

    Located by placeholder rather than by ``data-testid``: NiceGUI puts ``props`` on the Quasar
    wrapper, and the element that actually accepts text is a ``textarea`` nested inside it, so a
    testid selector here would be asserting about the wrapper's markup rather than about the box
    a person types in.
    """
    _open(page, base, "/advisor")
    page.get_by_placeholder("Ask about your account").fill(question)
    page.locator('[data-testid="advisor-send"]').first.click()
    return page


def test_the_nav_offers_the_advisor(phone: Page, ui_base_url: str) -> None:
    _open(phone, ui_base_url, "/")
    assert "Advisor" in (phone.locator('[data-testid="nav"]').first.inner_text() or "")
    assert any(item.path == "/advisor" for item in NAV)


def test_an_empty_advisor_says_what_it_can_see(phone: Page, ui_base_url: str) -> None:
    """The first question should be an informed one."""
    _open(phone, ui_base_url, "/advisor")
    empty = phone.locator('[data-testid="advisor-empty"]')
    empty.first.wait_for(state="visible")
    assert "Ask anything" in (empty.first.inner_text() or "")


def test_asking_renders_the_question_and_the_answer(phone: Page, ui_base_url: str) -> None:
    _ask(phone, ui_base_url, "what should I bring to crocodiles?")
    answer = phone.locator('[data-testid="advisor-message"][data-role="advisor"]')
    answer.first.wait_for(state="visible", timeout=15_000)
    assert "Bring a whip" in (answer.first.inner_text() or "")
    asked = phone.locator('[data-testid="advisor-message"][data-role="you"]')
    assert "crocodiles" in (asked.first.inner_text() or "")


def test_the_answer_carries_its_provenance(phone: Page, ui_base_url: str) -> None:
    """§15 — the reader should not have to infer which prose a model wrote."""
    _ask(phone, ui_base_url, "who wrote this?")
    provenance = phone.locator('[data-testid="advisor-provenance"]')
    provenance.first.wait_for(state="visible", timeout=15_000)
    assert "scripted-advisor" in (provenance.first.inner_text() or "")


def test_a_hedge_is_drawn_apart_from_the_answer(phone: Page, ui_base_url: str) -> None:
    """It cannot be marked *as* a hedge if it arrives inside the paragraph."""
    _ask(phone, ui_base_url, "what are you unsure about?")
    hedge = phone.locator('[data-testid="advisor-uncertain"]')
    hedge.first.wait_for(state="visible", timeout=15_000)
    assert "unsure" in (hedge.first.inner_text() or "")


def test_the_lookups_an_answer_used_are_named(phone: Page, ui_base_url: str) -> None:
    """So a reader can tell corpus-backed claims from the model's own knowledge."""
    _ask(phone, ui_base_url, "which methods exist?")
    sources = phone.locator('[data-testid="advisor-sources"]')
    sources.first.wait_for(state="visible", timeout=15_000)
    assert "training methods" in (sources.first.inner_text() or "")


def _open_picker(page: Page) -> None:
    """Open the conversation list, and wait for it to actually be there.

    Quasar teleports a menu's content to the body when it opens, so the rows do not exist in
    the document until that has happened — a bare click followed by a count reads zero.
    """
    page.locator('[data-testid="advisor-picker"]').first.click()
    page.locator('[data-testid="advisor-conversation"]').first.wait_for(
        state="visible", timeout=10_000
    )


def _ask_in_new_thread(page: Page, base: str, question: str) -> None:
    """Ask into a thread of its own, so that the thread is *named* after this question.

    A conversation takes its title from the question that opened it, and the fixtures in this
    module share one database for the whole session. Without the *New* click, a question lands
    in whichever conversation an earlier test left behind — and is then filed under that test's
    title, which is why every assertion below picks a word no other test uses.
    """
    _open(page, base, "/advisor")
    page.locator('[data-testid="advisor-new"]').first.click()
    # Waited on the URL, not on the empty state. *New* is a navigation, and the page being left
    # is itself empty whenever this account has no history yet — so waiting for an empty thread
    # is answered by the document we are trying to leave, and the question then gets typed into
    # a textarea that the navigation is about to discard.
    page.wait_for_url(lambda url: url.endswith("conversation=0"), timeout=15_000)
    page.wait_for_selector("[data-testid=nav]", timeout=15_000)
    page.locator('[data-testid="advisor-empty"]').first.wait_for(state="visible", timeout=15_000)
    page.get_by_placeholder("Ask about your account").fill(question)
    page.locator('[data-testid="advisor-send"]').first.click()
    page.locator('[data-testid="advisor-message"][data-role="advisor"]').first.wait_for(
        state="visible", timeout=15_000
    )


def _listed(page: Page) -> str:
    """Every title the open picker is showing, as one string."""
    rows = page.locator('[data-testid="advisor-conversation"]')
    return " ".join(rows.nth(index).inner_text() or "" for index in range(rows.count()))


def test_starting_a_new_conversation_leaves_the_old_one(phone: Page, ui_base_url: str) -> None:
    """*New* has to produce a blank thread, which for a while it did not.

    ``?conversation=0`` went through the read path's unknown-id fallback — the branch that
    exists so a stale bookmark still shows something — and came back with the most recent
    conversation. So the control returned the reader to the thread they were trying to leave,
    and the next question was appended to it.
    """
    _ask(phone, ui_base_url, "a conversation worth leaving behind")
    phone.locator('[data-testid="advisor-message"][data-role="advisor"]').first.wait_for(
        state="visible", timeout=15_000
    )

    phone.locator('[data-testid="advisor-new"]').first.click()
    phone.locator('[data-testid="advisor-empty"]').first.wait_for(state="visible", timeout=15_000)

    assert phone.locator('[data-testid="advisor-message"]').count() == 0


def test_the_picker_names_the_thread_you_are_reading(phone: Page, ui_base_url: str) -> None:
    """Which nothing on the page said before: the old row marked it with a gold outline only."""
    _ask_in_new_thread(phone, ui_base_url, "a question about zulrah, and nothing else")

    picker = phone.locator('[data-testid="advisor-picker"]')
    assert "zulrah" in (picker.first.inner_text() or "")


def test_past_conversations_are_listed_where_they_can_be_read(
    phone: Page, ui_base_url: str
) -> None:
    """Both threads, by name — the failure of the old row was that you could read neither."""
    _ask_in_new_thread(phone, ui_base_url, "an older thread, about vorkath")
    _ask_in_new_thread(phone, ui_base_url, "a newer thread, about wintertodt")
    _open_picker(phone)

    listed = _listed(phone)
    assert "vorkath" in listed
    assert "wintertodt" in listed


def test_opening_a_listed_conversation_goes_to_it(phone: Page, ui_base_url: str) -> None:
    _ask_in_new_thread(phone, ui_base_url, "the thread about tempoross that I want back")
    _ask_in_new_thread(phone, ui_base_url, "some later thread about hallowed sepulchre")
    _open_picker(phone)

    rows = phone.locator('[data-testid="advisor-conversation"]')
    wanted = next(
        index
        for index in range(rows.count())
        if "tempoross" in (rows.nth(index).inner_text() or "")
    )
    rows.nth(wanted).click()

    # Waited for by *content*, not by the presence of a question row. Opening a thread is a
    # navigation, and the page being left already has a question in it — so anything that only
    # asks "is there a question on screen" is answered by the old document and passes before
    # the new one has loaded, which is exactly how this read as green while landing nowhere.
    phone.wait_for_selector('[data-testid=advisor-thread]:has-text("tempoross")', timeout=15_000)


def test_cancelling_a_delete_keeps_the_conversation(phone: Page, ui_base_url: str) -> None:
    """The only irreversible thing this application does, so cancelling has to really cancel."""
    _ask_in_new_thread(phone, ui_base_url, "a thread about chambers that survives this")
    _open_picker(phone)

    phone.locator('[data-testid="advisor-delete"]').first.click()
    body = phone.locator('[data-testid="advisor-delete-body"]')
    body.first.wait_for(state="visible", timeout=10_000)
    # It names the thread, because every one of those buttons is otherwise identical.
    assert "chambers" in (body.first.inner_text() or "")

    phone.locator('[data-testid="advisor-delete-cancel"]').first.click()
    body.first.wait_for(state="hidden", timeout=10_000)

    _open(phone, ui_base_url, "/advisor")
    _open_picker(phone)
    assert "chambers" in _listed(phone)


def test_a_confirmed_delete_removes_the_conversation(phone: Page, ui_base_url: str) -> None:
    _ask_in_new_thread(phone, ui_base_url, "a thread about theatre of blood, soon gone")
    _open_picker(phone)
    before = phone.locator('[data-testid="advisor-conversation"]').count()

    phone.locator('[data-testid="advisor-delete"]').first.click()
    phone.locator('[data-testid="advisor-delete-body"]').first.wait_for(
        state="visible", timeout=10_000
    )
    phone.locator('[data-testid="advisor-delete-confirm"]').first.click()

    phone.wait_for_selector("[data-testid=nav]", timeout=15_000)
    _open_picker(phone)
    assert phone.locator('[data-testid="advisor-conversation"]').count() == before - 1
    assert "theatre of blood" not in _listed(phone)


def _continue_thread(page: Page, base: str) -> Page:
    """Reload wherever the last turn left us, so the next question *continues* a thread.

    The distinction is the whole subject of the tests below. A question that opens a new
    conversation ends in a navigate, and the reload hides everything the optimistic render did
    by fetching the stored turn back. Only the second question in a thread exercises the path
    where what stays on screen is what the page put there.
    """
    return _open(page, base, page.url.removeprefix(base))


def test_a_second_question_in_a_thread_stays_on_screen(phone: Page, ui_base_url: str) -> None:
    """The question and its answer have different lifetimes, and only the spinner is temporary.

    This is a regression test with a specific shape behind it: the question and the spinner
    were once rendered into a single wrapper that was deleted when the answer arrived, which
    deleted the question too. The first turn hid it — that one ends in a navigate, and the
    reload drew the stored question back — so the symptom only appeared from the second
    question onwards, as a thread of answers with nothing above them.
    """
    _ask(phone, ui_base_url, "first question about crocodiles")
    phone.locator('[data-testid="advisor-message"][data-role="advisor"]').first.wait_for(
        state="visible", timeout=15_000
    )
    _continue_thread(phone, ui_base_url)

    asked = phone.locator('[data-testid="advisor-message"][data-role="you"]')
    answers = phone.locator('[data-testid="advisor-message"][data-role="advisor"]')
    questions_before, answers_before = asked.count(), answers.count()

    phone.get_by_placeholder("Ask about your account").fill("second question about kalphites")
    phone.locator('[data-testid="advisor-send"]').first.click()
    answers.nth(answers_before).wait_for(state="visible", timeout=15_000)

    assert asked.count() == questions_before + 1
    assert "kalphites" in (asked.nth(questions_before).inner_text() or "")
    # The spinner is the one thing that was supposed to go.
    assert phone.locator('[data-testid="advisor-pending"]').count() == 0


def test_a_failed_question_goes_back_into_the_box(
    phone: Page, ui_base_url: str, advisor: Any
) -> None:
    """Nothing was asked, so nothing is left claiming to have been.

    The echoed question was optimistic and the turn was never stored, so leaving it in the
    transcript would promise a reload that will not show it. Returning it to the composer —
    which was cleared on send — is what makes *Ask* a retry instead of a request to retype the
    question, and a throttle is exactly the failure worth retrying.
    """
    advisor.failure = LlmUnavailable("down")
    _ask(phone, ui_base_url, "a question that will not survive the provider")

    phone.locator('[data-testid="advisor-error"]').first.wait_for(state="visible", timeout=15_000)

    box = phone.get_by_placeholder("Ask about your account")
    assert "will not survive" in (box.input_value() or "")
    echoed = phone.locator('[data-testid="advisor-message"][data-role="you"]')
    assert echoed.filter(has_text="will not survive").count() == 0


def test_the_page_announces_a_turn_without_showing_anything(phone: Page, ui_base_url: str) -> None:
    """The advisor is driven from the keyboard, and its answer arrives out of sight.

    The region has to exist *before* the question is sent — a live region appended alongside
    the content it describes is not reliably announced — so its presence on an untouched page
    is half of what is under test here.
    """
    _open(phone, ui_base_url, "/advisor")
    status = phone.locator('[data-testid="advisor-status"]')
    assert status.count() == 1
    assert status.first.get_attribute("aria-live") == "polite"

    phone.get_by_placeholder("Ask about your account").fill("announce this one")
    phone.locator('[data-testid="advisor-send"]').first.click()

    # Waited on the announcement itself rather than on an answer appearing. This page may open
    # onto a thread that already has answers in it, so "an answer is visible" is true before
    # this question is even sent. `state="attached"` because the region is clipped to a pixel
    # on purpose — its whole job is to be read aloud and never drawn.
    phone.wait_for_selector(
        '[data-testid=advisor-status]:has-text("answered")', state="attached", timeout=15_000
    )
    # `text_content` rather than `inner_text` for the same reason: `inner_text` reports what is
    # rendered, which for this element is nothing.
    assert "answered" in (status.first.text_content() or "")


def test_a_new_answer_is_scrolled_into_view(phone: Page, ui_base_url: str, advisor: Any) -> None:
    """A page whose response to a question is to change nothing visible has not answered it.

    Asserted as *where the answer ended up*, not as "the page scrolled". Scroll offset alone
    is not evidence: Playwright scrolls the composer into view in order to type into it, so a
    non-zero ``scrollY`` is true here whether or not this feature exists at all — which is
    exactly what an earlier draft of this test measured, and it passed with the scrolling
    removed.
    """
    original = advisor.answer
    advisor.answer = "Bring a whip and food.\n\n" + "\n\n".join(
        f"A paragraph of supporting detail, number {n}." for n in range(60)
    )
    try:
        _ask(phone, ui_base_url, "a question whose answer runs past the fold")
        phone.locator('[data-testid="advisor-message"][data-role="advisor"]').first.wait_for(
            state="visible", timeout=15_000
        )
        _continue_thread(phone, ui_base_url)
        answers = phone.locator('[data-testid="advisor-message"][data-role="advisor"]')
        answers_before = answers.count()

        phone.get_by_placeholder("Ask about your account").fill("and another one, just as long")
        phone.locator('[data-testid="advisor-send"]').first.click()
        arrived = answers.nth(answers_before)
        arrived.wait_for(state="visible", timeout=15_000)
        phone.wait_for_timeout(250)

        # `bounding_box` is viewport-relative, and nothing in this test scrolls the answer
        # itself — `wait_for` does not. So where the top edge sits is the page's doing.
        #
        # Asserted against the *top* of the screen rather than merely "on screen". An answer
        # appended to a thread the reader has already scrolled to the foot of starts just
        # below the fold anyway, so "somewhere in the viewport" is satisfied by doing nothing
        # at all — measured, and it was.
        # The lower bound has a pixel of slack in it: `scrollIntoView` lands on a fractional
        # offset, and the top edge measures a shade either side of zero rather than on it.
        box = arrived.bounding_box()
        assert box is not None
        assert -2 <= box["y"] < PHONE["height"] / 4
    finally:
        advisor.answer = original


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("unavailable", "Could not reach the advisor"),
        ("refused", "declined to answer"),
        ("throttled", "wait"),
    ],
)
def test_each_failure_renders_its_own_sentence_in_the_conversation(
    phone: Page, ui_base_url: str, advisor: Any, failure: str, expected: str
) -> None:
    """D14 — a failure is text where the reader is looking, and nothing else moves.

    Three sentences rather than one because the remedies differ: an outage is worth retrying,
    a refusal is not, and a throttle is a wait. Collapsing them would tell someone to retry
    something that will never succeed.
    """
    advisor.failure = {
        "unavailable": LlmUnavailable("down"),
        "refused": LlmRefused("no"),
        "throttled": AdvisorThrottled("wait 10s before asking again"),
    }[failure]

    _ask(phone, ui_base_url, f"trigger {failure}")
    error = phone.locator('[data-testid="advisor-error"]')
    error.first.wait_for(state="visible", timeout=15_000)
    assert expected in (error.first.inner_text() or "")
    # The rest of the page is untouched: the nav is still there and nothing was replaced.
    assert phone.locator('[data-testid="nav"]').count() > 0


def test_the_advisor_page_does_not_scroll_horizontally(phone: Page, ui_base_url: str) -> None:
    _ask(phone, ui_base_url, "a fairly long question about what to train next on this account")
    phone.locator('[data-testid="advisor-message"][data-role="advisor"]').first.wait_for(
        state="visible", timeout=15_000
    )
    overflow = phone.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 1
