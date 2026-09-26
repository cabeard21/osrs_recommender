"""Small browser smoke suite for retained pages and user workflows.

Domain and API tests cover account and recommendation values. These checks are limited to
behavior that requires NiceGUI's rendered DOM or an actual browser interaction.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.browser


def _open(page: Page, base: str, path: str) -> None:
    page.goto(f"{base}{path}", wait_until="domcontentloaded")
    # NiceGUI renders the page body over a websocket after the initial response.
    page.wait_for_selector("[data-testid=nav]", timeout=15_000)
    page.evaluate("() => document.fonts.ready")


@pytest.mark.parametrize(
    ("path", "selector"),
    [
        ("/", "[data-testid=account-summary]"),
        ("/skills", "[data-testid=skills-ranked]"),
        ("/gear", "[data-testid^=gear-slot-]"),
        ("/settings", "[data-testid=settings-character]"),
        ("/advisor", "[data-testid=advisor-thread]"),
        ("/recommendations", "[data-testid=recommendation]"),
        ("/practice", "[data-testid=practice-group]"),
    ],
)
def test_retained_pages_render(page: Page, ui_base_url: str, path: str, selector: str) -> None:
    _open(page, ui_base_url, path)
    assert page.locator(selector).count() > 0


@pytest.mark.parametrize("path", ["/gear", "/capabilities"])
def test_dense_pages_fit_a_phone(page: Page, ui_base_url: str, path: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    _open(page, ui_base_url, path)
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"{path} overflows a 390px viewport by {overflow}px"


def test_gear_ladder_renders_ordered_unique_rungs(page: Page, ui_base_url: str) -> None:
    _open(page, ui_base_url, "/gear")
    slot = page.locator("[data-testid^=gear-slot-]").first
    rungs = slot.locator("[data-testid=gear-rung]")
    tiers = [rungs.nth(index).get_attribute("data-tier") for index in range(rungs.count())]
    assert tiers
    assert len(tiers) == len(set(tiers))
    assert tiers == sorted(tiers, key=lambda tier: -int(tier or 0))
    assert slot.locator('[data-testid=gear-rung][data-role*="best"]').count() <= 1


def test_unranked_skill_does_not_claim_a_level(page: Page, ui_base_url: str) -> None:
    _open(page, ui_base_url, "/skills")
    row = page.locator('[data-testid=skill][data-ranked="false"]').first
    rendered = row.inner_text()
    assert "unranked" in rendered.lower()
    assert not any(character.isdigit() for character in rendered)


def test_settings_shows_token_presence_without_exposing_value(page: Page, ui_base_url: str) -> None:
    _open(page, ui_base_url, "/settings")
    presence = page.locator("[data-testid=token-presence]")
    assert presence.get_attribute("data-present") == "true"
    assert "ui-test-token-1234567890" not in page.locator("body").inner_text()


def test_advisor_question_and_answer_render(page: Page, ui_base_url: str) -> None:
    _open(page, ui_base_url, "/advisor")
    page.get_by_placeholder("Ask about your account").fill("what should I bring to crocodiles?")
    page.locator('[data-testid="advisor-send"]').first.click()
    answer = page.locator('[data-testid="advisor-message"][data-role="advisor"]')
    answer.first.wait_for(state="visible", timeout=15_000)
    assert "Bring a whip" in answer.first.inner_text()
    question = page.locator('[data-testid="advisor-message"][data-role="you"]')
    assert "crocodiles" in question.first.inner_text()
