"""One browser journey through the factual Account Companion surfaces."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from threading import Event

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def test_account_change_during_search_cannot_publish_cached_result(
    page: Page, ui_base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tracker.accounts.service import AccountService
    from tracker.gear.service import GearService

    started, release, changed = Event(), Event(), Event()
    original_snapshot = AccountService.get_snapshot
    original_optimize = GearService.optimize

    def fresh_snapshot(*args, **kwargs):
        snapshot = original_snapshot(*args, **kwargs)
        if changed.is_set():
            return replace(snapshot, last_sync_at=datetime(2026, 10, 19, tzinfo=UTC))
        return snapshot

    def delayed_search(*args, **kwargs):
        started.set()
        if not release.wait(10):
            raise RuntimeError("browser test did not release search")
        return original_optimize(*args, **kwargs)

    monkeypatch.setattr(AccountService, "get_snapshot", fresh_snapshot)
    monkeypatch.setattr(GearService, "optimize", delayed_search)
    page.goto(f"{ui_base_url}/gear", wait_until="domcontentloaded")
    page.locator("[data-testid=gear-optimize]").click()
    try:
        assert started.wait(5)
        changed.set()
    finally:
        release.set()
    page.get_by_text(
        "Account observations changed. Optimize again for current facts.", exact=True
    ).wait_for()
    expect(page.locator("[data-testid=gear-results]")).to_have_text("")


def test_factual_navigation_and_uncertainty(page: Page, ui_base_url: str) -> None:
    page.goto(ui_base_url, wait_until="domcontentloaded")
    page.locator("[data-testid=quest-cape-status]").wait_for()
    assert "unknown" in page.locator("[data-testid=account-summary]").inner_text().lower()

    page.goto(f"{ui_base_url}/gear", wait_until="domcontentloaded")
    page.locator("[data-testid=gear-optimizer]").wait_for()
    assert "Observed ownership" in page.locator("body").inner_text()
    page.locator("[data-testid=gear-optimize]").click()
    page.get_by_text("Best found under the supported combat model.", exact=True).wait_for()
    assert "No feasible solution" in page.locator("body").inner_text() or (
        page.locator("[data-testid=gear-selected-solution]").count() > 0
    )

    page.goto(f"{ui_base_url}/settings", wait_until="domcontentloaded")
    page.locator("[data-testid=gp-sensitivity-radio]").wait_for()
    assert "no effect on Gear" in page.locator("[data-testid=settings-sensitivity]").inner_text()
    assert "ui-test-token-1234567890" not in page.locator("body").inner_text()


def test_future_optimizer_preserves_account_facts_and_invalidates_results(
    page: Page, ui_base_url: str
) -> None:
    page.goto(f"{ui_base_url}/gear", wait_until="domcontentloaded")
    page.locator("[data-testid=gear-mode]").click()
    page.get_by_role("option", name="Future / explicit what-if").click()
    page.get_by_text("Target and future assumptions", exact=True).click()
    page.get_by_label("Future skill levels (one skill=level per line)", exact=True).fill(
        "attack=70\nstrength=70\ndefence=70\nranged=70\nmagic=70"
    )
    page.get_by_label("Assumed acquired item IDs, comma separated", exact=True).fill("1323,1333")
    page.get_by_text("Combat roles and transitions", exact=True).click()
    page.get_by_label("Stance", exact=True).first.click()
    page.get_by_role("option", name="aggressive", exact=True).click()
    page.locator("[data-testid=gear-optimize]").click()
    page.get_by_text("Encounter score:", exact=False).first.wait_for()
    expect(page.locator("[data-testid=gear-melee-melee_strength]")).to_have_text(
        "Melee strength bonus: +44"
    )
    expect(page.locator("[data-testid=gear-melee-ranged_strength]")).to_have_text(
        "Ranged strength bonus: +0"
    )
    page.get_by_text("Compatible alternatives", exact=True).first.click()
    iron_alternative = page.locator("[data-testid=gear-alternative-weapon-1323]")
    expect(iron_alternative).to_be_visible()
    expect(page.locator("[data-testid=gear-selected-solution]")).to_contain_text("DPS;")
    iron_alternative.click()
    expect(page.locator("[data-testid=gear-selected-solution]")).to_contain_text("Iron scimitar")
    expect(page.locator("[data-testid=gear-selected-solution]")).not_to_contain_text(
        "Rune scimitar"
    )
    expect(page.locator("[data-testid=gear-selected-solution]")).to_contain_text(
        "Free after reserved supplies:"
    )
    page.get_by_text("Magic", exact=True).click()
    magic_role = page.get_by_role("checkbox", name="Use magic", exact=True)
    magic_role.focus()
    magic_role.press("Space")
    expect(magic_role).to_be_checked()
    page.get_by_label("Required transitions", exact=True).click()
    page.get_by_role("option", name="Ordered phases", exact=True).click()
    page.get_by_label("Ordered phases (optional, role > role)", exact=True).fill(
        "melee > magic > melee"
    )
    page.locator("[data-testid=gear-optimize]").click()
    page.get_by_text("Best found under the supported combat model.", exact=True).wait_for(
        timeout=30000
    )
    page.get_by_text("Encounter score:", exact=False).first.wait_for()
    page.get_by_text("Magic equipment", exact=True).wait_for()
    page.get_by_text("Melee equipment", exact=True).wait_for()
    # The chart, picker, equipment and inventory must describe the same curve point.
    curve = page.locator("[data-testid=gear-swap-curve]")
    equipment = page.locator("[data-testid=gear-selected-solution]")
    assert curve.bounding_box()["y"] < equipment.bounding_box()["y"]
    point = curve.locator(".scatterlayer .point").last
    point.scroll_into_view_if_needed()
    position = point.bounding_box()
    # Plotly's transparent drag layer receives the physical pointer event.
    page.mouse.click(position["x"] + position["width"] / 2, position["y"] + position["height"] / 2)
    expect(page.locator("[data-testid=gear-curve-picker]")).to_contain_text("8 actions")
    expect(page.locator("[data-testid=gear-selected-action-limit]")).to_contain_text(
        "Selected action limit: 8"
    )
    page.locator("[data-testid=gear-curve-picker]").click()
    page.get_by_role("option", name="0 actions", exact=True).click()
    expect(page.locator("[data-testid=gear-selected-action-limit]")).to_contain_text(
        "Selected action limit: 0"
    )
    expect(page.locator("[data-testid=gear-inventory-plan]")).to_contain_text("melee → magic")
    expect(page.locator("[data-testid=gear-melee-paperdoll] button")).to_have_count(11)
    expect(page.locator("[data-testid=gear-magic-paperdoll] button")).to_have_count(11)
    expect(page.locator("[data-testid=gear-diagnostics] .q-expansion-item__content")).to_be_hidden()
    page.locator("[data-testid=gear-melee-slot-weapon]").click()
    expect(page.locator("[data-testid=gear-melee-slot-detail]")).to_contain_text("Requirements:")
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator("[data-testid=gear-melee-slot-weapon]")).to_be_visible()
    page.wait_for_function(
        "document.querySelector('[data-testid=gear-swap-curve] .main-svg')"
        ".getBoundingClientRect().right <= innerWidth"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_label("Additional GP", exact=True).fill("100")
    expect(page.locator("[data-testid=gear-results]")).to_have_text("")
    assert "Inputs changed" in page.locator("body").inner_text()
    page.reload(wait_until="domcontentloaded")
    page.locator("[data-testid=gear-optimizer]").wait_for()
    page.get_by_text("Target and future assumptions", exact=True).click()
    expect(
        page.get_by_label("Future skill levels (one skill=level per line)", exact=True)
    ).to_have_value("")
