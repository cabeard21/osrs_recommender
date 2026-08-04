"""The §6.6 freshness policy, as a pure function.

| Time since ``last_practiced_at`` | Freshness |
|---|---|
| < 30 days | ``current`` |
| 30–90 days | ``stale`` |
| > 90 days | ``very_stale`` |

Two boundaries the table leaves implicit are fixed here, by reading §6.6's own notation:
``30–90 days`` is an inclusive range and ``very_stale`` is strictly *"> 90 days"*, so
exactly 30 days is ``stale`` and exactly 90 days is **still** ``stale``.

**The policy applies to ``class: execution`` milestones and nothing else** (§6.6).
``knowledge`` is understanding, once acquired; ``threshold`` is a thing that happened.
Neither ages, and :func:`freshness` returns ``None`` for both rather than a band the
caller might act on.

**Freshness is never a blocker.** It cannot set ``achieved`` back to false (G1) and it
cannot reach ``CapabilityState.status`` (G2, D8). Its only outputs are
``readiness_confidence``, ``recommended_now`` and refresher candidates — all computed
strictly after ``status``, in :mod:`tracker.progression.engine`.

Kept in its own package because the freshness *service* (Step 8c) maps practice events
onto milestones and writes rows; that is I/O, and this is the rule it applies. The pure
half is what the progression engine imports, so §16.1's purity boundary holds without
the engine reaching into a service.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from tracker.domain.types import Freshness, MilestoneClass

#: §6.6's two boundaries. Game-behaviour constants, not tuning knobs: they say what
#: "recently practiced" means, which is why they are here and not in ``profile.yaml``
#: alongside ``observation_aged_days`` (§9.7, §10.8).
STALE_AFTER = timedelta(days=30)
VERY_STALE_AFTER = timedelta(days=90)


def classify_age(age: timedelta) -> Freshness:
    """Band a practice age, with no reference to milestone class.

    Callers that must respect §6.6's class gate want :func:`freshness`. This exists for
    §6.9's third warning generator, which puts an *informational* staleness note on
    ``class: knowledge`` milestones — a note §6.6 permits while forbidding any readiness
    effect. Keeping one band table means the note cannot drift from the policy it
    describes; keeping it a separate function means no caller reaches the note's leniency
    by accident.

    A negative age — a practice timestamp in the future, which a clock skew between the
    plugin and the server can produce — is ``current``. It is not evidence of decay.

    Note the asymmetric comparisons: ``>= STALE_AFTER`` but ``> VERY_STALE_AFTER``. §6.6
    writes the middle band as the inclusive range *"30–90 days"*, so both boundaries
    belong to ``stale``.
    """
    if age > VERY_STALE_AFTER:
        return Freshness.VERY_STALE
    if age >= STALE_AFTER:
        return Freshness.STALE
    return Freshness.CURRENT


def freshness(
    last_practiced_at: datetime | None,
    now: datetime,
    milestone_class: MilestoneClass,
) -> Freshness | None:
    """Practice freshness for one milestone (§6.6), or ``None`` where it does not apply.

    ``None`` covers the two cases in which the caller must not downgrade anything:

    * **The milestone does not age** — ``knowledge`` or ``threshold`` (§6.6).
    * **There is no practice evidence at all.** No ``last_practiced_at`` means no
      practice event has ever been attributed to this milestone, which is a statement
      about our observations rather than about the player. Returning ``very_stale`` there
      would convert absence of evidence into evidence of decay — the §4.5 error, and
      exactly what G6 forbids: *"absent evidence never accelerates staleness."* A player
      who attested a milestone before any practice tracking existed is not less ready
      than one who attested it yesterday.

    Both datetimes must agree on timezone-awareness; the engine passes an aware ``now``.
    """
    if milestone_class is not MilestoneClass.EXECUTION:
        return None
    if last_practiced_at is None:
        return None
    return classify_age(now - last_practiced_at)
