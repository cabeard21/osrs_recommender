"""§9.8's refresher candidates: one composite per practice group, never one per milestone.

Ungrouped refreshers produce technically accurate and completely useless coaching —
*"Refresh 4-way switches / Refresh overhead prayers / Refresh freeze logging / Refresh
DDing / Refresh offensive prayers"* — which is the failure D9 exists to prevent. Milestones
declare a ``practice_group`` (§10.3) and a refresher template is authored per group
(§10.4); when several members of a group have decayed, the engine emits **one** candidate
covering all of them.

Urgency (§9.8)
--------------

=========================  ==========================================
Freshness                  Urgency
=========================  ==========================================
``current``                0.00
``stale`` (30–90d)         0.40 → 0.70, linear in age
``very_stale`` (>90d)      0.70 → 1.00, linear to 270d, then clamped
=========================  ==========================================

::

    breadth_bonus = min(0.10, 0.03 × (member_count − 1))
    group_urgency = min(1.00, max(member_urgency) + breadth_bonus)

**The inner cap is the whole point.** Without it a group of twenty stale milestones
saturates at 1.0 on breadth alone, and urgency stops meaning *how decayed the worst thing
is* and starts meaning *how many boxes are unticked*. With it, a five-member and a
twenty-member group both contribute at most +0.10.

What a refresher is, in engine terms
------------------------------------

A refresher is **not** a :class:`~tracker.content.schema.Candidate`, and synthesizing one
would be a bug rather than a shortcut. Every candidate carries a ``completion`` predicate
that §16.2 tests before scoring, and the only predicate a refresher could plausibly carry —
*"these milestones are achieved"* — is **already satisfied**, since a milestone must be
achieved before it can decay. The refresher would evaluate ``completed`` on the very run it
was most needed and never rank at all. :class:`PracticeCandidate` therefore carries its
factors directly; the engine scores both kinds through the same §9.4 function.

Where urgency enters the score
------------------------------

§9.8 defines ``group_urgency`` and §9.4 lists five factors, but the SDD never joins them.
This module supplies ``urgency`` and the engine spends it as **proximity** — the factor
§9.4 glosses as *"closer is better"*. For a progression candidate, proximity is how much of
the work is already done; for a refresher, it is how far the practice has decayed, which is
the same question — *how close is this to being the right thing to do now?* — asked of a
different clock. A current group scores 0 there and sinks; a very stale one approaches 1.

The alternative, folding urgency into ``pvp_value``, is ruled out by §9.3's own worked
table: *"Practice vengeance timing"* is listed at **0.375**, which is exactly
``effective_weight(vengeance_pvp)`` under ``main_nh: 0.75, anti_pk: 0.25``. A refresher's
``pvp_value`` is its relevance and nothing else. Recorded as an open amendment candidate in
``plans/`` — the code ships a documented choice, not an invention.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from tracker.content.loader import Content
from tracker.content.schema import Milestone, RefresherTemplate, ScoringProfile
from tracker.domain.types import (
    CandidateKind,
    Freshness,
    MilestoneState,
    PlayerState,
    Recommendation,
)
from tracker.freshness.policy import STALE_AFTER, VERY_STALE_AFTER, freshness

#: §9.8's urgency anchors. The two band boundaries are imported rather than restated so
#: the curve cannot drift away from the policy that decides which band an age falls in.
_STALE_URGENCY = (0.40, 0.70)
_VERY_STALE_URGENCY = (0.70, 1.00)

#: Where ``very_stale`` urgency saturates (§9.8: *"linear to 270d, then clamped"*). Past
#: nine months, the difference between forgotten and very forgotten stops being actionable.
_SATURATION = timedelta(days=270)

#: Freshness as an ordering, for ``trigger.any_member_freshness_at_least`` (§10.4).
#: :class:`Freshness` is a plain ``Enum`` — deliberately, since nothing else compares its
#: members — so the one place that needs an order declares it here rather than promoting
#: the type and inviting arithmetic on it everywhere else.
_FRESHNESS_RANK: Mapping[Freshness, int] = {
    Freshness.CURRENT: 0,
    Freshness.STALE: 1,
    Freshness.VERY_STALE: 2,
}


@dataclass(frozen=True, slots=True)
class PracticeCandidate:
    """One composite refresher, ready to be scored beside progression candidates.

    ``members`` holds only the milestones that actually triggered — the bullets §9.8 puts
    under *"Practice:"*, and the exact set its *"mark session complete"* action refreshes.
    A current member of the same group is not listed, because a session claiming to refresh
    it would be attesting to practice that did not happen.
    """

    id: str
    name: str
    advances: Mapping[str, float]
    members: tuple[str, ...]
    urgency: float
    hours: float
    suggested_session: str


def member_urgency(state: MilestoneState, now: datetime) -> float:
    """§9.8's per-milestone urgency, or ``0.0`` where freshness does not apply.

    Reads the band from :func:`~tracker.freshness.policy.freshness` rather than deriving it
    from the age again, so a milestone this module calls urgent is one the freshness policy
    calls stale. ``knowledge`` and ``threshold`` milestones get ``None`` from that function
    and therefore ``0.0`` here: §6.6 says they do not age, and a refresher for something
    that cannot decay would be a session with no purpose.
    """
    band = freshness(state.last_practiced_at, now, state.class_)
    if band is None or band is Freshness.CURRENT or state.last_practiced_at is None:
        return 0.0

    age = now - state.last_practiced_at
    if band is Freshness.STALE:
        return _interpolate(age, STALE_AFTER, VERY_STALE_AFTER, _STALE_URGENCY)
    return _interpolate(age, VERY_STALE_AFTER, _SATURATION, _VERY_STALE_URGENCY)


def group_urgency(urgencies: Sequence[float], profile: ScoringProfile) -> float:
    """``min(1.00, max(member) + capped breadth bonus)`` (§9.8).

    The maximum, never the sum — the rule §9.3 applies to ``pvp_value``, for the same
    reason: breadth must not substitute for severity. Both caps are authored (§9.7), so the
    trade-off between *how stale* and *how many* is tunable without a code change.
    """
    if not urgencies:
        return 0.0
    policy = profile.refresher
    breadth = min(
        policy.breadth_bonus_cap,
        policy.breadth_bonus_per_extra_member * (len(urgencies) - 1),
    )
    return min(1.0, max(urgencies) + breadth)


def practice_candidates(
    state: PlayerState, content: Content, profile: ScoringProfile, now: datetime
) -> tuple[PracticeCandidate, ...]:
    """Every practice group whose decay has crossed its authored trigger (§10.4).

    Returned in descending urgency so the engine's list policy — *"at most one refresher in
    the primary list"* — keeps the most urgent group rather than whichever one the corpus
    happened to declare first. Ties break on id, so the output is stable across runs
    (§16.1).
    """
    candidates = [
        candidate
        for template in content.refreshers.values()
        if (candidate := _for_template(template, state, content, profile, now)) is not None
    ]
    return tuple(sorted(candidates, key=lambda entry: (-entry.urgency, entry.id)))


def _for_template(
    template: RefresherTemplate,
    state: PlayerState,
    content: Content,
    profile: ScoringProfile,
    now: datetime,
) -> PracticeCandidate | None:
    """One template's candidate, or ``None`` when nothing in its group has decayed enough."""
    triggered: list[tuple[Milestone, float]] = []
    for milestone in _group_members(content, template.practice_group):
        observed = state.milestones.get(milestone.id)
        if observed is None or not observed.achieved:
            # Not yet achieved is not decayed. A refresher for something the player has
            # never claimed would coach them to maintain what they do not have; acquiring
            # it is a progression concern, and G7 keeps practice evidence from asserting
            # the milestone on its own.
            continue
        band = freshness(observed.last_practiced_at, now, observed.class_)
        if band is None or not _meets(band, template.trigger.any_member_freshness_at_least):
            continue
        triggered.append((milestone, member_urgency(observed, now)))

    if not triggered:
        return None

    return PracticeCandidate(
        id=template.id,
        name=template.name,
        # §9.8: the composite *"inherits the maximum relevant capability value, never the
        # sum"*. A template names which capabilities its group serves but not by how much,
        # and 1.0 is the only honest reading of "serves": the maximum is then taken over
        # the blended weight map by the same `pvp_value` derivation every candidate uses,
        # so group size cannot reach relevance through this door.
        advances=dict.fromkeys(template.advances, 1.0),
        members=tuple(milestone.id for milestone, _ in triggered),
        urgency=group_urgency([urgency for _, urgency in triggered], profile),
        hours=template.suggested_session_hours,
        suggested_session=template.suggested_session,
    )


def _group_members(content: Content, group: str) -> tuple[Milestone, ...]:
    """The corpus's members of one practice group, in id order for stable bullet lists.

    Only ``class: execution`` milestones can be here at all — ``Milestone`` refuses
    ``practice_group`` on any other class (§10.7) — so no filter is needed and none is
    written; a redundant one would suggest the invariant were in doubt.
    """
    return tuple(
        sorted(
            (m for m in content.milestones.values() if m.practice_group == group),
            key=lambda milestone: milestone.id,
        )
    )


def _meets(band: Freshness, threshold: Freshness) -> bool:
    return _FRESHNESS_RANK[band] >= _FRESHNESS_RANK[threshold]


def _interpolate(
    age: timedelta, start: timedelta, end: timedelta, bounds: tuple[float, float]
) -> float:
    """Linear position of ``age`` within a band, mapped onto that band's urgency range.

    Clamped at both ends: ``very_stale`` runs past its own saturation point by design
    (§9.8), and an age exactly at the lower boundary must give the band's floor rather than
    a negative fraction of it.
    """
    low, high = bounds
    span = (end - start).total_seconds()
    position = (age - start).total_seconds() / span if span > 0 else 1.0
    return low + (high - low) * min(max(position, 0.0), 1.0)


def enforce_list_policy(
    ranked: Iterable[Recommendation], profile: ScoringProfile
) -> tuple[tuple[Recommendation, ...], tuple[Recommendation, ...]]:
    """Split a ranking into §9.8's primary list and its deferred refreshers (**G10**).

    *"At most one refresher in the primary recommendation list"*, with the count authored
    (§9.7) rather than fixed at one in code. Applied **after** scoring, never before: a
    refresher that would have ranked second is genuinely second, and suppressing it earlier
    would hide that from the Practice freshness view §9.8 sends it to.

    Order within each half is preserved, so the primary list keeps its ranking and the
    deferred refreshers keep theirs.
    """
    primary: list[Recommendation] = []
    deferred: list[Recommendation] = []
    kept = 0

    for entry in ranked:
        if entry.kind is not CandidateKind.PRACTICE:
            primary.append(entry)
            continue
        if kept < profile.refresher.max_in_primary_list:
            primary.append(entry)
            kept += 1
        else:
            deferred.append(entry)

    return tuple(primary), tuple(deferred)
