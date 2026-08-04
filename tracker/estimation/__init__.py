"""Time and GP estimation (§8) — a subsystem, not a formula.

Deliberately empty of re-exports — import from the submodules:

* :mod:`tracker.estimation.xp_table` — the OSRS XP curve, levels 1–99 (§8.2)
* :mod:`tracker.estimation.methods` — level-band partitioning and method selection (§8.2)
* :mod:`tracker.estimation.prices` — the §8.3 cascade and §8.4's trade-age confidence
* :mod:`tracker.estimation.estimate` — ``estimate(candidate, ...) -> Estimate``

Pure, and mechanically so: ``tests/progression/test_import_boundary.py`` walks the AST of
every module here and fails on an import of ``tracker.db``, ``tracker.api``, ``httpx`` or
``sqlalchemy`` (§16.1). Prices are handed in already fetched; nothing here has a clock.
"""
