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


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/capabilities",
        "/unlocks",
        "/skills",
        "/recommendations",
        "/practice",
        "/roadmaps",
        "/settings",
        "/history",
    ],
)
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
