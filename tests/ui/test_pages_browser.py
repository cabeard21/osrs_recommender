"""One browser journey through the factual Account Companion surfaces."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.browser


def test_factual_navigation_and_uncertainty(page: Page, ui_base_url: str) -> None:
    page.goto(ui_base_url, wait_until="domcontentloaded")
    page.locator("[data-testid=quest-cape-status]").wait_for()
    assert "unknown" in page.locator("[data-testid=account-summary]").inner_text().lower()

    page.goto(f"{ui_base_url}/gear", wait_until="domcontentloaded")
    page.locator("[data-testid=gear-item]").first.wait_for()
    assert page.locator("[data-testid=gear-item]").count() > 0
    assert "unknown" in page.locator("[data-testid=gear-item]").first.inner_text().lower()

    page.goto(f"{ui_base_url}/settings", wait_until="domcontentloaded")
    page.locator("[data-testid=gp-sensitivity-radio]").wait_for()
    assert "no effect on Gear" in page.locator("[data-testid=settings-sensitivity]").inner_text()
    assert "ui-test-token-1234567890" not in page.locator("body").inner_text()
