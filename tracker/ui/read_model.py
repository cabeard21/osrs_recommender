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
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.content.loader import Content
from tracker.content.requirements import iter_leaves
from tracker.db.models import (
    CapabilityState,
    ContainerScan,
    Player,
    RecommendationEntry,
    RecommendationSnapshot,
    SkillSnapshot,
    Unlock,
)
from tracker.db.repository import (
    current_skill_snapshots,
    get_active_roadmaps,
    get_container_scans,
    get_player,
    get_unlocks,
)
from tracker.domain.types import Container, LeafRef, Status, UnlockState
from tracker.ui.staleness import humanize_age, scan_note
from tracker.ui.view_model import (
    CapabilityRow,
    DashboardView,
    RecommendationRow,
    RoadmapProgressRow,
    SkillRow,
    UnlockRow,
    capability_row,
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


def first_player_id(session: Session) -> int | None:
    """The single-user app's one player, or ``None`` before the first sync.

    §1 and §11 make this a single-user, single-account tool, so the UI has no account picker
    and no session identity to resolve. Reading the lowest id keeps that assumption in one
    function: if the app ever grows a second account, this is the call site that has to
    answer for it rather than every page.
    """
    return session.scalar(select(Player.id).order_by(Player.id).limit(1))
