"""The §6 tables projected into the engine's :class:`PlayerState` (§16.1).

§16.1 requires ``recommend`` — and everything under it — to be a pure function over a
state object rather than something that reads the database internally.
:func:`build_player_state` is the entire bridge across that line: below it are ORM rows,
above it only frozen dataclasses. ``tests/progression/test_import_boundary.py`` keeps the
line one-way by failing if anything under ``tracker/progression/``,
``tracker/recommendations/`` or ``tracker/estimation/`` imports ``tracker.db``.

**This module supplies facts. It does not interpret them.** The temptation is to resolve
§6.5's three-way ownership table here, since that table appears in §6.5 next to the two
tables this module reads. It is resolved in :meth:`tracker.progression.evaluate.Evaluator._item`
instead, and for a reason worth restating: an ``item:`` leaf names no container, so an item
is only *absent* once **every** container has been scanned — a rule about the requirement
grammar, not about storage. Deciding it here would need a second copy of that rule, and two
copies of a three-valued rule is exactly the drift D8 exists to prevent. What this module
owes the evaluator is the two inputs the rule reads, faithfully:

* ``observed_items`` — one entry per item, containers merged;
* ``container_scans`` — an entry only where a scan actually happened.

**Absence is a value here, not a gap to fill.** Every mapping this module builds omits the
key when there is no row, and no default is ever substituted: a missing skill is not level
1, a missing container scan is not ``datetime.min``, ``xp IS NULL`` is not ``0`` (§6.2,
G5). Each of those defaults would read as a plausible convenience and each converts
*absence of evidence* into *evidence of absence*, which is the single error §4.5 names as
recurring at three separate layers of this design.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from sqlalchemy.orm import Session

from tracker.db import repository
from tracker.db.models import ContainerScan, Milestone, ObservedItem, SkillSnapshot
from tracker.domain.skills import canonical_skill_name
from tracker.domain.types import (
    AccountType,
    Container,
    ItemObservation,
    MilestoneState,
    PlayerState,
    SkillState,
    Tri,
)

__all__ = ["build_player_state"]


def build_player_state(session: Session, player_id: int) -> PlayerState:
    """Project every stored fact about one player into the engine's view of the account.

    Raises :class:`tracker.db.repository.PlayerNotFoundError` when no ``Player`` row
    exists. A player row with no fact rows is **not** an error — that is a freshly
    created account before its first sync, and it projects empty mappings with
    ``last_sync_at=None``, which is precisely the state that makes every leaf resolve
    ``unknown`` rather than ``unsatisfied`` (§4.5, §9.1). Raising on it would make "never
    synced" indistinguishable from "does not exist", which is the §4.5 error one level up
    from the ones §4.5 lists.

    ``last_sync_at`` is carried through untouched because it is load-bearing on its own
    (A6): :meth:`~tracker.progression.evaluate.Evaluator._combat_level` and
    ``_quest_points`` check it *before* looking at ``combat_level``/``quest_points``, so
    substituting a timestamp here — ``now`` for convenience, say — would flip an unsynced
    account's combat-level leaf from ``unknown`` to ``unsatisfied`` and turn "sync this"
    into "go train" (G3).
    """
    player = repository.require_player(session, player_id)

    return PlayerState(
        player_id=player.id,
        skills=_skills(repository.current_skill_snapshots(session, player_id)),
        unlocks={row.key: row.state for row in repository.get_unlocks(session, player_id)},
        quests={
            row.quest_id: row.status for row in repository.get_quest_states(session, player_id)
        },
        observed_items=_observed_items(repository.get_observed_items(session, player_id)),
        container_scans=_container_scans(repository.get_container_scans(session, player_id)),
        milestones=_milestones(repository.get_milestones(session, player_id)),
        combat_level=player.combat_level,
        quest_points=player.quest_points,
        # Pass-throughs, with no interpretation: a stored NULL stays None so the evaluator
        # can resolve it `unknown` (§4.5). Coercing to a default here would put the guess
        # somewhere no leaf could tell it apart from an answer.
        account_type=AccountType(player.account_type) if player.account_type else None,
        members=player.members,
        gp_sensitivity=player.gp_sensitivity,
        last_sync_at=player.last_sync_at,
    )


def _skills(snapshots: Iterable[SkillSnapshot]) -> Mapping[str, SkillState]:
    """§6.2. ``xp`` passes through untouched, ``None`` and all.

    ``None`` means unranked and must never become ``0`` (G5): a level-1 skill with no
    hiscores rank and a skill sitting at exactly 0 xp are the same in-game, but the
    projection cannot know which it is looking at, and writing ``0`` would claim it does.
    The hiscores' ``-1`` sentinel is normalized to ``None`` at the adapter boundary
    (§6.2, Step 7), so anything reaching here is already either a real number or an
    honest absence.

    ``repository.current_skill_snapshots`` has already applied §7.4 to pick one row per
    skill, so no skill can appear twice and no ordering assumption is made here.
    """
    return {
        canonical_skill_name(snapshot.skill): SkillState(
            level=snapshot.level,
            xp=snapshot.xp,
            source=snapshot.source,
            observed_at=snapshot.observed_at,
        )
        for snapshot in snapshots
    }


def _observed_items(rows: Iterable[ObservedItem]) -> Mapping[int, ItemObservation]:
    """Collapse ``(item_id, container)`` rows into one observation per item (§6.5).

    ``ObservedItem`` is keyed per container; ``ItemObservation`` is keyed per item, by
    the *numeric* OSRS id — the same id ``Item.item_id`` carries in content (§10.5), which
    is how an ``item:`` leaf reaches an observation at all.

    Three merge decisions, none of them free:

    * **``quantity`` sums across containers.** The player's holding of a fungible item is
      the total they have of it, wherever it sits — a rune pouch in the bank and one worn
      is two. Taking the maximum would understate the total, and taking the first row's
      value would make the answer depend on row order.
    * **``containers`` is the union.** It is read by
      :func:`tracker.progression.engine._sighting` to find which scan dates support a
      satisfied leaf; dropping one would hide fresh evidence and depress
      ``readiness_confidence`` for a player who owns more than one copy (§6.9, A4).
    * **``observed_at`` is the most recent sighting.** Same rationale, and it matches what
      ``_sighting`` does with the value: it is used as a per-container fallback age and
      then maximized. Carrying the oldest would penalise owning two of something.
    """
    merged: dict[int, ItemObservation] = {}
    for row in rows:
        seen = merged.get(row.item_id)
        if seen is None:
            merged[row.item_id] = ItemObservation(
                item_id=row.item_id,
                quantity=row.quantity,
                containers=frozenset({row.container}),
                observed_at=row.observed_at,
            )
            continue
        merged[row.item_id] = ItemObservation(
            item_id=row.item_id,
            quantity=seen.quantity + row.quantity,
            containers=seen.containers | {row.container},
            observed_at=max(seen.observed_at, row.observed_at),
        )
    return merged


def _container_scans(rows: Iterable[ContainerScan]) -> Mapping[Container, datetime]:
    """§6.5's staleness anchor — present only where a scan happened.

    A container with no row is simply absent from the mapping. It must **not** be given a
    sentinel: ``datetime.min`` would read as "scanned, infinitely long ago" and let
    :meth:`~tracker.progression.evaluate.Evaluator._item` answer *"you don't have a
    Voidwaker"* about a place nobody has ever looked, while ``now`` would claim a scan
    that never ran. Both turn §6.5's ``unknown`` row into its ``unsatisfied`` row, which
    is the difference between telling the user to open their bank and telling them to buy
    something they may already own.
    """
    return {row.container: row.scanned_at for row in rows}


def _milestones(rows: Iterable[Milestone]) -> Mapping[str, MilestoneState]:
    """§6.6 rows into the engine's milestone view, ``attested`` included (A7)."""
    return {
        row.key: MilestoneState(
            key=row.key,
            achieved=row.achieved,
            attested=_attested(row),
            kind=row.kind,
            class_=row.class_,
            value=row.value,
            last_practiced_at=row.last_practiced_at,
        )
        for row in rows
    }


def _attested(row: Milestone) -> Tri:
    """``attested_at IS NULL`` → ``unknown``; otherwise ``achieved`` lifted (§6.6, A7).

    The two negative cases must not collapse. *Never prompted* and *asked and declined*
    are both ``achieved = False`` in storage, and only ``attested_at`` separates them —
    the §4.5 pattern applied to attestation. Collapsing them makes a self-attested
    milestone the user has never seen a *blocker* ("you cannot do this") instead of an
    *unknown* ("we should ask"), which is exactly the wrong instruction (§9.1, G3).

    ``Tri.from_bool`` is only valid where absence of evidence is impossible, and past the
    ``None`` guard it is: a non-null ``attested_at`` is a record that the question was
    put to the user, so ``achieved`` is their answer rather than a default.
    """
    if row.attested_at is None:
        return Tri.UNKNOWN
    return Tri.from_bool(row.achieved)
