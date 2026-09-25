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
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.content.requirements import iter_leaves
from tracker.db import advisor as advisor_repo
from tracker.db.enums import AdvisorRole, RecommendationCandidateKind
from tracker.db.models import (
    AdvisorConversation,
    AdvisorMessage,
    CapabilityState,
    ContainerScan,
    ItemPrice,
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
    upsert_milestone,
)
from tracker.domain.skills import canonical_skill_name
from tracker.domain.types import (
    AccountType,
    Container,
    GpSensitivity,
    LeafRef,
    MilestoneKind,
    PlayerState,
    Source,
    Status,
    Tri,
    UnlockState,
)
from tracker.gear.render import rungs_label
from tracker.gear.setup import GearPick, GearSetup, SetupSlot, gear_progress
from tracker.recommendations.refreshers import practice_candidates
from tracker.sync.advisor import AdvisorReply
from tracker.sync.guidance import StoredGuidance
from tracker.ui.staleness import CONTAINER_NAMES, humanize_age, scan_note
from tracker.ui.states import UiState
from tracker.ui.view_model import (
    NEW_CONVERSATION_ID,
    AdvisorConversationRow,
    AdvisorMessageRow,
    AdvisorThreadView,
    BandRow,
    BlockedRecommendationRow,
    CapabilityRow,
    DashboardView,
    FactorDiffRow,
    GearPickRow,
    GearSlotRow,
    GearStyleRow,
    GearView,
    GoalProgressRow,
    GuidanceStepRow,
    GuidanceView,
    HistorySnapshotRow,
    LeafRow,
    NeededForRow,
    PracticeGroupRow,
    PracticeMemberRow,
    RecommendationEntryRow,
    RecommendationRow,
    RoadmapOptionRow,
    RoadmapProgressRow,
    SettingsView,
    SkillRow,
    SkillXpPoint,
    SpeedUpRow,
    UnblockRow,
    UnlockRow,
    _gp,
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
    """One row per canonical current skill, ranked first and highest first.

    Names and combat flags come from content where the id resolves; a snapshot for a skill
    the corpus does not declare still renders, under a titled id. §10.7 makes that
    unreachable through the corpus, but a sync payload names skills freely, and dropping
    one here would hide an observed fact because a *content* file omitted it.
    """
    snapshots: Sequence[SkillSnapshot] = current_skill_snapshots(session, player_id)
    skills = content.skills

    rows = []
    for snapshot in snapshots:
        skill_id = canonical_skill_name(snapshot.skill)
        definition = skills.get(skill_id)
        rows.append(
            skill_row(
                skill_id=skill_id,
                name=definition.name if definition else skill_id.replace("_", " ").title(),
                is_combat=definition.is_combat if definition else False,
                level=snapshot.level,
                xp=snapshot.xp,
            )
        )
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


def _consequence_name(stored: Mapping[str, Any], lookup: Mapping[str, Any], id_key: str) -> str:
    """The freshest truthful name for a stored consequence.

    Prefers what content says today and falls back to the name the run recorded, which is
    ``_band_rows``' rule applied to a second join. Content changes between runs: renaming a
    capability must not turn a History page into a stack trace, and the stored name is still
    the most truthful thing available about what that row described when it was written.
    """
    entity = lookup.get(str(stored.get(id_key, "")))
    if entity is not None:
        return str(entity.name)
    return str(stored.get("name", stored.get(id_key, "")))


def _consequence_rows(
    stored: Mapping[str, Any] | None, content: Content
) -> tuple[
    tuple[UnblockRow, ...],
    tuple[NeededForRow, ...],
    tuple[GoalProgressRow, ...],
    tuple[SpeedUpRow, ...],
]:
    """§9.10's consequence rows, read from the snapshot rather than recomputed.

    **The stored blob is rendered; nothing is re-derived here.** A consequence is a fact
    about the account at the time of the run — "unblocks Desert Treasure I" stops being true
    the moment the quest is done — so re-deriving on read would relabel a historical entry
    with today's facts. Same argument as ``_band_rows``, and the reason the column exists.

    ``goal_links`` is folded into the *"needed for"* rows rather than shown as a list of its
    own: an indirect goal is only meaningful attached to the hop that reached it, and a bare
    "Ice Barrage NH" under its own heading would claim a directness the engine was careful
    not to claim. The first link is used, which is the strongest one the engine ordered.
    """
    blob = stored or {}
    links = list(blob.get("goal_links") or ())
    link = links[0] if links else None

    unblocks = tuple(
        UnblockRow(name=_consequence_name(entry, content.capabilities, "capability_id"))
        for entry in blob.get("unblocks_capabilities") or ()
    )
    needed_for = tuple(
        NeededForRow(
            name=_consequence_name(entry, content.candidates, "candidate_id"),
            remaining_before=int(entry.get("remaining_before", 0)),
            remaining_after=int(entry.get("remaining_after", 0)),
            # The link hangs off the hop the engine reached it through, and off no other.
            goal_name=(
                _consequence_name(link, content.capabilities, "capability_id")
                if link is not None and link.get("via_candidate_id") == entry.get("candidate_id")
                else None
            ),
            goal_on_roadmap=bool(link.get("on_roadmap", True)) if link is not None else True,
        )
        for entry in blob.get("gate_progress") or ()
    )
    works_toward = tuple(
        GoalProgressRow(
            name=_consequence_name(entry, content.capabilities, "capability_id"),
            remaining_before=int(entry.get("remaining_before", 0)),
            remaining_after=int(entry.get("remaining_after", 0)),
            on_roadmap=bool(entry.get("on_roadmap", True)),
        )
        for entry in blob.get("goal_progress") or ()
    )
    speeds_up = tuple(
        SpeedUpRow(
            name=_consequence_name(entry, content.candidates, "candidate_id"),
            hours_before=float(entry.get("hours_before", 0.0)),
            hours_after=float(entry.get("hours_after", 0.0)),
        )
        for entry in blob.get("speeds_up") or ()
    )
    return unblocks, needed_for, works_toward, speeds_up


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


def _band_rows(stored: Sequence[Mapping[str, Any]] | None, content: Content) -> tuple[BandRow, ...]:
    """Join §8.2's persisted bands back to content for the method's name and description.

    **The stored ``method_id`` is rendered; a method is never re-selected here.** §8.2
    step 3 chooses among the methods the account satisfied *at run time*, so re-deriving
    the choice on read could name a method the quoted hours did not come from — the same
    drift argument that makes ``reason`` a stored string rather than a regenerated one.

    A ``method_id`` content no longer declares degrades to the raw id and never raises.
    Content changes between runs: renaming a method must not turn every History page into
    a stack trace, and the id is still the most truthful thing available about what that
    number was computed from.
    """
    rows: list[BandRow] = []
    for band in stored or ():
        method_id = band.get("method_id")
        method = content.training_methods.get(method_id) if method_id else None
        detail = method.detail if method is not None else None
        rows.append(
            BandRow(
                from_level=int(band["from_level"]),
                to_level=int(band["to_level"]),
                method_id=method_id,
                method_name=method.name if method is not None else method_id,
                hours=float(band.get("hours", 0.0)),
                gp=int(band.get("gp", 0)),
                fallback=bool(band.get("fallback", False)),
                location=detail.location if detail is not None else None,
                target=detail.target if detail is not None else None,
                gear=tuple(detail.gear) if detail is not None else (),
                inventory=tuple(detail.inventory) if detail is not None else (),
                notes=detail.notes if detail is not None else None,
                wiki_url=detail.wiki_url if detail is not None else None,
            )
        )
    return tuple(rows)


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
    # Read live rather than from the snapshot: coins move between runs, and a purchasing
    # note quoting a balance from last week's snapshot would be worse than none at all.
    # The *ranking* stays the persisted one — this is display, and it feeds no factor.
    liquid_gp = build_player_state(session, player_id).liquid_gp
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
        unblocks, needed_for, works_toward, speeds_up = _consequence_rows(
            entry.consequences, content
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
                unblocks=unblocks,
                needed_for=needed_for,
                works_toward=works_toward,
                speeds_up=speeds_up,
                practice_members=members,
                suggested_session=suggested_session,
                bands=_band_rows(entry.bands, content),
                liquid_gp=liquid_gp,
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
            blockers=tuple(
                LeafRow(
                    leaf_type=str(leaf.get("leaf_type", "")),
                    key=str(leaf.get("key", "")),
                    description=str(leaf.get("description", "")),
                    target=leaf.get("target"),
                )
                for leaf in (entry.blockers or ())
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


def attest_milestone(
    session: Session,
    player_id: int,
    key: str,
    *,
    achieved: bool,
    content: Content,
    now: datetime,
    source: Source = Source.MANUAL,
) -> bool:
    """A7's missing half: record the user's answer to a self-attested milestone (§6.6).

    :func:`refresh_milestones` deliberately skips a milestone with no row, on the grounds
    that *"a session cannot complete a milestone the player has never been asked about"* —
    and names this function's job as the one that closes that gap. So this one **creates**
    the row: the whole point is that the question has now been put.

    Writing ``attested_at`` is what makes the answer legible. ``achieved=False`` with a
    timestamp is *"asked, and they said no"* — an honest ``unsatisfied`` — while the absent
    row it replaces was ``unknown``. Those two must not collapse (§4.5, A7), which is why
    declining is a write rather than a no-op.

    ``last_practiced_at`` is carried over rather than set. Attesting is a claim about
    competence, and freshness is a claim about recency; §6.6 keeps them in separate columns
    precisely so answering *"yes, I can do 4-way switches"* cannot silently pass for having
    practised them today. The reverse guard is G7's, in
    :func:`refresh_milestones`, and both directions have to hold for the pair to mean
    anything.

    :returns: False when ``key`` names no authored milestone, or one measured rather than
        asked. A ``derived`` milestone is computed from counters (§6.6), so accepting a
        user's answer for one would let an opinion overwrite a measurement.
    """
    authored = content.milestones.get(key)
    if authored is None or authored.kind is not MilestoneKind.SELF_ATTESTED:
        return False

    existing = session.get(MilestoneRow, (player_id, key))
    upsert_milestone(
        session,
        player_id,
        key,
        kind=authored.kind,
        class_=authored.class_,
        achieved=achieved,
        source=source,
        observed_at=now,
        value=existing.value if existing is not None else None,
        attested_at=now,
        last_practiced_at=existing.last_practiced_at if existing is not None else None,
    )
    session.commit()
    return True


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
        account_type=(
            AccountType(player.account_type) if player is not None and player.account_type else None
        ),
        members=player.members if player is not None else None,
        price_rows=session.scalar(select(func.count()).select_from(ItemPrice)) or 0,
        price_last_fetched_at=session.scalar(select(func.max(ItemPrice.fetched_at))),
    )


def set_account_type(
    session: Session, player_id: int | None, account_type: AccountType | None
) -> None:
    """Record §4.2's account mode, or clear it back to "nobody has said".

    Clearing is a real operation, not an oversight: a user who picked Ironman by mistake
    must be able to get back to *unknown* rather than being forced to assert "main"
    instead. §4.5 makes those two different states, so the UI has to be able to reach both.
    """
    player = get_player(session, player_id) if player_id is not None else None
    if player is None:
        return
    player.account_type = account_type.value if account_type is not None else None
    session.commit()


def set_members(session: Session, player_id: int | None, members: bool | None) -> None:
    """Record membership, or clear it back to unknown — :func:`set_account_type`'s rule."""
    player = get_player(session, player_id) if player_id is not None else None
    if player is None:
        return
    player.members = members
    session.commit()


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

    # ``display_name`` moves with the username. It is what the dashboard shows as the
    # account (§15's account stat), so leaving it at the previous character's value would
    # label one account's data with another's name. A later sync overwrites it with the
    # properly-cased name from the payload's identity block (``tracker.sync.merge``); until
    # then, what the user typed is the best name available.
    player.username = cleaned
    player.display_name = cleaned
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
    """Every ranked skill's XP history under its canonical key, oldest first (§6.2).

    Unranked snapshots (``xp IS NULL``) are excluded — a chart has no honest way to plot
    "no experience figure exists yet" as a point on a numeric axis, and a ``0`` would be
    the level-1 claim §6.2 forbids, drawn as a line instead of a label.
    """
    snapshots = session.scalars(
        select(SkillSnapshot)
        .where(SkillSnapshot.player_id == player_id, SkillSnapshot.xp.is_not(None))
        .order_by(SkillSnapshot.observed_at.asc(), SkillSnapshot.id.asc())
    ).all()

    by_skill: dict[str, list[SkillXpPoint]] = {}
    for snapshot in snapshots:
        if snapshot.xp is None:  # pragma: no cover — excluded by the query above
            continue
        by_skill.setdefault(canonical_skill_name(snapshot.skill), []).append(
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


def guidance_view_of(stored: StoredGuidance, candidate_id: str) -> GuidanceView:
    """§21's answer, as a row (§15's `read_model -> view_model -> renderer` layering).

    ``cached`` is carried through rather than dropped because it is the one thing the reader
    cannot infer from the text: identical prose means something different when it was written
    just now and when it was written a week ago against the same levels.
    """
    dto = stored.dto
    return GuidanceView(
        candidate_id=candidate_id,
        task_name=stored.task_name,
        summary=dto.summary,
        prerequisites=dto.prerequisites,
        steps=tuple(
            GuidanceStepRow(order=step.order, title=step.title, detail=step.detail)
            for step in dto.steps
        ),
        warnings=dto.warnings,
        uncertain=dto.uncertain,
        estimated_session_minutes=dto.estimated_session_minutes,
        model=dto.model,
        generated_at=dto.generated_at,
        cached=stored.cached,
    )


# ---------------------------------------------------------------------------
# §22 — the general advisor
# ---------------------------------------------------------------------------


def advisor_thread(
    session: Session,
    player_id: int,
    conversation_id: int | None = None,
    *,
    limit: int = 20,
) -> AdvisorThreadView:
    """The conversation to show, plus the threads beside it.

    An explicit ``conversation_id`` that does not exist falls back to the latest rather than
    raising: this is the *read* path, reached by a page load, and a stale bookmark should show
    a conversation rather than an error. The write path in :mod:`tracker.sync.advisor` is
    stricter for the opposite reason — there, silently answering into a different thread would
    put the user's words somewhere they did not intend.

    :data:`~tracker.ui.view_model.NEW_CONVERSATION_ID` is the one id that does not take that
    fallback, and it cannot: it is not an id that failed to resolve, it is a request for a
    blank thread. Running it through the fallback answered that request with the most recent
    conversation, which is what made *New conversation* a control that appeared to do nothing.
    """
    conversation = _chosen_conversation(session, player_id, conversation_id)

    rows = tuple(
        AdvisorConversationRow(
            conversation_id=row.id,
            title=row.title,
            updated_at=row.updated_at,
            current=conversation is not None and row.id == conversation.id,
        )
        for row in advisor_repo.list_conversations(session, player_id, limit=limit)
    )
    if conversation is None:
        return AdvisorThreadView(conversation_id=None, title="", conversations=rows)

    return AdvisorThreadView(
        conversation_id=conversation.id,
        title=conversation.title,
        messages=tuple(
            _advisor_message_row(message, current_hash=conversation.digest_hash)
            for message in advisor_repo.thread(session, conversation.id)
        ),
        conversations=rows,
    )


def _chosen_conversation(
    session: Session, player_id: int, conversation_id: int | None
) -> AdvisorConversation | None:
    """Which thread the URL is asking for, in the three senses it can ask.

    *Nothing* means "wherever I was", *zero* means "a new one", and any other number means that
    thread if it is this player's and the most recent otherwise. Separated out because the
    middle case reads as an oversight when it is inlined among the fallbacks — it is the only
    branch that must not fall through, and it looked exactly like the branch that must.
    """
    if conversation_id == NEW_CONVERSATION_ID:
        return None
    if conversation_id is not None:
        found = advisor_repo.get_conversation(session, player_id, conversation_id)
        if found is not None:
            return found
    return advisor_repo.latest_conversation(session, player_id)


def delete_advisor_conversation(session: Session, player_id: int, conversation_id: int) -> bool:
    """Remove one thread, and say whether there was one. Commits.

    The only destructive action the interface offers, which is why it is spelled out here
    rather than reached through :mod:`tracker.db.advisor` directly: a page should not be the
    thing that decides when a delete is committed.
    """
    deleted = advisor_repo.delete_conversation(session, player_id, conversation_id)
    if deleted:
        session.commit()
    return deleted


def _advisor_message_row(message: AdvisorMessage, *, current_hash: str) -> AdvisorMessageRow:
    """One stored row, as a view row.

    ``stale_digest`` compares the message's own hash against the conversation's current one, so
    the interface marks *the answers that predate a sync* rather than the whole thread — §15's
    staleness discipline at the resolution the fact actually has.
    """
    return AdvisorMessageRow(
        role="advisor" if message.role is AdvisorRole.ASSISTANT else "you",
        text=message.content,
        uncertain=tuple(message.uncertain or ()),
        model=message.model or "",
        generated_at=message.created_at,
        tool_names=tuple(
            str(entry.get("name", "")) for entry in (message.tool_trace or ()) if entry.get("name")
        ),
        truncated=message.stop_reason == "max_tokens",
        stale_digest=(
            message.role is AdvisorRole.ASSISTANT
            and message.digest_hash is not None
            and message.digest_hash != current_hash
        ),
    )


def advisor_reply_row(reply: AdvisorReply) -> AdvisorMessageRow:
    """The answer just produced, without a second read of the database.

    A freshly written answer is never stale by construction — it was written against the
    snapshot the conversation now stores — so ``stale_digest`` is false rather than recomputed.
    """
    turn = reply.turn
    return AdvisorMessageRow(
        role="advisor",
        text=turn.answer,
        uncertain=turn.uncertain,
        model=turn.model,
        generated_at=turn.generated_at,
        tool_names=tuple(entry.name for entry in turn.tool_trace),
        truncated=turn.truncated,
    )


# ---------------------------------------------------------------------------
# §23 — gear progression
# ---------------------------------------------------------------------------

#: Which §23 answer each :class:`UiState` draws. ``UNKNOWN`` is the one with a rule
#: attached (§15): it means *nobody looked* or *nobody authored it*, never *no*.
_GEAR_STATE: Mapping[Tri, UiState] = {
    Tri.SATISFIED: UiState.UNLOCKED,
    Tri.UNSATISFIED: UiState.LOCKED,
    Tri.UNKNOWN: UiState.UNKNOWN,
}

#: Ownership in ownership's own words. The *state* is shared with the lock scale — one
#: `UiState`, so §15's disjointness assertion still covers these badges — but the *word* is
#: not, because "locked" answers whether the account can wear the piece and reads as a flat
#: contradiction on the very rung the page has just recommended.
_HELD_LABEL: Mapping[Tri, str] = {
    Tri.SATISFIED: "held",
    Tri.UNSATISFIED: "not held",
    Tri.UNKNOWN: "not yet seen",
}

#: Whether the account can wear it. Rendered only where the row's own layer does not
#: already say so — see `_gear_pick_row`.
_FIT_LABEL: Mapping[Tri, str] = {
    Tri.SATISFIED: "can equip",
    Tri.UNSATISFIED: "cannot equip yet",
    Tri.UNKNOWN: "requirements unknown",
}


def gear_view(session: Session, player_id: int | None, content: Content) -> GearView:
    """§23.5's page: the computed setup, turned into rows.

    Reads the same cached prices §22 does, preferring ``selected_price_gp`` over
    ``high_price_gp`` for §8.3's reason — that is the figure the estimator actually costed
    with, and showing the raw quote instead would put a number on this page that no other
    page agrees with.

    The computation itself is :func:`tracker.gear.setup.gear_progress`, unchanged and shared
    with §22. One projection, two renderings.
    """
    if player_id is None:
        return GearView()

    state = build_player_state(session, player_id)
    prices: dict[int, int | None] = {
        row.item_id: (
            row.selected_price_gp if row.selected_price_gp is not None else row.high_price_gp
        )
        for row in session.scalars(select(ItemPrice)).all()
    }
    progress = gear_progress(state, content, prices=prices)

    return GearView(
        styles=tuple(_gear_style_row(setup) for setup in progress.setups),
        fully_scanned=progress.fully_scanned,
        scan_note=None if progress.fully_scanned else _gear_scan_note(state),
    )


def _gear_scan_note(state: PlayerState) -> str:
    """Name the containers nobody has opened, because that is what the reader can act on.

    Deliberately not :func:`tracker.ui.staleness.scan_note`: that one reports *when* a
    container was last seen and needs a clock, and this page's question is the prior one —
    whether it has ever been looked in at all. Until every container has, every *not held*
    below is really *unknown* (§4.5), which is a caveat over the whole page rather than a
    fact about any one row.
    """
    unseen = [
        CONTAINER_NAMES[container]
        for container in Container
        if container not in state.container_scans
    ]
    return (
        f"Never scanned: {', '.join(unseen)}. Anything shown as not held may simply not have "
        "been seen — open it in-game with RuneLite running."
    )


def _gear_style_row(setup: GearSetup) -> GearStyleRow:
    missing = setup.missing
    total = setup.to_complete_gp
    if not missing:
        label = "Every recommended piece is already held."
    elif total is not None:
        label = f"Still to get: {len(missing)} pieces, about {_gp(total)} gp at cached prices."
    else:
        # Not a partial sum — see `GearSetup.to_complete_gp`. A figure covering only the
        # cached half would read as the whole bill and understate it.
        label = f"Still to get: {len(missing)} pieces. No total — some have no cached price."

    return GearStyleRow(
        style=setup.style,
        slots=tuple(_gear_slot_row(slot) for slot in setup.slots),
        missing_label=label,
    )


def _gear_slot_row(slot: SetupSlot) -> GearSlotRow:
    # Compared on `item_id` rather than on the rendered rows: two rungs can share a name and
    # a rung number across ladders, and identity is the thing being asked about.
    same = (
        slot.recommended is not None
        and slot.best_held is not None
        and slot.recommended.item_id == slot.best_held.item_id
    )
    return GearSlotRow(
        slot=slot.slot,
        # Shared with the advisor's rendering rather than spelled twice — the ammunition
        # ladder holds one rung, and "1 rungs" is a stated fact that is wrong.
        ladder_label=rungs_label(slot.ladder_size),
        recommended=_gear_pick_row(slot.recommended, slot.ladder_size),
        best_held=_gear_pick_row(slot.best_held, slot.ladder_size),
        held_is_recommended=same,
        next_rung=_gear_pick_row(slot.next_rung, slot.ladder_size),
        earn=_gear_pick_row(slot.earn, slot.ladder_size),
        aspirational=tuple(
            row
            for pick in slot.aspirational[1:]
            if (row := _gear_pick_row(pick, slot.ladder_size)) is not None
        ),
        also_held=tuple(
            row
            for pick in slot.also_held
            if (row := _gear_pick_row(pick, slot.ladder_size)) is not None
        ),
        ladder=tuple((pick.tier, pick.name) for pick in slot.rungs),
        conflict=slot.holds_what_it_cannot_wear,
    )


def _gear_pick_row(pick: GearPick | None, ladder_size: int) -> GearPickRow | None:
    if pick is None:
        return None
    return GearPickRow(
        name=pick.name,
        rung_label=f"rung {pick.tier} of {ladder_size}",
        held_state=_GEAR_STATE[pick.held],
        fit_state=_GEAR_STATE[pick.fit],
        # Empty rather than "no cached price". §8.3's rule is that absent is absent, and an
        # empty label keeps it — but the sentence was being repeated once per rung, so a slot
        # with five unpriced rungs said it five times and the page read as an apology. The
        # fact is not dropped: `tracker.ui.gear` says it once, for the whole style, when no
        # rung in it has a price. One caveat at the scope it actually applies to.
        # An untradeable rung shows no price, whatever is cached against it. The figure held
        # for an Avernic defender is really its *hilt*, and a gp label beside a piece the
        # market does not sell invites a purchase nobody can make (§23.5).
        price_label=(
            f"{_gp(pick.price_gp)} gp"
            if pick.price_gp is not None and pick.obtainable is not Tri.UNSATISFIED
            else ""
        ),
        held_label=_HELD_LABEL[pick.held],
        # A wearable rung needs no badge saying so: every layer that can carry one either
        # states it outright ("best you can equip") or explains the gap in `note`. The badge
        # earns its place only when the answer is no or nobody knows.
        fit_label="" if pick.fit is Tri.SATISFIED else _FIT_LABEL[pick.fit],
        note=_gear_note(pick),
        acquire_label=_acquire_label(pick),
        tier=pick.tier,
    )


def _acquire_label(pick: GearPick) -> str:
    """§23.2's second axis, in the words a reader can act on.

    Three answers and only two of them are worth a line. A tradeable rung says nothing —
    *"you can buy this"* is what the price beside it already means — while the other two both
    change what the reader should do next, and so both earn the space.
    """
    if pick.obtainable is Tri.UNSATISFIED:
        if pick.acquired_from:
            return f"Earn it — {pick.acquired_from}. It cannot be bought."
        return "It cannot be bought — the tracker has not recorded what wins it."
    if pick.obtainable is Tri.UNKNOWN:
        return "The tracker has not recorded how this is obtained."
    return ""


def _gear_note(pick: GearPick) -> str | None:
    """Why a rung is not usable — the requirement, not merely that one exists."""
    if pick.gate_unknown:
        return "Requirements not established by the tracker — not a claim about your account."
    if pick.fit is Tri.UNSATISFIED and pick.blockers:
        return "Needs " + ", ".join(ref.description for ref in pick.blockers[:3])
    if pick.fit is Tri.UNKNOWN and pick.unknowns:
        return "Cannot tell — nobody has observed " + ", ".join(
            ref.description for ref in pick.unknowns[:3]
        )
    return None
