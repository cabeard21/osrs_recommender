"""The §7.5 attribution string, for Step 11's settings-page footer.

Kept as a constant, not composed from ``PricesSettings``, because §7.5 fixes the exact
wording as a condition of using the feed — it is not something a deployer's config
should be able to alter.
"""

from __future__ import annotations

PRICE_ATTRIBUTION = (
    "Market prices provided by the OSRS Wiki real-time prices API and RuneLite "
    "contributors. Prices are estimates and may be stale for low-volume items."
)
