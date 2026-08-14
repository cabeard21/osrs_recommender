"""§22's general advisor: the pure half.

Everything in this package is pure in §16.1's sense — no database session, no network, no
``datetime.now()``. That is not a style preference; it is how **D15** is enforced rather than
merely intended. Tool dispatch is handed a frozen snapshot, so there is no session for a
future edit to write through and no client for one to fetch with, and the guarantee holds by
construction instead of by review.

Seven things must never happen, and they are restated here because this is the module a
reader lands on first:

1. No advisor output reaches :class:`~tracker.domain.types.Recommendation`,
   ``RecommendationEntry`` (including its ``reason``, ``factors``, ``bands`` and
   ``consequences``), :class:`~tracker.domain.types.Estimate`, ``CapabilityState``,
   ``Milestone``, or any §9.4 factor. (D14)
2. No advisor tool writes anything.
3. No tool ranks, estimates or evaluates a capability from model-supplied arguments. (D15)
4. ``tracker.progression``, ``tracker.recommendations``, ``tracker.estimation`` and
   ``tracker.domain`` never import this package.
5. This package never imports ``tracker.db`` or ``sqlalchemy``.
6. An install with the advisor off ranks, estimates, syncs and renders byte-identically to
   one with it on.
7. Any advisor failure degrades to a message in the conversation and changes nothing else.

(4) and (5) are asserted by ``tests/advisor/test_import_boundary.py`` over the AST, and (2)
by ``tests/advisor/test_tools_are_read_only.py``.

Note the division of labour with :mod:`tracker.sync.advisor`: the session reads that produce
a snapshot's inputs — projecting the player, computing capability states, reading back the
latest persisted run, loading the price cache — happen *there*, and this package receives the
results. :func:`~tracker.advisor.snapshot.build_advisor_snapshot` is a pure assembler, not a
query.
"""

from __future__ import annotations

from tracker.advisor.snapshot import (
    AdvisorSnapshot,
    ObservationAge,
    PriceFact,
    RankedTask,
    build_advisor_snapshot,
)

__all__ = [
    "AdvisorSnapshot",
    "ObservationAge",
    "PriceFact",
    "RankedTask",
    "build_advisor_snapshot",
]
