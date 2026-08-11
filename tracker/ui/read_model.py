"""Database reads for the UI — the only place a page touches a session.

The pages are render functions over the frozen rows in :mod:`tracker.ui.view_model`; this
module is what produces those rows. Splitting them buys two things.

First, **no ORM object reaches a template.** A detached row emits a query on attribute
access, and a page that lazily loads while rendering does so inside NiceGUI's event loop,
where the failure surfaces as a blank card rather than as an error. Every function here
returns frozen dataclasses read inside one open session.

Second, the §15 honesty rules stay testable. What "unknown" renders as, and whether an
unranked skill can show a level, are decided in ``view_model``; this module only supplies
the facts. So a test can assert the rules without a database and assert the reads without a
browser.

This module sits **outside** §16.1's purity boundary and may import ``tracker.db`` freely —
it is UI, not engine. The boundary test covers ``tracker/{progression,recommendations,
estimation,domain}/`` and deliberately not this package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.content.requirements import iter_leaves
from tracker.db.enums import RecommendationCandidateKind
from tracker.db.models import (
    CapabilityState,
    ContainerScan,
    Player,
    RecommendationEntry,
    RecommendationSnapshot,
    SkillSnapshot,
    Unlock,
)
from tracker.db.models import Milestone as MilestoneRow
from tracker.db.projection import build_player_state
from tracker.db.repository import (
    clear_active_roadmap,
    current_skill_snapshots,
    get_active_roadmaps,
    get_container_scans,
    get_player,
    get_player_by_username,
    get_unlocks,
    set_active_roadmap,
)
from tracker.domain.types import (
    Container,
    GpSensitivity,
    LeafRef,
    MilestoneKind,
    Source,
    Status,
    UnlockState,
)
from tracker.recommendations.refreshers import practice_candidates
from tracker.ui.staleness import humanize_age, scan_note
from tracker.ui.view_model import (
    BlockedRecommendationRow,
    CapabilityRow,
    DashboardView,
    FactorDiffRow,
    HistorySnapshotRow,
    PracticeGroupRow,
    PracticeMemberRow,
    RecommendationEntryRow,
    RecommendationRow,
    RoadmapOptionRow,
    RoadmapProgressRow,
    SettingsView,
    SkillRow,
    SkillXpPoint,
    UnlockRow,
    capability_row,
    recommendation_entry_row,
    skill_row,
    unlock_row,
)

#: Containers §15 reports staleness for on the dashboard. Equipment is observed on nearly
#: every tick while the plugin runs; the bank is the one whose age routinely reaches weeks,
#: and it is the one §6.5 uses as its worked example.
DASHBOARD_SCAN_CONTAINERS = (Container.BANK, Container.EQUIPMENT)

#: What a capability with no ``capability_state`` row says for its third layer. Phrased as
#: a fact about *our* records rather than about the account, per §4.5.
NEVER_COMPUTED_REASON = "no sync has been processed for this account yet"


def _leaf_refs(raw: Sequence[object]) -> tuple[LeafRef, ...]:
    """Rebuild ``LeafRef``s from the JSON ``CapabilityState`` stores.

    Missing keys are tolerated with empty defaults rather than raising. These columns are a
    *projection* that Step 9 rewrites on every pipeline run (§6.9), so a row written under
    an older shape is a stale cache entry, not corruption — and a dashboard that raised on
    one would take the whole page down rather than the one capability that is about to be
    recomputed anyway.
    """
    refs: list[LeafRef] = []
    for item in raw:
        if not isinstance(item, Mapping):  # pragma: no cover — JSON column, list of objects
            continue
        target = item.get("target")
        refs.append(
            LeafRef(
                leaf_type=str(item.get("leaf_type", "")),
                key=str(item.get("key", "")),
                description=str(item.get("description", "")),
                target=target if isinstance(target, int) else None,
            )
        )
    return tuple(refs)


def capability_rows(
    session: Session, player_id: int, content: Content
) -> tuple[CapabilityRow, ...]:
    """Every capability the corpus declares, in content order, with its stored state.

    Driven by **content** rather than by the ``capability_state`` table so that a capability
    with no row yet renders as ``unknown`` instead of vanishing. A missing row means the
    pipeline has not run for it, which is the definition of "we do not know" — and §15's
    whole complaint is about states that quietly disappear or read as "no".
    """
    stored = {
        row.capability_id: row
        for row in session.scalars(
            select(CapabilityState).where(CapabilityState.player_id == player_id)
        )
    }

    rows: list[CapabilityRow] = []
    for capability_id, capability in content.capabilities.items():
        state = stored.get(capability_id)
        if state is None:
            rows.append(
                capability_row(
                    capability_id=capability_id,
                    name=capability.name,
                    status=Status.UNKNOWN,
                    unlock_fraction=0.0,
                    blockers=(),
                    unknowns=(),
                    readiness=None,
                    warnings=(),
                    recommended_now=False,
                    recommended_now_reason=NEVER_COMPUTED_REASON,
                )
            )
            continue

        rows.append(
            capability_row(
                capability_id=capability_id,
                name=capability.name,
                status=state.status,
                unlock_fraction=state.unlock_fraction,
                blockers=_leaf_refs(state.blockers),
                unknowns=_leaf_refs(state.unknowns),
                readiness=state.readiness_confidence,
                warnings=tuple(state.warnings),
                recommended_now=state.recommended_now,
                recommended_now_reason=state.recommended_now_reason,
            )
        )
    return tuple(rows)


def referenced_unlock_keys(content: Content) -> tuple[str, ...]:
    """Every ``unlock:`` key any capability requirement mentions, sorted.

    The union with the player's stored rows is what gives the unlocks view its ``unknown``
    state. §6.3 has no unlock registry — keys are free-form and appear only inside
    requirement trees and sync payloads — so a key the corpus needs but no sync has ever
    reported has *no row at all*, and "no row" is exactly §4.5's ambiguity: never observed,
    not observed-as-absent.
    """
    keys: set[str] = set()
    for capability in content.capabilities.values():
        if capability.requires is None:
            continue
        for leaf in iter_leaves(capability.requires):
            if leaf.type == "unlock":
                keys.add(leaf.key)
    return tuple(sorted(keys))


def unlock_rows(session: Session, player_id: int, content: Content) -> tuple[UnlockRow, ...]:
    """The four-state unlock cards: stored rows, plus every referenced key with no row."""
    stored: dict[str, Unlock] = {row.key: row for row in get_unlocks(session, player_id)}
    keys = sorted(set(stored) | set(referenced_unlock_keys(content)))
    return tuple(
        unlock_row(key, stored[key].state if key in stored else UnlockState.UNKNOWN) for key in keys
    )


def skill_rows(session: Session, player_id: int, content: Content) -> tuple[SkillRow, ...]:
    """One row per skill snapshot, ranked first and highest first.

    Names and combat flags come from content where the id resolves; a snapshot for a skill
    the corpus does not declare still renders, under a titled id. §10.7 makes that
    unreachable through the corpus, but a sync payload names skills freely, and dropping
    one here would hide an observed fact because a *content* file omitted it.
    """
    snapshots: Sequence[SkillSnapshot] = current_skill_snapshots(session, player_id)
    skills = content.skills

    rows = [
        skill_row(
            skill_id=snapshot.skill,
            name=(
                skills[snapshot.skill].name
                if snapshot.skill in skills
                else snapshot.skill.replace("_", " ").title()
            ),
            is_combat=skills[snapshot.skill].is_combat if snapshot.skill in skills else False,
            level=snapshot.level,
            xp=snapshot.xp,
        )
        for snapshot in snapshots
    ]
    # Ranked before unranked, then by level. Sorting unranked rows by their stored `level`
    # would place them where their nominal 1 falls, reintroducing into the *ordering* the
    # very number §6.2 says must not be shown.
    rows.sort(key=lambda row: (not row.is_ranked, -(row.level or 0), row.name))
    return tuple(rows)


def latest_snapshot(session: Session, player_id: int) -> RecommendationSnapshot | None:
    """The most recent §6.10 snapshot, or ``None`` before the first pipeline run."""
    return session.scalar(
        select(RecommendationSnapshot)
        .where(RecommendationSnapshot.player_id == player_id)
        .order_by(RecommendationSnapshot.run_at.desc(), RecommendationSnapshot.id.desc())
        .limit(1)
    )


def current_goal(session: Session, player_id: int, content: Content) -> RecommendationRow | None:
    """§15's "current goal": the top-ranked unblocked entry of the latest snapshot.

    Derived, never stored. §15 names a current goal and §6 defines no model for one, so the
    honest reading is that it *is* the head of the latest ranking — and §9.9's hysteresis
    already gives that head the stability the word "goal" implies. A dedicated table would
    be a second answer to the same question, free to disagree with the first.

    Blocked entries are skipped for the reason §9.4 keeps them out of the ranking: they are
    surfaced so the user knows why, not offered as the thing to do next.
    """
    snapshot = latest_snapshot(session, player_id)
    if snapshot is None:
        return None

    entry = session.scalar(
        select(RecommendationEntry)
        .where(
            RecommendationEntry.snapshot_id == snapshot.id,
            RecommendationEntry.blocked.is_(False),
        )
        .order_by(RecommendationEntry.rank.asc())
        .limit(1)
    )
    if entry is None:
        return None

    candidate = content.candidates.get(entry.candidate_id)
    return RecommendationRow(
        candidate_id=entry.candidate_id,
        name=candidate.name if candidate is not None else entry.candidate_id,
        reason=entry.reason,
        estimated_hours=entry.estimated_hours,
        estimated_gp=entry.estimated_gp,
        confidence=entry.estimate_confidence,
    )


def roadmap_progress(
    session: Session, player_id: int, content: Content, rows: Sequence[CapabilityRow]
) -> tuple[RoadmapProgressRow, ...]:
    """Per-roadmap unlocked counts, ordered by the §4.3 selection weight (primary first).

    Counted over ``status is UNLOCKED`` only. ``unknown`` deliberately does not count as
    partial progress: §4.4 keeps unknown off the locked-to-unlocked scale entirely, and a
    bar that crept upward as evidence went missing would be the "backward progress" the
    three-layer split exists to prevent.
    """
    by_id = {row.capability_id: row for row in rows}
    progress: list[RoadmapProgressRow] = []
    for active in get_active_roadmaps(session, player_id):
        roadmap = content.roadmaps.get(active.roadmap_id)
        if roadmap is None:  # pragma: no cover — §10.7 rejects a corpus missing a roadmap
            continue
        capability_ids = tuple(roadmap.capabilities)
        unlocked = sum(
            1
            for capability_id in capability_ids
            if capability_id in by_id and by_id[capability_id].status is Status.UNLOCKED
        )
        progress.append(
            RoadmapProgressRow(
                roadmap_id=active.roadmap_id,
                name=roadmap.name,
                selection_weight=active.selection_weight,
                unlocked=unlocked,
                total=len(capability_ids),
            )
        )
    progress.sort(key=lambda row: (-row.selection_weight, row.name))
    return tuple(progress)


def staleness_notes(session: Session, player_id: int, now: datetime) -> tuple[str, ...]:
    """§6.5 sentences for the dashboard's containers, never-scanned ones included.

    A container with no scan row still produces a note. That is the whole point of §6.5's
    ``ContainerScan``: silence about a container we have never opened is indistinguishable
    from silence about one we opened a minute ago, and only one of those is good news.
    """
    scans: dict[Container, ContainerScan] = {
        scan.container: scan for scan in get_container_scans(session, player_id)
    }
    return tuple(
        scan_note(container, scans[container].scanned_at if container in scans else None, now)
        for container in DASHBOARD_SCAN_CONTAINERS
    )


def dashboard_view(
    session: Session, player_id: int, content: Content, now: datetime
) -> DashboardView:
    """Assemble §15's dashboard in one pass over the player's stored state."""
    player: Player | None = get_player(session, player_id)
    rows = capability_rows(session, player_id, content)

    last_sync = (
        f"synced {humanize_age(player.last_sync_at, now)}"
        if player is not None and player.last_sync_at is not None
        else "never synced — start RuneLite with the companion plugin"
    )

    return DashboardView(
        display_name=player.display_name if player is not None else "unknown account",
        combat_level=player.combat_level if player is not None else None,
        quest_points=player.quest_points if player is not None else None,
        last_sync_at_label=last_sync,
        unlocked_capabilities=sum(1 for row in rows if row.status is Status.UNLOCKED),
        total_capabilities=len(rows),
        unknown_capabilities=sum(1 for row in rows if row.status is Status.UNKNOWN),
        roadmaps=roadmap_progress(session, player_id, content, rows),
        current_goal=current_goal(session, player_id, content),
        staleness_notes=staleness_notes(session, player_id, now),
    )


# ---------------------------------------------------------------------------
# Step 11 — Recommendations (§9.10, §15)
# ---------------------------------------------------------------------------


def _candidate_unlocks_and_advances(
    content: Content, candidate_id: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """§9.10's "Unlocks"/"Advances" lines for a progression candidate.

    "Unlocks" is read from ``grants_facts``'s ``unlock:`` leaves (§10.6) — the ``unlock``
    *keys* the candidate would grant, not the capabilities. "Advances" is the candidate's
    ``advances`` map (§10.6), sorted by weight so the strongest relationship reads first.
    Both are read straight off content; neither is composed here.
    """
    candidate = content.candidates.get(candidate_id)
    if candidate is None:
        return (), ()
    unlocks: tuple[str, ...] = ()
    if candidate.grants_facts is not None:
        unlocks = tuple(
            leaf.key.replace("_", " ").title()
            for leaf in iter_leaves(candidate.grants_facts)
            if leaf.type == "unlock"
        )
    advances = tuple(
        content.capabilities[capability_id].name
        for capability_id, _weight in sorted(
            candidate.advances.items(), key=lambda item: (-item[1], item[0])
        )
        if capability_id in content.capabilities
    )
    return unlocks, advances


def _refresher_advances(content: Content, template_id: str) -> tuple[str, ...]:
    """§9.10's "Advances" line for a refresher, from its authored ``advances`` tuple."""
    template = content.refreshers.get(template_id)
    if template is None:
        return ()
    return tuple(
        content.capabilities[capability_id].name
        for capability_id in template.advances
        if capability_id in content.capabilities
    )


def _live_practice_group(
    session: Session, player_id: int, content: Content, template_id: str, now: datetime
) -> tuple[str, ...]:
    """The stale members a refresher entry would refresh, recomputed live (§9.8).

    Not persisted on ``RecommendationEntry`` (§6.10 stores the score's inputs, not the
    membership) — recomputed through the same pure
    :func:`~tracker.recommendations.refreshers.practice_candidates` the engine scored, so
    the bullet list can never name a milestone the engine did not actually consider stale.
    """
    state = build_player_state(session, player_id)
    for candidate in practice_candidates(state, content, content.profile, now):
        if candidate.id == template_id:
            return tuple(
                content.milestones[key].name if key in content.milestones else key
                for key in candidate.members
            )
    return ()


def recommendation_rows(
    session: Session, player_id: int, content: Content, now: datetime
) -> tuple[RecommendationEntryRow, ...]:
    """§15's primary ranked list: the latest snapshot's unblocked entries, in rank order.

    This is the persisted ranking, not a recomputation (§9.9's hysteresis and §9.8's list
    policy already ran when the snapshot was written) — reading it back is what keeps the
    displayed order identical to the one the engine actually produced.
    """
    snapshot = latest_snapshot(session, player_id)
    if snapshot is None:
        return ()
    entries = session.scalars(
        select(RecommendationEntry)
        .where(
            RecommendationEntry.snapshot_id == snapshot.id, RecommendationEntry.blocked.is_(False)
        )
        .order_by(RecommendationEntry.rank.asc())
    ).all()

    rows: list[RecommendationEntryRow] = []
    for entry in entries:
        is_refresher = entry.candidate_kind is RecommendationCandidateKind.REFRESHER
        candidate = content.candidates.get(entry.candidate_id)
        template = content.refreshers.get(entry.candidate_id)
        name = (
            candidate.name
            if candidate is not None
            else (template.name if template is not None else entry.candidate_id)
        )
        if is_refresher:
            unlocks: tuple[str, ...] = ()
            advances = _refresher_advances(content, entry.candidate_id)
            members = _live_practice_group(session, player_id, content, entry.candidate_id, now)
            suggested_session = template.suggested_session if template is not None else None
        else:
            unlocks, advances = _candidate_unlocks_and_advances(content, entry.candidate_id)
            members = ()
            suggested_session = None

        rows.append(
            recommendation_entry_row(
                candidate_id=entry.candidate_id,
                rank=entry.rank,
                name=name,
                is_refresher=is_refresher,
                score=entry.score,
                factors=entry.factors,
                reason=entry.reason,
                estimated_hours=entry.estimated_hours,
                estimated_gp=entry.estimated_gp,
                confidence=entry.estimate_confidence,
                unlocks=unlocks,
                advances=advances,
                practice_members=members,
                suggested_session=suggested_session,
            )
        )
    return tuple(rows)


def blocked_recommendation_rows(
    session: Session, player_id: int, content: Content
) -> tuple[BlockedRecommendationRow, ...]:
    """§15's collapsed "blocked" section — every entry the latest snapshot marked ``blocked``."""
    snapshot = latest_snapshot(session, player_id)
    if snapshot is None:
        return ()
    entries = session.scalars(
        select(RecommendationEntry)
        .where(
            RecommendationEntry.snapshot_id == snapshot.id, RecommendationEntry.blocked.is_(True)
        )
        .order_by(RecommendationEntry.candidate_id.asc())
    ).all()
    return tuple(
        BlockedRecommendationRow(
            candidate_id=entry.candidate_id,
            name=(
                content.candidates[entry.candidate_id].name
                if entry.candidate_id in content.candidates
                else entry.candidate_id
            ),
        )
        for entry in entries
    )


# ---------------------------------------------------------------------------
# Step 11 — Practice freshness (§9.8, §15)
# ---------------------------------------------------------------------------


def stale_practice_groups(
    session: Session, player_id: int, content: Content, now: datetime
) -> tuple[PracticeGroupRow, ...]:
    """Every practice group whose decay has crossed its trigger, most urgent first (§9.8).

    All of them — not just the ones the primary list excluded. §15 routes refreshers
    *beyond the first* here; :func:`primary_refresher_id` is what a caller subtracts to get
    "the rest". Keeping this function total over every triggered group (rather than
    pre-filtering) is what makes it independently testable against §9.8's grouping rules,
    without also depending on which one last happened to rank first.

    **Members are narrowed to the self-attested set.** A milestone whose freshness a
    plugin-derived signal can restore (``kind: derived``) refreshes with *no prompt at
    all* the moment matching evidence arrives (§9.8, §7.6) — that write happens earlier in
    the pipeline, in :mod:`tracker.freshness.service`, before this view ever renders. A
    derived milestone appearing here promptable would invite a manual tap to stand in for
    evidence nobody actually observed, which is the exact confirmation-for-derived-evidence
    §9.8 rules out.
    """
    state = build_player_state(session, player_id)
    candidates = practice_candidates(state, content, content.profile, now)
    return tuple(
        PracticeGroupRow(
            template_id=candidate.id,
            name=candidate.name,
            suggested_session=candidate.suggested_session,
            suggested_session_hours=candidate.hours,
            urgency=candidate.urgency,
            members=tuple(
                PracticeMemberRow(
                    key=key,
                    name=content.milestones[key].name if key in content.milestones else key,
                )
                for key in candidate.members
                if key in state.milestones
                and state.milestones[key].kind is MilestoneKind.SELF_ATTESTED
            ),
        )
        for candidate in candidates
    )


def primary_refresher_id(session: Session, player_id: int) -> str | None:
    """The one refresher (if any) currently shown in the primary list (G10).

    Read from the persisted snapshot rather than recomputed, so "the rest" in the Practice
    freshness view is defined against the same ranking the primary list is actually
    showing right now.
    """
    snapshot = latest_snapshot(session, player_id)
    if snapshot is None:
        return None
    entry = session.scalar(
        select(RecommendationEntry).where(
            RecommendationEntry.snapshot_id == snapshot.id,
            RecommendationEntry.blocked.is_(False),
            RecommendationEntry.candidate_kind == RecommendationCandidateKind.REFRESHER,
        )
    )
    return entry.candidate_id if entry is not None else None


def practice_freshness_rows(
    session: Session, player_id: int, content: Content, now: datetime
) -> tuple[PracticeGroupRow, ...]:
    """§15's Practice freshness view: every stale group *except* the primary list's one.

    "So freshness never crowds out objective progression" (§9.8) is a statement about the
    primary list; it says nothing about hiding a group from view entirely, so this is a
    subtraction, not a second cap. A corpus with only one triggered group at a time will
    show it here as empty, which is correct — that group is already visible above.
    """
    primary_id = primary_refresher_id(session, player_id)
    return tuple(
        group
        for group in stale_practice_groups(session, player_id, content, now)
        if group.template_id != primary_id
    )


def refresh_milestones(
    session: Session,
    player_id: int,
    keys: Sequence[str],
    *,
    now: datetime,
    source: Source = Source.MANUAL,
) -> int:
    """Self-attested practice completion (§9.8's two actions), written here directly.

    Moves ``last_practiced_at`` forward only, mirroring
    :func:`tracker.freshness.service.apply_practice_events`'s own forward-only rule — a
    later confirmation must not roll a fresher observation backwards. Never touches
    ``achieved`` (G7): this refreshes *freshness*, not competence, and a milestone with no
    row yet is skipped rather than created, since a session cannot "complete" a milestone
    the player has never been asked about (§4.5 — that gap is A7's, not this button's, to
    close).

    ``keys`` is exactly the set the caller passes: "Mark session complete" passes every
    member of one group, "Review individual skills" passes whichever subset the user
    checked. Both call this one function, so the two actions can never diverge in what
    "refreshed" means — only in which keys reach it.
    """
    refreshed = 0
    for key in keys:
        row = session.get(MilestoneRow, (player_id, key))
        if row is None:
            continue
        if row.last_practiced_at is not None and row.last_practiced_at >= now:
            continue
        row.last_practiced_at = now
        row.source = source
        row.observed_at = now
        refreshed += 1
    session.commit()
    return refreshed


# ---------------------------------------------------------------------------
# Step 11 — Roadmaps (§4.3, §6.12, §15)
# ---------------------------------------------------------------------------

#: §4.3's defaults: one primary at full weight, secondaries at a quarter.
DEFAULT_PRIMARY_WEIGHT = 1.00
DEFAULT_SECONDARY_WEIGHT = 0.25


def roadmap_options(
    session: Session, player_id: int, content: Content
) -> tuple[RoadmapOptionRow, ...]:
    """Every authored roadmap, with the player's live §6.12 selection joined in."""
    selected = {
        row.roadmap_id: row.selection_weight for row in get_active_roadmaps(session, player_id)
    }
    return tuple(
        RoadmapOptionRow(
            roadmap_id=roadmap_id,
            name=roadmap.name,
            selected=roadmap_id in selected,
            selection_weight=selected.get(roadmap_id, 0.0),
        )
        for roadmap_id, roadmap in sorted(content.roadmaps.items())
    )


def select_primary_roadmap(session: Session, player_id: int, roadmap_id: str) -> None:
    """Choose the one primary roadmap (§4.3's ``1.00``).

    Demotes every other roadmap currently at the primary weight down to the secondary
    default rather than deselecting it — switching primaries is a common re-prioritization,
    not a reason to drop a roadmap the player is still progressing.
    """
    for row in get_active_roadmaps(session, player_id):
        if row.roadmap_id != roadmap_id and row.selection_weight >= DEFAULT_PRIMARY_WEIGHT:
            set_active_roadmap(
                session, player_id, row.roadmap_id, selection_weight=DEFAULT_SECONDARY_WEIGHT
            )
    set_active_roadmap(session, player_id, roadmap_id, selection_weight=DEFAULT_PRIMARY_WEIGHT)
    session.commit()


def set_secondary_roadmap(
    session: Session, player_id: int, roadmap_id: str, *, enabled: bool
) -> None:
    """Toggle a secondary roadmap on (at §4.3's default weight) or off entirely."""
    if enabled:
        set_active_roadmap(
            session, player_id, roadmap_id, selection_weight=DEFAULT_SECONDARY_WEIGHT
        )
    else:
        clear_active_roadmap(session, player_id, roadmap_id)
    session.commit()


def set_roadmap_weight(session: Session, player_id: int, roadmap_id: str, weight: float) -> None:
    """The advanced-settings path (§4.3): an explicit raw weight, normalized at read time."""
    set_active_roadmap(session, player_id, roadmap_id, selection_weight=weight)
    session.commit()


# ---------------------------------------------------------------------------
# Step 11 — Settings (§9.6, §15)
# ---------------------------------------------------------------------------


def settings_view(session: Session, player_id: int | None, settings: Settings) -> SettingsView:
    """The settings page's whole state: the player's live preference plus app config.

    ``api_token_present`` reads only whether the configured token is non-empty — Settings
    requires ``min_length=1`` so this is always ``True`` in practice, but the field exists
    so the page can say "configured" without the token value ever reaching a template
    (§15: *"token presence, never the token value"*).
    """
    player = get_player(session, player_id) if player_id is not None else None
    prices = settings.integrations.prices
    return SettingsView(
        gp_sensitivity=player.gp_sensitivity if player is not None else GpSensitivity.NORMAL,
        tracked_username=player.username if player is not None else None,
        bind_address=settings.bind_address,
        port=settings.port,
        api_token_present=bool(settings.api_token),
        price_provider=prices.provider,
        price_base_url=prices.base_url,
        wom_base_url=settings.integrations.wise_old_man.base_url,
    )


def set_tracked_username(session: Session, player_id: int | None, username: str) -> int:
    """Name the account WOM should follow, creating the ``Player`` row if there is none.

    **This is the bootstrap §7.2 otherwise cannot have.** WOM exists to advance skill data
    while RuneLite is closed, but until now the only writer of ``Player.username`` was a sync
    payload — so the app could not learn a username without the very plugin WOM covers for.
    A user who has not installed the plugin could never use WOM at all.

    §6.11 is not weakened by this. Identity still comes from a username and never from a
    caller-supplied id, and this path sits behind the same bearer auth as everything else on
    ``/api``; what changes is only that a human at the settings page is now an accepted
    source of that username alongside the plugin.

    ``last_sync_at`` is deliberately left ``NULL`` on a row created here. A6 makes that column
    mean *"the account's own scalars have been observed"*, and naming an account observes
    nothing — so ``combat_level`` and ``quest_points`` keep resolving ``unknown`` until a real
    sync, which is the honest answer and the one G3 requires.
    """
    cleaned = username.strip()
    if not cleaned:
        raise ValueError("username must not be blank — it is WOM's only lookup key (§6.1)")

    player = get_player(session, player_id) if player_id is not None else None
    if player is None:
        existing = get_player_by_username(session, cleaned)
        if existing is not None:
            return existing.id
        created = Player(username=cleaned, display_name=cleaned, created_at=datetime.now(UTC))
        session.add(created)
        session.flush()
        return created.id

    player.username = cleaned
    return player.id


def set_gp_sensitivity(session: Session, player_id: int, sensitivity: GpSensitivity) -> None:
    """Write the player's §9.6 preference, asked in user language on the page."""
    player = get_player(session, player_id)
    if player is not None:
        player.gp_sensitivity = sensitivity
        session.commit()


# ---------------------------------------------------------------------------
# Step 11 — History (§6.10, §15)
# ---------------------------------------------------------------------------


def history_snapshots(
    session: Session, player_id: int, content: Content, *, limit: int = 20
) -> tuple[HistorySnapshotRow, ...]:
    """Recent §6.10 snapshots, newest first, each with its own ``scoring_profile_version``.

    The version is carried per row rather than assumed constant: §9.7 says a retune bumps
    it, and a history list that dropped the column would make an old run's ranking look
    like it disagreed with today's profile for no visible reason.
    """
    snapshots = session.scalars(
        select(RecommendationSnapshot)
        .where(RecommendationSnapshot.player_id == player_id)
        .order_by(RecommendationSnapshot.run_at.desc(), RecommendationSnapshot.id.desc())
        .limit(limit)
    ).all()

    rows: list[HistorySnapshotRow] = []
    for snapshot in snapshots:
        top = session.scalar(
            select(RecommendationEntry)
            .where(
                RecommendationEntry.snapshot_id == snapshot.id,
                RecommendationEntry.blocked.is_(False),
            )
            .order_by(RecommendationEntry.rank.asc())
            .limit(1)
        )
        top_name = None
        if top is not None:
            candidate = content.candidates.get(top.candidate_id)
            template = content.refreshers.get(top.candidate_id)
            top_name = (
                candidate.name
                if candidate is not None
                else (template.name if template is not None else top.candidate_id)
            )
        rows.append(
            HistorySnapshotRow(
                snapshot_id=snapshot.id,
                run_at=snapshot.run_at,
                scoring_profile_version=snapshot.scoring_profile_version,
                top_candidate_id=top.candidate_id if top is not None else None,
                top_candidate_name=top_name,
                top_reason=top.reason if top is not None else None,
            )
        )
    return tuple(rows)


def xp_series(session: Session, player_id: int) -> Mapping[str, tuple[SkillXpPoint, ...]]:
    """Every ranked skill's XP history, oldest first, for the §15 Plotly chart (§6.2).

    Unranked snapshots (``xp IS NULL``) are excluded — a chart has no honest way to plot
    "no experience figure exists yet" as a point on a numeric axis, and a ``0`` would be
    the level-1 claim §6.2 forbids, drawn as a line instead of a label.
    """
    snapshots = session.scalars(
        select(SkillSnapshot)
        .where(SkillSnapshot.player_id == player_id, SkillSnapshot.xp.is_not(None))
        .order_by(SkillSnapshot.skill.asc(), SkillSnapshot.observed_at.asc())
    ).all()

    by_skill: dict[str, list[SkillXpPoint]] = {}
    for snapshot in snapshots:
        if snapshot.xp is None:  # pragma: no cover — excluded by the query above
            continue
        by_skill.setdefault(snapshot.skill, []).append(
            SkillXpPoint(observed_at=snapshot.observed_at, xp=snapshot.xp)
        )
    return {skill: tuple(points) for skill, points in by_skill.items()}


def snapshot_diff(
    session: Session, player_id: int, before_id: int, after_id: int
) -> tuple[FactorDiffRow, ...]:
    """Which factor moved between two runs (§6.10: *"two runs can be diffed"*).

    Compared candidate-by-candidate, factor-by-factor, over the **union** of candidates
    either run scored. A candidate present in only one run still produces rows — with the
    missing side ``None`` — because "this stopped being scored" and "this newly started
    being scored" are themselves the kind of movement a diff exists to surface, not a case
    to drop silently.
    """

    def _entries(snapshot_id: int) -> dict[str, RecommendationEntry]:
        return {
            entry.candidate_id: entry
            for entry in session.scalars(
                select(RecommendationEntry).where(RecommendationEntry.snapshot_id == snapshot_id)
            )
        }

    before = _entries(before_id)
    after = _entries(after_id)

    rows: list[FactorDiffRow] = []
    for candidate_id in sorted(set(before) | set(after)):
        before_entry = before.get(candidate_id)
        after_entry = after.get(candidate_id)
        factor_names = sorted(
            {
                *(before_entry.factors if before_entry is not None else {}),
                *(after_entry.factors if after_entry is not None else {}),
            }
        )
        for factor_name in factor_names:
            before_value = (
                before_entry.factors.get(factor_name, {}).get("log_contribution")
                if before_entry is not None
                else None
            )
            after_value = (
                after_entry.factors.get(factor_name, {}).get("log_contribution")
                if after_entry is not None
                else None
            )
            rows.append(
                FactorDiffRow(
                    candidate_id=candidate_id,
                    factor=factor_name,
                    before=before_value,
                    after=after_value,
                )
            )
    return tuple(rows)


def first_player_id(session: Session) -> int | None:
    """The single-user app's one player, or ``None`` before the first sync.

    §1 and §11 make this a single-user, single-account tool, so the UI has no account picker
    and no session identity to resolve. Reading the lowest id keeps that assumption in one
    function: if the app ever grows a second account, this is the call site that has to
    answer for it rather than every page.
    """
    return session.scalar(select(Player.id).order_by(Player.id).limit(1))
