"""Merging a validated sync payload into the §6 tables under §7.4's precedence rules.

This is stage 3 of §12's pipeline. Stage 2 (:mod:`tracker.api.sync`) has already proved
the payload conforms to the contract, so nothing here re-checks shapes — every key this
module reads is one the schema guarantees. What it does check is *provenance*, which the
contract cannot: whether this observation may overwrite what is stored.

**Why the guards live here and not in the repository.** The repository's writers are
last-write-wins by construction, deliberately — a repository that silently dropped writes
would make this layer impossible to test. §7.4's rules compare an incoming observation's
provenance against the stored one, and that comparison is the sync layer's job.

**§7.4, in the order the SDD states it:**

1. Prefer the most recent ``observed_at``.
2. On ties, prefer by source precedence: ``runelite > wise_old_man > hiscores``.
3. **Never allow a lower-precedence source to decrease a skill's stored XP** (G4).

Rule 3 is not implied by rules 1 and 2, which is the whole reason it is written down. The
hiscores — and therefore WOM — only update on logout, so a WOM read can carry a *newer*
``observed_at`` than a mid-session RuneLite observation while describing an *older* state
of the account. Recency alone would let it roll the account backwards.

**Idempotence.** A plugin that retries a POST, or a user who syncs twice without playing,
must not double the account's history. ``SkillSnapshot`` skips an exact duplicate;
the current-value tables are upserts already.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from tracker.db.models import Player, SkillSnapshot
from tracker.db.repository import (
    append_skill_snapshot,
    current_skill_snapshots,
    get_container_scans,
    get_observed_items,
    get_player_by_username,
    get_quest_states,
    get_unlocks,
    record_container_scan,
    upsert_observed_item,
    upsert_quest_state,
    upsert_unlock,
)
from tracker.domain.skills import canonical_skill_name
from tracker.domain.types import (
    SOURCE_PRECEDENCE,
    Container,
    QuestStatus,
    Source,
    UnlockState,
)

#: §7.4 rule 2 as a sortable rank, lowest first. Sources the rule does not name sort last,
#: deterministically — the same choice :mod:`tracker.db.repository` makes for the read
#: side, and it must stay the same choice, or a write this module permits could lose the
#: subsequent read.
_SOURCE_RANK: dict[Source, int] = {source: rank for rank, source in enumerate(SOURCE_PRECEDENCE)}
_UNRANKED = len(SOURCE_PRECEDENCE)


def _rank(source: Source) -> int:
    return _SOURCE_RANK.get(source, _UNRANKED)


@dataclass(frozen=True)
class MergeOutcome:
    """What one merge changed. Returned rather than logged, so Step 9's pipeline can put it
    in the ``SyncEvent`` trail and the UI can say *"12 facts updated, 1 ignored as stale"*.

    The ``*_ignored`` counts are as interesting as the writes: a plugin whose clock is
    wrong produces a sync where everything is ignored, and an outcome that reported only
    successes would look identical to one that did nothing.
    """

    player_id: int
    player_created: bool = False
    skills_written: int = 0
    skills_ignored: int = 0
    unlocks_written: int = 0
    unlocks_ignored: int = 0
    quests_written: int = 0
    quests_ignored: int = 0
    items_written: int = 0
    items_ignored: int = 0
    container_scans_written: int = 0
    container_scans_ignored: int = 0
    #: One line per fact rejected by a §7.4 guard, naming the rule. Diagnostics, not data:
    #: "why did my level not update" is otherwise unanswerable without a debugger.
    notes: tuple[str, ...] = field(default=())


def parse_timestamp(value: str) -> datetime:
    """Parse a contract timestamp into an aware UTC instant.

    The schema's pattern already requires an explicit offset, so this cannot produce a
    naive value from a payload that validated. The conversion to UTC is what matters: a
    plugin running in a non-UTC zone would otherwise store instants whose stored ordering
    depended on the offset each was written with.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:  # pragma: no cover — the contract's pattern forbids it
        raise ValueError(f"timestamp {value!r} carries no offset; §4.5 requires an instant")
    return parsed.astimezone(UTC)


def _supersedes(
    *,
    incoming_at: datetime,
    incoming_source: Source,
    stored_at: datetime,
    stored_source: Source,
) -> bool:
    """§7.4 rules 1 and 2 — may ``incoming`` overwrite ``stored``?

    An exact tie on both timestamp *and* source resolves as "yes", which is the harmless
    case: the same source claiming the same instant is either a retry or a re-read, and
    both write the value that is already there.
    """
    if incoming_at > stored_at:
        return True
    if incoming_at < stored_at:
        return False
    return _rank(incoming_source) <= _rank(stored_source)


def _regresses(
    *,
    incoming_xp: int | None,
    incoming_level: int,
    stored_xp: int | None,
    stored_level: int,
) -> bool:
    """Would writing this observation move the account *backwards*?

    XP is compared when both sides have it. When the incoming observation is unranked
    (``xp = None``, G5) and the stored one is not, that counts as a regression: an unranked
    read carries no information, and letting it become the current snapshot would erase a
    known value — the same loss as a numeric decrease, one step less obvious.

    Levels are the fallback when XP is absent on both sides, so a source that reports
    levels only still cannot roll the account back.
    """
    if incoming_xp is not None and stored_xp is not None:
        return incoming_xp < stored_xp
    if incoming_xp is None and stored_xp is not None:
        return True
    return incoming_level < stored_level


# ---------------------------------------------------------------------------
# §6.1 Player
# ---------------------------------------------------------------------------


def _merge_player(
    session: Session,
    payload: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> tuple[Player, bool]:
    """Find or create the ``Player``, and advance its account-wide scalars.

    Identity comes from ``username`` and nothing else. The payload deliberately carries no
    ``player_id``: an id chosen by the caller would let one plugin install write into
    another character's history (§6.11).

    ``last_sync_at`` guards the two scalars, because §6.1 gives them no ``observed_at`` of
    their own. It is load-bearing beyond this function too — A6 makes ``last_sync_at IS
    NULL`` the reason ``combat_level`` and ``quest_points`` leaves resolve ``unknown``, so
    the first sync flipping it from ``NULL`` is what turns those leaves from "we have never
    looked" into a real answer.
    """
    identity = payload["player"]
    username = identity["username"]

    player = get_player_by_username(session, username)
    created = player is None
    if player is None:
        player = Player(
            username=username,
            display_name=identity.get("display_name", username),
            created_at=observed_at,
        )
        session.add(player)
        session.flush()

    if player.last_sync_at is None or observed_at >= player.last_sync_at:
        if "display_name" in identity:
            player.display_name = identity["display_name"]
        if "combat_level" in identity:
            player.combat_level = identity["combat_level"]
        if "quest_points" in identity:
            player.quest_points = identity["quest_points"]
        player.last_sync_at = observed_at

    return player, created


# ---------------------------------------------------------------------------
# §6.2 SkillSnapshot — the table rule 3 exists for
# ---------------------------------------------------------------------------


def _is_duplicate_snapshot(
    stored: SkillSnapshot, *, level: int, xp: int | None, source: Source, at: datetime
) -> bool:
    """An exact re-observation. Appending it would grow the §15 XP chart with no new fact."""
    return (
        stored.observed_at == at
        and stored.source == source
        and stored.level == level
        and stored.xp == xp
    )


def _merge_skills(
    session: Session,
    player_id: int,
    entries: Sequence[Mapping[str, Any]],
    *,
    source: Source,
    observed_at: datetime,
    notes: list[str],
) -> tuple[int, int]:
    """Append skill observations, honouring §7.4 rule 3 (**G4**).

    ``SkillSnapshot`` is a log (§6.2), so "overwrite" is not something that happens here —
    the risk is subtler. A row appended with a newer ``observed_at`` becomes what
    :func:`current_skill_snapshots` *selects*, so appending a stale low-XP read from a
    lower-precedence source rolls the projection back without touching a single existing
    row. That is the rollback rule 3 forbids, and it is why the guard compares against the
    currently-selected snapshot rather than against the last row inserted.
    """
    current = {
        canonical_skill_name(row.skill): row for row in current_skill_snapshots(session, player_id)
    }
    written = ignored = 0

    for entry in entries:
        skill = canonical_skill_name(entry["skill"])
        level = entry["level"]
        xp = entry.get("xp")
        stored = current.get(skill)

        if stored is not None:
            if _rank(source) > _rank(stored.source) and _regresses(
                incoming_xp=xp,
                incoming_level=level,
                stored_xp=stored.xp,
                stored_level=stored.level,
            ):
                ignored += 1
                notes.append(
                    f"§7.4/3: ignored {skill} from {source.value} — it would lower the value "
                    f"observed by {stored.source.value}, which outranks it"
                )
                continue
            if _is_duplicate_snapshot(stored, level=level, xp=xp, source=source, at=observed_at):
                ignored += 1
                continue

        append_skill_snapshot(
            session,
            player_id,
            skill=skill,
            level=level,
            xp=xp,
            source=source,
            observed_at=observed_at,
        )
        written += 1

    return written, ignored


# ---------------------------------------------------------------------------
# §6.3 Unlock · §6.4 QuestState · §6.5 ObservedItem — current-value tables
# ---------------------------------------------------------------------------


def _merge_unlocks(
    session: Session,
    player_id: int,
    entries: Sequence[Mapping[str, Any]],
    *,
    source: Source,
    observed_at: datetime,
    notes: list[str],
) -> tuple[int, int]:
    """Upsert unlocks under rules 1 and 2, including the A12 reserved prefixes.

    ``spellbook_*``, ``diary_*`` and ``ca_*`` need no special handling here — that is the
    point of folding them into ``Unlock`` rather than giving them tables (§6.3, A12).
    """
    stored = {row.key: row for row in get_unlocks(session, player_id)}
    written = ignored = 0

    for entry in entries:
        key = entry["key"]
        existing = stored.get(key)
        if existing is not None and not _supersedes(
            incoming_at=observed_at,
            incoming_source=source,
            stored_at=existing.observed_at,
            stored_source=existing.source,
        ):
            ignored += 1
            notes.append(f"§7.4/1: ignored unlock {key} — a fresher observation is stored")
            continue

        upsert_unlock(
            session,
            player_id,
            key,
            state=UnlockState(entry["state"]),
            source=source,
            observed_at=observed_at,
        )
        written += 1

    return written, ignored


def _merge_quests(
    session: Session,
    player_id: int,
    entries: Sequence[Mapping[str, Any]],
    *,
    source: Source,
    observed_at: datetime,
    notes: list[str],
) -> tuple[int, int]:
    stored = {row.quest_id: row for row in get_quest_states(session, player_id)}
    written = ignored = 0

    for entry in entries:
        quest_id = entry["quest_id"]
        existing = stored.get(quest_id)
        if existing is not None and not _supersedes(
            incoming_at=observed_at,
            incoming_source=source,
            stored_at=existing.observed_at,
            stored_source=existing.source,
        ):
            ignored += 1
            notes.append(f"§7.4/1: ignored quest {quest_id} — a fresher observation is stored")
            continue

        upsert_quest_state(
            session,
            player_id,
            quest_id,
            status=QuestStatus(entry["status"]),
            source=source,
            observed_at=observed_at,
        )
        written += 1

    return written, ignored


def _merge_items(
    session: Session,
    player_id: int,
    entries: Sequence[Mapping[str, Any]],
    *,
    source: Source,
    observed_at: datetime,
    notes: list[str],
) -> tuple[int, int]:
    stored = {(row.item_id, row.container): row for row in get_observed_items(session, player_id)}
    scans = {row.container: row for row in get_container_scans(session, player_id)}
    written = ignored = 0

    for entry in entries:
        container = Container(entry["container"])
        scan = scans.get(container)
        if scan is not None and observed_at < scan.scanned_at:
            ignored += 1
            notes.append(
                f"§7.4/1: ignored item {entry['item_id']} in {container.value} — "
                "a fresher full-container scan is stored"
            )
            continue
        existing = stored.get((entry["item_id"], container))
        if existing is not None and not _supersedes(
            incoming_at=observed_at,
            incoming_source=source,
            stored_at=existing.observed_at,
            stored_source=existing.source,
        ):
            ignored += 1
            notes.append(
                f"§7.4/1: ignored item {entry['item_id']} in {container.value} — "
                "a fresher observation is stored"
            )
            continue

        upsert_observed_item(
            session,
            player_id,
            entry["item_id"],
            container,
            quantity=entry["quantity"],
            source=source,
            observed_at=observed_at,
        )
        written += 1

    return written, ignored


def _merge_container_scans(
    session: Session,
    player_id: int,
    entries: Sequence[Mapping[str, Any]],
    *,
    source: Source,
    notes: list[str],
) -> tuple[int, int, dict[Container, datetime]]:
    """Record every scan the payload reports — **including scans that found nothing.**

    This is the least obvious writer in the module and the most important. §6.5's
    three-way ownership table turns on whether a ``ContainerScan`` row exists: without one,
    an absent ``ObservedItem`` is ``unknown`` ("we have never looked"); with one, it is
    ``unsatisfied`` ("you do not have it"). A merge that skipped scans of empty containers
    — or that wrote a scan row only when it also wrote items — would leave every genuinely
    empty bank permanently indistinguishable from a bank nobody has opened, and the UI
    would say *"we have never seen your bank"* forever.

    Nothing in this function reads the item list, and that independence is the property the
    test asserts.
    """
    stored = {row.container: row for row in get_container_scans(session, player_id)}
    written = ignored = 0
    accepted: dict[Container, datetime] = {}

    for entry in entries:
        container = Container(entry["container"])
        scanned_at = parse_timestamp(entry["scanned_at"])
        existing = stored.get(container)
        if existing is not None and not _supersedes(
            incoming_at=scanned_at,
            incoming_source=source,
            stored_at=existing.scanned_at,
            stored_source=existing.source,
        ):
            ignored += 1
            notes.append(f"§7.4/1: ignored {container.value} scan — a later scan is recorded")
            continue

        stored[container] = record_container_scan(
            session, player_id, container, scanned_at=scanned_at, source=source
        )
        accepted[container] = scanned_at
        written += 1

    return written, ignored, accepted


def _reconcile_scanned_items(
    session: Session,
    player_id: int,
    accepted: Mapping[Container, datetime],
    entries: Sequence[Mapping[str, Any]],
) -> None:
    """A full scan replaces older container membership, including absent items.

    An observation made after the scan remains valid even if the older scan omitted it.
    A stale rejected scan has no effect. The scan and item list must be in the same
    payload for omission to establish absence.
    """
    if not accepted:
        return
    reported = {(entry["item_id"], Container(entry["container"])) for entry in entries}
    for row in get_observed_items(session, player_id):
        scan_at = accepted.get(row.container)
        if scan_at is None or row.observed_at > scan_at:
            continue
        if (row.item_id, row.container) not in reported:
            session.delete(row)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def merge_wom_skills(
    session: Session,
    player_id: int,
    entries: Sequence[Mapping[str, Any]],
    *,
    observed_at: datetime,
) -> MergeOutcome:
    """Merge a Wise Old Man skill read into §6.2, as the lower-precedence source (§7.4).

    This is the writer rule 3 was written against. WOM derives from the hiscores, which only
    update on logout (§7.2), so during a session its numbers are *behind* RuneLite's and a
    naive append would roll the projection back. :func:`_merge_skills` already refuses that,
    and it refuses it here for free — the guard is about relative precedence, not about which
    caller invoked it, which is why this function is a wrapper and not a reimplementation.

    **It deliberately does not touch the player's scalars, and above all not**
    ``last_sync_at``. A6 gives that column a specific meaning — *"the account's own scalars
    have been observed"* — and makes ``last_sync_at IS NULL`` the reason ``combat_level`` and
    ``quest_points`` resolve ``unknown``. WOM supplies neither scalar, so advancing the column
    would assert that they had been observed when they had not: precisely the "observation
    time is not truth" defect §4.5 names, one column over. A WOM-only account therefore keeps
    reporting those two leaves as ``unknown``, which is the honest answer.

    ``observed_at`` must be WOM's snapshot timestamp, never the moment of the fetch — §4.5
    again, and the same rule D10 applies to prices.
    """
    notes: list[str] = []
    written, ignored = _merge_skills(
        session,
        player_id,
        entries,
        source=Source.WISE_OLD_MAN,
        observed_at=observed_at,
        notes=notes,
    )
    return MergeOutcome(
        player_id=player_id,
        skills_written=written,
        skills_ignored=ignored,
        notes=tuple(notes),
    )


def merge_sync_payload(
    session: Session,
    payload: Mapping[str, Any],
    *,
    source: Source = Source.RUNELITE,
) -> MergeOutcome:
    """Merge one validated payload into the §6 tables, returning what changed.

    **The caller commits.** Every fact in one payload is one observation of one account at
    one instant, so a merge that half-applied would leave the account describing a moment
    that never existed — the transaction boundary belongs to whoever owns the request
    (Step 9's pipeline), not to this function.

    ``source`` is a parameter rather than a constant because §7.4's rules are about
    *relative* precedence, and the same merge must serve the WOM importer (Step 9), which
    supplies ``Source.WISE_OLD_MAN`` and is exactly the lower-precedence writer rule 3 is
    written against.
    """
    observed_at = parse_timestamp(payload["observed_at"])
    notes: list[str] = []

    player, created = _merge_player(session, payload, observed_at=observed_at)
    player_id = player.id

    skills_written, skills_ignored = _merge_skills(
        session,
        player_id,
        payload.get("skills", []),
        source=source,
        observed_at=observed_at,
        notes=notes,
    )
    unlocks_written, unlocks_ignored = _merge_unlocks(
        session,
        player_id,
        payload.get("unlocks", []),
        source=source,
        observed_at=observed_at,
        notes=notes,
    )
    quests_written, quests_ignored = _merge_quests(
        session,
        player_id,
        payload.get("quests", []),
        source=source,
        observed_at=observed_at,
        notes=notes,
    )
    items_written, items_ignored = _merge_items(
        session,
        player_id,
        payload.get("observed_items", []),
        source=source,
        observed_at=observed_at,
        notes=notes,
    )
    scans_written, scans_ignored, accepted_scans = _merge_container_scans(
        session,
        player_id,
        payload.get("container_scans", []),
        source=source,
        notes=notes,
    )
    _reconcile_scanned_items(session, player_id, accepted_scans, payload.get("observed_items", []))
    # v1 compatibility: the schema still validates optional practice_events from older
    # clients, but practice evidence has no surviving persistence or domain consumer.

    session.flush()

    return MergeOutcome(
        player_id=player_id,
        player_created=created,
        skills_written=skills_written,
        skills_ignored=skills_ignored,
        unlocks_written=unlocks_written,
        unlocks_ignored=unlocks_ignored,
        quests_written=quests_written,
        quests_ignored=quests_ignored,
        items_written=items_written,
        items_ignored=items_ignored,
        container_scans_written=scans_written,
        container_scans_ignored=scans_ignored,
        notes=tuple(notes),
    )
