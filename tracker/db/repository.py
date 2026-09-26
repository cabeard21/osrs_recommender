"""Account fact reads and writes; sync owns observation conflict resolution."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from tracker.db.models import (
    ContainerScan,
    ObservedItem,
    Player,
    QuestState,
    SkillSnapshot,
    SyncEvent,
    Unlock,
)
from tracker.domain.skills import SKILL_ALIASES
from tracker.domain.types import (
    SOURCE_PRECEDENCE,
    Container,
    QuestStatus,
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

_CANONICAL_SKILL = case(
    *((SkillSnapshot.skill == alias, name) for alias, name in SKILL_ALIASES.items()),
    else_=SkillSnapshot.skill,
)


def current_skill_snapshots(session: Session, player_id: int) -> Sequence[SkillSnapshot]:
    """The one current snapshot per canonical skill, resolved by §7.4.

    Resolved in SQL with a window function rather than by loading every row and reducing
    in Python. ``SkillSnapshot`` is an append-only history feeding the §15 XP chart, so
    the naive version's cost grows with the account's age — a player synced hourly for a
    year is a six-figure row count to answer a question about twenty-three skills.

    Legacy ``runecrafting`` and canonical ``runecraft`` rows share one partition. An exact
    time/source tie prefers the canonical stored key, then the newest row id. The returned
    ORM row retains its original key and provenance; read consumers present the canonical
    identity without rewriting history.
    """
    ranked = (
        select(
            SkillSnapshot,
            func.row_number()
            .over(
                partition_by=_CANONICAL_SKILL,
                order_by=(
                    SkillSnapshot.observed_at.desc(),
                    _SOURCE_RANK.asc(),
                    SkillSnapshot.skill.asc(),
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
