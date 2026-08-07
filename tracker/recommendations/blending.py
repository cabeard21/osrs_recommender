"""§9.3's effective capability-weight map — the engine's entry to roadmap blending.

§14 names ``tracker/recommendations/`` as the home of *"roadmap blending"*, and this is
that module. The implementation itself lives one layer down, in
:func:`tracker.domain.candidates.effective_capability_weights`, because ``pvp_value`` is
derived from the blended map and both halves shipped together in Step 2.5 — splitting them
across packages would have put a derivation and its only input on opposite sides of a seam
neither needed.

Re-exporting rather than reimplementing is the point. Two copies of a convex combination
would agree today and drift the first time one of them learned something about a missing
roadmap; §9.3's *"blend the capability map first, **then** take the maximum"* is only a
rule if there is exactly one blend to be first.

What §9.3 guarantees, and why the engine may rely on it without a second normalization:

* Selection weights are normalized to sum to 1 at read time
  (:meth:`~tracker.domain.types.RoadmapSelection.normalized`).
* Each roadmap's capability weights lie in [0,1] — enforced by ``Roadmap`` (§10.7).
* The result is therefore a **convex combination**, automatically in [0,1].

A capability in two roadmaps blends, never accumulates: ``0.75(1.0) + 0.25(0.8) = 0.95``,
never ``1.8`` (D3). The maximum across roadmaps is explicitly not used — a max rule would
let every candidate be read under whichever roadmap flatters it most, which makes the
selection weights the user set mean nothing.
"""

from __future__ import annotations

from tracker.domain.candidates import effective_capability_weights

__all__ = ["effective_capability_weights"]
