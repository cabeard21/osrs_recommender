"""OSRS Wiki real-time prices (§7.5, §8.3, D2, D10).

Deliberately empty of re-exports — import from the submodules:

* :mod:`tracker.integrations.prices.client` — the live fetch, ``PriceDTO``
* :mod:`tracker.integrations.prices.scope` — authored Gear market item IDs
* :mod:`tracker.integrations.prices.cache` — the three-layer resolution cascade
* :mod:`tracker.integrations.prices.attribution` — the §7.5 footer string
"""
