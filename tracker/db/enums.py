"""Persistence-only enums (§6).

``tracker/domain/types.py`` owns the enums the *engine* reasons over — the ones whose
values feed Kleene evaluation (§9.1) or the three status layers (§4.4). This module holds
the handful of enums that appear only in the schema: they describe storage or provenance
concerns a few SDD tables define with their own value sets, and reusing a domain enum for
them would either be wrong (a different set of members) or would blur a distinction the
SDD draws deliberately. Each is cited against the table that defines it.

One is easy to mistake for a domain type that already exists and is *not* the same thing:
``PracticeEventConfidence`` (§6.7) is two-valued (``high | medium``) — practice evidence
is never *low* confidence, it simply isn't recorded. ``tracker.domain.types.Confidence``
is three-valued and ordered for a threshold comparison (§6.9); reusing it here would let
a ``low`` value round-trip through the database with nothing to stop it.

**``PriceSelectionPolicy`` and ``PriceSourceLayer`` are re-exports, not definitions.**
They moved to :mod:`tracker.domain.types` when §8.3's cascade was implemented: they are
that cascade's *output* vocabulary, and :mod:`tracker.estimation.prices` — which produces
them — may not import :mod:`tracker.db` under §16.1. Persistence merely records what the
estimator decided, so the definition belongs on the estimator's side of that boundary.
The re-export keeps ``from tracker.db.enums import PriceSourceLayer`` working at every
existing call site, which is where the §6.8 columns are declared.
"""

from __future__ import annotations

from enum import Enum

from tracker.domain.types import PriceSelectionPolicy, PriceSourceLayer

__all__ = [
    "PracticeEventConfidence",
    "PriceSelectionPolicy",
    "PriceSourceLayer",
    "RecommendationCandidateKind",
]


class PracticeEventConfidence(Enum):
    """§6.7 — how strongly a practice signal implies real PvP activity occurred.

    Deliberately two-valued. §7.6's signal table never assigns ``low`` to any accepted
    signal; a signal too weak to imply practice is rejected outright rather than recorded
    at low confidence (§7.6: "Player merely enters the Wilderness" -> nothing).
    """

    HIGH = "high"
    MEDIUM = "medium"


class RecommendationCandidateKind(Enum):
    """§6.10 — whether a ranked entry is an ordinary candidate or a synthesized refresher.

    Not to be confused with ``tracker.domain.types.CandidateKind`` (§10.6), which
    distinguishes *how* a candidate changes facts (``skill_training | acquisition |
    quest | unlock | practice``). This is the orthogonal axis §6.10 actually names:
    whether the candidate was authored content or generated from a stale practice group
    (§9.8), which is what the "at most one refresher in the primary list" policy checks.
    """

    PROGRESSION = "progression"
    REFRESHER = "refresher"
