"""Outbound HTTP integrations (§7): the OSRS Wiki prices feed and Wise Old Man.

Deliberately empty of re-exports — import from the submodules:

* :mod:`tracker.integrations.http` — shared transport, retry schedule, circuit breaker
* :mod:`tracker.integrations.prices` — OSRS Wiki real-time prices (§7.5, §8.3)
* :mod:`tracker.integrations.wise_old_man` — Wise Old Man (§7.2)
* :mod:`tracker.integrations.hiscores` — contingency documentation only (§7.3); no code

**Every client here returns DTOs and persists nothing.** Step 9's orchestration
pipeline owns all writes; this package must never import :mod:`tracker.db`. That
mirrors §16.1's purity mandate — "the recommendation engine is a pure function over a
state object" — one layer further out, at the network boundary instead of the engine
boundary.
"""
