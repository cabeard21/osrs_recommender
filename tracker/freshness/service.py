"""Mapping practice evidence onto milestones — stage 4 of §12's pipeline (§6.7, §7.6).

**This module writes exactly one column: ``Milestone.last_practiced_at``.** That is not a
scope note, it is the design. §7.6 draws the whole distinction on which the practice-proxy
system rests — ``achieved`` is *"the user has established this skill before"* and
``last_practiced_at`` is *"the user recently exercised the general skill domain"* —
and permits a proxy to refresh the second **only** when all four of §7.6's conditions hold:
the signal proves relevant PvP activity occurred; the milestone declares that signal via
``practiced_by``; the proxy does not set ``achieved``; and the proxy does not claim
competence from mere participation. Conditions 3 and 4 are properties of *what this module
never does*, which is why the guarantee is worth stating as an absence and testing as one
(**G7**) — ``tests/freshness/test_service.py`` walks this file's AST and fails on any
assignment to ``achieved``.

**G1 follows from the same absence.** *"``achieved`` never transitions true → false from
the passage of time alone"* — this is the only module in the system where time and
milestone rows meet, so if it cannot write ``achieved``, no amount of elapsed clock can
clear one. The recommendation engine is pure and cannot; the merge layer never touches
``Milestone`` rows at all (Step 8b).

**Why the indirection exists.** §6.7: *"Integrations write ``PracticeEvent`` rows; the
freshness service maps events onto milestones. Client-side detection logic never touches
milestone rows directly."* Collapsing the two would put §7.6's four conditions in every
producer of evidence — the RuneLite plugin, the WOM importer, whatever comes next —
instead of in one place where they can be read together.

**The two functions are deliberately separate.** :func:`apply_practice_events` records the
evidence; :func:`materialize_freshness` derives the §6.6 band from it (A18). Step 9 runs
them in that order. Keeping them apart means the derived column is never something another
stage reasons from — it can be dropped and rebuilt at any time, which is what §6.6 means
by *"materialized for query convenience"*.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.content.loader import Content
from tracker.db.models import Milestone as MilestoneRow
from tracker.db.models import PracticeEvent
from tracker.domain.types import MilestoneClass, PracticeDomain, Source
from tracker.freshness.policy import freshness


@dataclass(frozen=True)
class FreshnessOutcome:
    """What one freshness pass did. Counts, not rows — the caller commits.

    ``events_unattributed`` is the interesting number: a plugin emitting a domain no
    milestone declares via ``practiced_by`` produces evidence that lands nowhere, and an
    outcome reporting only successful attributions would be indistinguishable from a
    corpus where nothing practices that domain.
    """

    milestones_refreshed: int = 0
    events_considered: int = 0
    events_unattributed: int = 0
    rows_created: int = 0


def _practicing_milestones(content: Content) -> dict[PracticeDomain, list[str]]:
    """Domain → the milestone ids that declare it, for ``class: execution`` only.

    The class filter is redundant against the content schema, which already refuses
    ``practiced_by`` on any other class, and is kept anyway: §6.6's rule that only
    execution milestones age is the kind of invariant that should fail closed in the module
    that would otherwise violate it, not only in the validator that runs at load time. A
    ``knowledge`` milestone given a practice timestamp would acquire a freshness band it is
    never allowed to have (§6.6, D8).
    """
    index: dict[PracticeDomain, list[str]] = defaultdict(list)
    for milestone in content.milestones.values():
        if milestone.class_ is not MilestoneClass.EXECUTION:
            continue
        for domain in milestone.practiced_by:
            index[domain].append(milestone.id)
    return dict(index)


def apply_practice_events(
    session: Session,
    player_id: int,
    content: Content,
    *,
    since: datetime | None = None,
) -> FreshnessOutcome:
    """Attribute ``PracticeEvent`` rows to milestones via ``practiced_by`` (§7.6).

    Each milestone takes the **latest** ``ended_at`` among the events whose domain it
    declares, and ``last_practiced_at`` only ever moves forward. Never backwards, for the
    reason G6 gives: a value that could decrease would turn a gap in our observations into
    evidence of decay, and *"absent evidence must never accelerate staleness."*

    A milestone with no row yet gets one — practice evidence about a milestone the player
    has never been asked about is still evidence. The new row carries ``achieved = False``
    and ``attested_at = NULL``, which is what keeps A7 intact: the leaf continues to
    resolve **unknown** ("never prompted"), not ``unsatisfied`` ("asked, said no"). Merely
    recording that someone played LMS must not become a statement that they have, or have
    not, established a skill.

    ``since`` bounds the scan for Step 9's incremental runs. Omitting it reprocesses the
    whole log, which is safe precisely because the write is a forward-only maximum: this
    function is idempotent, and re-running it after a restore cannot produce a different
    answer from the same events.
    """
    by_domain = _practicing_milestones(content)
    if not by_domain:
        return FreshnessOutcome()

    domains = list(by_domain)
    attributable = select(PracticeEvent).where(
        PracticeEvent.player_id == player_id,
        PracticeEvent.domain.in_(domains),
    )
    unattributable = select(PracticeEvent).where(
        PracticeEvent.player_id == player_id,
        PracticeEvent.domain.not_in(domains),
    )
    if since is not None:
        attributable = attributable.where(PracticeEvent.ended_at >= since)
        unattributable = unattributable.where(PracticeEvent.ended_at >= since)

    events = list(session.scalars(attributable))
    unattributed = len(list(session.scalars(unattributable)))

    #: milestone id → the latest practice instant attributable to it.
    latest: dict[str, datetime] = {}
    for event in events:
        for milestone_id in by_domain[event.domain]:
            current = latest.get(milestone_id)
            if current is None or event.ended_at > current:
                latest[milestone_id] = event.ended_at

    rows = {
        row.key: row
        for row in session.scalars(
            select(MilestoneRow).where(
                MilestoneRow.player_id == player_id, MilestoneRow.key.in_(list(latest))
            )
        )
    }

    refreshed = created = 0
    for milestone_id, practiced_at in latest.items():
        row = rows.get(milestone_id)
        if row is None:
            authored = content.milestones[milestone_id]
            row = MilestoneRow(
                player_id=player_id,
                key=milestone_id,
                kind=authored.kind,
                class_=authored.class_,
                achieved=False,
                attested_at=None,
                source=Source.DERIVED,
                observed_at=practiced_at,
            )
            session.add(row)
            created += 1
        elif row.last_practiced_at is not None and row.last_practiced_at >= practiced_at:
            continue

        row.last_practiced_at = practiced_at
        refreshed += 1

    session.flush()
    return FreshnessOutcome(
        milestones_refreshed=refreshed,
        events_considered=len(events),
        events_unattributed=unattributed,
        rows_created=created,
    )


def materialize_freshness(session: Session, player_id: int, now: datetime) -> int:
    """Recompute ``Milestone.freshness`` from ``last_practiced_at`` (A18, §6.6).

    A18 added the column because §6.6 calls it *"materialized for query convenience"* and
    nothing materialized it. This is that writer, and the data is derived in the strict
    sense: every value is a pure function of ``last_practiced_at``, the row's class and
    ``now``, so dropping the column and rebuilding it changes nothing. Nothing in the
    engine reads it — :mod:`tracker.progression.engine` calls
    :func:`tracker.freshness.policy.freshness` on the projected state directly — which is
    what stops a stale materialization from being able to corrupt a recommendation.

    The class comes from the stored row rather than from content: a milestone whose
    authored class changed after rows existed must be reclassed deliberately, not silently
    by whichever pass happens to run first after the edit.
    """
    rows = session.scalars(select(MilestoneRow).where(MilestoneRow.player_id == player_id)).all()

    written = 0
    for row in rows:
        band = freshness(row.last_practiced_at, now, row.class_)
        if row.freshness is not band:
            row.freshness = band
            written += 1

    session.flush()
    return written
