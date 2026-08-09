"""Per-aggregate read and write helpers over the §6 tables.

This module is deliberately dull. It knows how to find every row belonging to one player
and how to write one fact back, and nothing else. The three-valued reasoning that gives
those rows meaning lives in :mod:`tracker.progression.evaluate`; the mapping from rows to
:class:`~tracker.domain.types.PlayerState` lives in :mod:`tracker.db.projection`. Putting
any of it here would give the project two implementations of §9.1 that could drift, which
is the specific failure D8 exists to prevent.

Two rules do live here, and both are about *which row to read*, not about what it means:

* **§7.4 read-side conflict resolution** — ``SkillSnapshot`` is a history log (§6.2), so
  "the player's Magic level" is a selection among rows: most recent ``observed_at`` first,
  ties broken by ``runelite > wise_old_man > hiscores``. See
  :func:`current_skill_snapshots`, which resolves it in SQL rather than by loading a log
  that grows without bound.
* **§6.12 read-time normalization** — ``ActiveRoadmap.selection_weight`` is stored raw and
  normalized on read, so removing one roadmap cannot rescale the others' stored values.
  :func:`roadmap_selection` returns the raw weights inside a
  :class:`~tracker.domain.types.RoadmapSelection`, whose ``normalized()`` applies §9.3.

§7.4's *write*-side rules — never let a staler observation overwrite a fresher one, never
let a lower-precedence source decrease stored XP — are **not** applied by the writers here.
They require comparing an incoming payload's provenance against what is stored, which is
the sync layer's job (§7.1, Step 8); a repository that silently dropped writes would make
that layer impossible to test. The writers below are last-write-wins by construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from tracker.db.models import (
    ActiveRoadmap,
    ContainerScan,
    Milestone,
    ObservedItem,
    Player,
    QuestState,
    SkillSnapshot,
    SyncEvent,
    Unlock,
)
from tracker.domain.types import (
    SOURCE_PRECEDENCE,
    Container,
    MilestoneClass,
    MilestoneKind,
    QuestStatus,
    RoadmapSelection,
    Source,
    UnlockState,
)


class PlayerNotFoundError(LookupError):
    """No ``Player`` row with the requested id.

    Distinct from a player who exists but has never been synced. A brand-new account has
    a row and no facts, and must project an empty-but-valid state (§4.5); an id with no
    row at all is a caller bug — a stale bookmark, a deleted character — and inventing a
    ``PlayerState`` for it would hand the engine an account that does not exist.
    """


# ---------------------------------------------------------------------------
# §6.1 Player
# ---------------------------------------------------------------------------


def get_player(session: Session, player_id: int) -> Player | None:
    """The player row, or ``None``. Use :func:`require_player` when absence is an error."""
    return session.get(Player, player_id)


def require_player(session: Session, player_id: int) -> Player:
    """The player row, raising :class:`PlayerNotFoundError` when there is none."""
    player = session.get(Player, player_id)
    if player is None:
        raise PlayerNotFoundError(
            f"no player with id {player_id}. An account that exists but has never synced "
            "has a row and no facts (§4.5); no row at all means the id is wrong"
        )
    return player


def get_player_by_username(session: Session, username: str) -> Player | None:
    """Lookup by the hiscores/WOM key (§6.1). ``username`` is unique, so at most one row."""
    return session.scalar(select(Player).where(Player.username == username))


# ---------------------------------------------------------------------------
# §6.2 SkillSnapshot
# ---------------------------------------------------------------------------


#: §7.4's precedence as a sortable rank, lowest first. ``Source`` members the rule does
#: not name — ``manual``, ``derived``, ``osrs_wiki_prices`` — fall through to ``else_``
#: and sort last. §7.4 orders only the three *observation* sources, so anything else
#: losing an exact-timestamp tie is arbitrary; it is at least deterministic, which
#: matters more than the choice, since a tie means two rows claiming the same instant.
#:
#: Written as a *searched* ``CASE`` (``WHEN source = :x``) rather than the shorter
#: ``case({...}, value=...)`` form: the latter binds its keys as raw parameters with no
#: type attached, and SQLite's driver cannot bind a Python ``Enum``. The comparison form
#: routes each value through the column's own ``sa.Enum`` type, which is what turns
#: ``Source.RUNELITE`` into the string the column actually stores.
_SOURCE_RANK = case(
    *((SkillSnapshot.source == source, rank) for rank, source in enumerate(SOURCE_PRECEDENCE)),
    else_=len(SOURCE_PRECEDENCE),
)


def current_skill_snapshots(session: Session, player_id: int) -> Sequence[SkillSnapshot]:
    """The one current snapshot per skill, resolved by §7.4.

    Resolved in SQL with a window function rather than by loading every row and reducing
    in Python. ``SkillSnapshot`` is an append-only history feeding the §15 XP chart, so
    the naive version's cost grows with the account's age — a player synced hourly for a
    year is a six-figure row count to answer a question about twenty-three skills.

    ``id`` is the final tie-break so the result is stable when two rows share both an
    ``observed_at`` and a source; without it SQLite is free to return either, and a
    projection that flickers between equal candidates is impossible to debug.
    """
    ranked = (
        select(
            SkillSnapshot,
            func.row_number()
            .over(
                partition_by=SkillSnapshot.skill,
                order_by=(
                    SkillSnapshot.observed_at.desc(),
                    _SOURCE_RANK.asc(),
                    SkillSnapshot.id.desc(),
                ),
            )
            .label("precedence_rank"),
        )
        .where(SkillSnapshot.player_id == player_id)
        .subquery()
    )
    current = aliased(SkillSnapshot, ranked)
    return session.scalars(select(current).where(ranked.c.precedence_rank == 1)).all()


def append_skill_snapshot(
    session: Session,
    player_id: int,
    *,
    skill: str,
    level: int,
    xp: int | None,
    source: Source,
    observed_at: datetime,
) -> SkillSnapshot:
    """Append one observation. Never an upsert — §6.2 is a log, not a current-value table.

    ``xp=None`` means unranked and must be passed through untouched (§6.2, G5). Hiscores'
    ``-1`` is normalized to ``None`` at the adapter boundary (Step 7), not here; this
    function would happily store ``-1`` and that is the adapter's bug to avoid, not a
    coercion to bury in the repository.
    """
    snapshot = SkillSnapshot(
        player_id=player_id,
        skill=skill,
        level=level,
        xp=xp,
        source=source,
        observed_at=observed_at,
    )
    session.add(snapshot)
    return snapshot


# ---------------------------------------------------------------------------
# §6.3 Unlock · §6.4 QuestState
# ---------------------------------------------------------------------------


def get_unlocks(session: Session, player_id: int) -> Sequence[Unlock]:
    """Every unlock row for the player, including ``spellbook_*``/``diary_*``/``ca_*`` (A12)."""
    return session.scalars(select(Unlock).where(Unlock.player_id == player_id)).all()


def upsert_unlock(
    session: Session,
    player_id: int,
    key: str,
    *,
    state: UnlockState,
    source: Source,
    observed_at: datetime,
) -> Unlock:
    """Write the current state of one unlock, keyed by ``(player_id, key)`` (§6.3)."""
    row = session.get(Unlock, (player_id, key))
    if row is None:
        row = Unlock(
            player_id=player_id, key=key, state=state, source=source, observed_at=observed_at
        )
        session.add(row)
        return row
    row.state = state
    row.source = source
    row.observed_at = observed_at
    return row


def get_quest_states(session: Session, player_id: int) -> Sequence[QuestState]:
    return session.scalars(select(QuestState).where(QuestState.player_id == player_id)).all()


def upsert_quest_state(
    session: Session,
    player_id: int,
    quest_id: str,
    *,
    status: QuestStatus,
    source: Source,
    observed_at: datetime,
) -> QuestState:
    """Write the current status of one quest, keyed by ``(player_id, quest_id)`` (§6.4)."""
    row = session.get(QuestState, (player_id, quest_id))
    if row is None:
        row = QuestState(
            player_id=player_id,
            quest_id=quest_id,
            status=status,
            source=source,
            observed_at=observed_at,
        )
        session.add(row)
        return row
    row.status = status
    row.source = source
    row.observed_at = observed_at
    return row


# ---------------------------------------------------------------------------
# §6.5 ObservedItem and ContainerScan
# ---------------------------------------------------------------------------


def get_observed_items(session: Session, player_id: int) -> Sequence[ObservedItem]:
    """Every ``(item_id, container)`` sighting for the player.

    One item can appear here several times — a Voidwaker in the bank and a second one
    wielded are two rows (§6.5's key is ``(player_id, item_id, container)``). Collapsing
    them into the engine's per-item view is :mod:`tracker.db.projection`'s job.
    """
    return session.scalars(select(ObservedItem).where(ObservedItem.player_id == player_id)).all()


def upsert_observed_item(
    session: Session,
    player_id: int,
    item_id: int,
    container: Container,
    *,
    quantity: int,
    source: Source,
    observed_at: datetime,
) -> ObservedItem:
    """Write the latest sighting of one item in one container (§6.5).

    Writing ``quantity=0`` is meaningful and is not the same as deleting the row: it
    records that the container was looked at and the item was not in it. Neither is
    required — the ``ContainerScan`` row is what makes an *absent* row resolve
    ``unsatisfied`` rather than ``unknown`` — but a zero row is not an error to be
    normalized away here.
    """
    row = session.get(ObservedItem, (player_id, item_id, container))
    if row is None:
        row = ObservedItem(
            player_id=player_id,
            item_id=item_id,
            container=container,
            quantity=quantity,
            source=source,
            observed_at=observed_at,
        )
        session.add(row)
        return row
    row.quantity = quantity
    row.source = source
    row.observed_at = observed_at
    return row


def get_container_scans(session: Session, player_id: int) -> Sequence[ContainerScan]:
    """Every container this player has had scanned at least once (§6.5).

    A container with no row here has *never* been seen in full, and that absence is the
    signal — see :func:`tracker.db.projection.build_player_state`.
    """
    return session.scalars(select(ContainerScan).where(ContainerScan.player_id == player_id)).all()


def record_container_scan(
    session: Session,
    player_id: int,
    container: Container,
    *,
    scanned_at: datetime,
    source: Source,
) -> ContainerScan:
    """Record that one container was seen *in full* (§6.5)."""
    row = session.get(ContainerScan, (player_id, container))
    if row is None:
        row = ContainerScan(
            player_id=player_id, container=container, scanned_at=scanned_at, source=source
        )
        session.add(row)
        return row
    row.scanned_at = scanned_at
    row.source = source
    return row


# ---------------------------------------------------------------------------
# §6.6 Milestone
# ---------------------------------------------------------------------------


def get_milestones(session: Session, player_id: int) -> Sequence[Milestone]:
    return session.scalars(select(Milestone).where(Milestone.player_id == player_id)).all()


def upsert_milestone(
    session: Session,
    player_id: int,
    key: str,
    *,
    kind: MilestoneKind,
    class_: MilestoneClass,
    achieved: bool,
    source: Source,
    observed_at: datetime,
    value: int | None = None,
    attested_at: datetime | None = None,
    last_practiced_at: datetime | None = None,
) -> Milestone:
    """Write the current state of one milestone, keyed by ``(player_id, key)`` (§6.6).

    ``attested_at=None`` must be preserved on a row that was never prompted: it is what
    makes the leaf resolve ``unknown`` instead of ``unsatisfied`` (A7). Callers that only
    mean to record practice should pass the row's existing ``attested_at`` back, not
    ``None``, since this is a whole-row write.

    No monotonic guard is applied to ``achieved``. §6.6's rule is that it is *"never set
    back to false **by the passage of time**"* — which forbids the freshness service
    (§9.8) clearing it, not a user correcting an attestation they made in error. This
    layer cannot see which of the two a caller is doing, so the guard belongs to the
    freshness pipeline, where the reason for the write is known.
    """
    row = session.get(Milestone, (player_id, key))
    if row is None:
        row = Milestone(player_id=player_id, key=key, kind=kind, class_=class_)
        session.add(row)
    row.kind = kind
    row.class_ = class_
    row.achieved = achieved
    row.value = value
    row.attested_at = attested_at
    row.last_practiced_at = last_practiced_at
    row.source = source
    row.observed_at = observed_at
    return row


# ---------------------------------------------------------------------------
# §6.12 ActiveRoadmap (A13)
# ---------------------------------------------------------------------------


def get_active_roadmaps(session: Session, player_id: int) -> Sequence[ActiveRoadmap]:
    return session.scalars(
        select(ActiveRoadmap)
        .where(ActiveRoadmap.player_id == player_id)
        .order_by(ActiveRoadmap.roadmap_id)
    ).all()


def roadmap_selection(session: Session, player_id: int) -> RoadmapSelection:
    """Build the §4.3 selection from ``ActiveRoadmap`` rows.

    Deliberately **not** part of ``PlayerState``. §16.1 fixes the engine's entry point as
    ``recommend(state, selection, content, profile, incumbent)`` — the selection is a
    separate parameter because it is live configuration the user changes between runs
    (§6.12), not an observation of the account. Folding it into the state object would
    make every golden-corpus fixture restate a setting it is not testing.

    Weights come back **raw**. Normalization is
    :meth:`~tracker.domain.types.RoadmapSelection.normalized`'s job and happens at the
    point of use (§6.12), so that deselecting one roadmap does not rescale the stored
    weight of the others.

    A player with no rows gets an empty selection rather than an error: "no roadmap
    chosen yet" is the state every account starts in.
    """
    rows = get_active_roadmaps(session, player_id)
    return RoadmapSelection(weights={row.roadmap_id: row.selection_weight for row in rows})


def set_active_roadmap(
    session: Session, player_id: int, roadmap_id: str, *, selection_weight: float
) -> ActiveRoadmap:
    """Select a roadmap, or change its raw weight (§6.12). Stored unnormalized."""
    row = session.get(ActiveRoadmap, (player_id, roadmap_id))
    if row is None:
        row = ActiveRoadmap(
            player_id=player_id, roadmap_id=roadmap_id, selection_weight=selection_weight
        )
        session.add(row)
        return row
    row.selection_weight = selection_weight
    return row


def clear_active_roadmap(session: Session, player_id: int, roadmap_id: str) -> None:
    """Deselect a roadmap. Silent when it was not selected — deselection is idempotent."""
    row = session.get(ActiveRoadmap, (player_id, roadmap_id))
    if row is not None:
        session.delete(row)


# ---------------------------------------------------------------------------
# §6.11 SyncEvent
# ---------------------------------------------------------------------------


def record_sync_event(
    session: Session,
    *,
    source: Source,
    accepted: bool,
    received_at: datetime,
    player_id: int | None = None,
    payload_version: int | None = None,
    remote_addr: str | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> SyncEvent:
    """Append one audit row (§6.11, §11.3).

    Append-only by construction: there is no update or delete helper here, because the
    value of an audit trail is that a later request cannot revise what an earlier one
    recorded.

    ``player_id`` defaults to ``None`` rather than being required, which is the whole point
    of A17 — §11.3 demands an audit row for *unauthenticated* writes, and an
    unauthenticated caller has no trusted identity. Writing an id parsed out of a rejected
    payload would put attacker-controlled data into the audit trail; leaving it ``NULL`` is
    the only honest record of "we do not know who this was".
    """
    row = SyncEvent(
        player_id=player_id,
        source=source,
        payload_version=payload_version,
        remote_addr=remote_addr,
        received_at=received_at,
        accepted=accepted,
        reason=reason,
        error=error,
    )
    session.add(row)
    return row
