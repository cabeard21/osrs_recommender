"""§7.5's attribution footer text."""

from __future__ import annotations

from tracker.integrations.prices.attribution import PRICE_ATTRIBUTION


def test_attribution_names_the_provider_and_the_staleness_caveat() -> None:
    assert "OSRS Wiki" in PRICE_ATTRIBUTION
    assert "RuneLite" in PRICE_ATTRIBUTION
    assert "stale" in PRICE_ATTRIBUTION
