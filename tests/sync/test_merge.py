"""§7.4 precedence, G4, and the §6.5 scan rule that makes "unknown" distinguishable."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.db.models import (
    ContainerScan,
    ObservedItem,
    SkillSnapshot,
    Unlock,
)
from tracker.db.repository import current_skill_snapshots, get_player_by_username
from tracker.domain.types import Container, Source, UnlockState
from tracker.sync.merge import merge_sync_payload

VOIDWAKER = 27_690


def _magic(level: int, xp: int | None) -> dict[str, Any]:
    return {"skills": [{"skill": "magic", "level": level, "xp": xp}]}


def _current_xp(session: Session, player_id: int, skill: str = "magic") -> int | None:
    rows = {row.skill: row for row in current_skill_snapshots(session, player_id)}
    return rows[skill].xp


# ---------------------------------------------------------------------------
# §6.1 — identity
# ---------------------------------------------------------------------------


def test_a_first_sync_creates_the_player(
    session: Session, build_payload: Callable[..., Any]
) -> None:
    outcome = merge_sync_payload(session, build_payload())

    assert outcome.player_created is True
    assert get_player_by_username(session, "zezima") is not None


def test_a_second_sync_reuses_the_player(
    session: Session, build_payload: Callable[..., Any], now: datetime
) -> None:
    """Identity is the username and nothing else — the payload carries no ``player_id``,
    because an id chosen by the caller would let one install write into another
    character's history (§6.11).
    """
    first = merge_sync_payload(session, build_payload())
    second = merge_sync_payload(session, build_payload(now + timedelta(minutes=5)))

    assert second.player_created is False
    assert second.player_id == first.player_id


def test_the_first_sync_sets_last_sync_at(
    session: Session, build_payload: Callable[..., Any], now: datetime
) -> None:
    """A6 — ``last_sync_at IS NULL`` is what makes the ``combat_level`` and
    ``quest_points`` leaves resolve ``unknown``. Flipping it is how those leaves stop
    meaning "we have never looked".
    """
    payload = build_payload()
    payload["player"]["combat_level"] = 126

    merge_sync_payload(session, payload)

    player = get_player_by_username(session, "zezima")
    assert player is not None
    assert player.last_sync_at == now
    assert player.combat_level == 126


def test_an_older_payload_does_not_roll_back_the_account_scalars(
    session: Session, build_payload: Callable[..., Any], now: datetime, earlier: datetime
) -> None:
    fresh = build_payload(now)
    fresh["player"]["combat_level"] = 126
    merge_sync_payload(session, fresh)

    stale = build_payload(earlier)
    stale["player"]["combat_level"] = 3
    merge_sync_payload(session, stale)

    player = get_player_by_username(session, "zezima")
    assert player is not None
    assert player.combat_level == 126
    assert player.last_sync_at == now


# ---------------------------------------------------------------------------
# G4 — §7.4 rule 3, the rule the other two do not imply
# ---------------------------------------------------------------------------


def test_g4_stale_wom_xp_does_not_overwrite_fresher_runelite_xp(
    session: Session, build_payload: Callable[..., Any], now: datetime, earlier: datetime
) -> None:
    """**G4**, in the exact shape §7.4 describes.

    The hiscores — and therefore WOM — only update on logout, so this WOM read carries the
    *newer* ``observed_at`` while describing an *older* account. Rules 1 and 2 would both
    let it win: it is more recent, and precedence is only consulted on a tie. Rule 3 is
    what stops it, and this test is why rule 3 is written down separately.
    """
    merge_sync_payload(
        session, build_payload(earlier, **_magic(94, 7_195_629)), source=Source.RUNELITE
    )

    outcome = merge_sync_payload(
        session, build_payload(now, **_magic(87, 3_000_000)), source=Source.WISE_OLD_MAN
    )

    assert _current_xp(session, outcome.player_id) == 7_195_629
    assert outcome.skills_ignored == 1
    assert outcome.skills_written == 0
    assert any("§7.4/3" in note for note in outcome.notes)


def test_g4_an_unranked_read_from_a_lower_source_does_not_erase_a_known_xp(
    session: Session, build_payload: Callable[..., Any], now: datetime, earlier: datetime
) -> None:
    """G5 meeting G4. ``xp = None`` means unranked (§6.2) — no information, not zero.

    Letting an unranked WOM read become the current snapshot would erase a known value.
    That is the same loss as a numeric decrease, one step less obvious, and a naive
    ``incoming < stored`` comparison does not catch it because ``None`` is not comparable.
    """
    merge_sync_payload(
        session, build_payload(earlier, **_magic(94, 7_195_629)), source=Source.RUNELITE
    )
    merge_sync_payload(session, build_payload(now, **_magic(94, None)), source=Source.WISE_OLD_MAN)

    player = get_player_by_username(session, "zezima")
    assert player is not None
    assert _current_xp(session, player.id) == 7_195_629


def test_a_lower_precedence_source_may_still_increase_xp(
    session: Session, build_payload: Callable[..., Any], now: datetime, earlier: datetime
) -> None:
    """Rule 3 forbids *decreases*, not lower-precedence writes.

    WOM is the primary remote source (§7.2) and the only one that sees an account whose
    owner has not opened RuneLite in a week. Reading rule 3 as "runelite always wins"
    would make that integration inert.
    """
    merge_sync_payload(
        session, build_payload(earlier, **_magic(87, 3_000_000)), source=Source.RUNELITE
    )
    outcome = merge_sync_payload(
        session, build_payload(now, **_magic(94, 7_195_629)), source=Source.WISE_OLD_MAN
    )

    assert _current_xp(session, outcome.player_id) == 7_195_629
    assert outcome.skills_written == 1


def test_the_same_source_may_correct_its_own_earlier_value(
    session: Session, build_payload: Callable[..., Any], now: datetime, earlier: datetime
) -> None:
    """§7.4 rule 3 names a *lower-precedence* source. A source correcting itself is not the
    rollback the rule guards against, and the SDD does not forbid it.
    """
    merge_sync_payload(
        session, build_payload(earlier, **_magic(94, 7_195_629)), source=Source.RUNELITE
    )
    outcome = merge_sync_payload(
        session, build_payload(now, **_magic(87, 3_000_000)), source=Source.RUNELITE
    )

    assert _current_xp(session, outcome.player_id) == 3_000_000


def test_repeating_a_sync_appends_no_duplicate_snapshot(
    session: Session, build_payload: Callable[..., Any], now: datetime
) -> None:
    """A retried POST must not grow the §15 XP chart with a fact it already contains."""
    payload = build_payload(now, **_magic(94, 7_195_629))
    merge_sync_payload(session, payload)
    outcome = merge_sync_payload(session, payload)

    assert len(session.scalars(select(SkillSnapshot)).all()) == 1
    assert outcome.skills_ignored == 1


# ---------------------------------------------------------------------------
# §7.4 rules 1 and 2 — recency, then precedence on a tie
# ---------------------------------------------------------------------------


def test_a_tie_on_observed_at_resolves_by_source_precedence(
    session: Session, build_payload: Callable[..., Any], now: datetime
) -> None:
    """§7.4 rule 2. Both observations claim the same instant, so recency cannot decide;
    ``runelite > wise_old_man`` does.
    """
    merge_sync_payload(
        session,
        build_payload(now, unlocks=[{"key": "rigour", "state": "unlocked"}]),
        source=Source.RUNELITE,
    )

    outcome = merge_sync_payload(
        session,
        build_payload(now, unlocks=[{"key": "rigour", "state": "locked"}]),
        source=Source.WISE_OLD_MAN,
    )

    row = session.get(Unlock, (outcome.player_id, "rigour"))
    assert row is not None
    assert row.state is UnlockState.UNLOCKED
    assert outcome.unlocks_ignored == 1


def test_a_tie_lets_the_same_source_rewrite_its_own_value(
    session: Session, build_payload: Callable[..., Any], now: datetime
) -> None:
    """An exact tie on both timestamp and source is a retry or a re-read; both write the
    value already stored, so refusing it would only make merges non-idempotent.
    """
    merge_sync_payload(
        session,
        build_payload(now, unlocks=[{"key": "rigour", "state": "unlocked"}]),
        source=Source.RUNELITE,
    )
    outcome = merge_sync_payload(
        session,
        build_payload(now, unlocks=[{"key": "rigour", "state": "unlocked"}]),
        source=Source.RUNELITE,
    )

    assert outcome.unlocks_written == 1


def test_an_older_observation_never_overwrites_a_newer_one(
    session: Session, build_payload: Callable[..., Any], now: datetime, earlier: datetime
) -> None:
    """§7.4 rule 1, across all three current-value tables at once."""
    merge_sync_payload(
        session,
        build_payload(
            now,
            unlocks=[{"key": "rigour", "state": "unlocked"}],
            quests=[{"quest_id": "desert_treasure_i", "status": "complete"}],
            observed_items=[{"item_id": VOIDWAKER, "quantity": 1, "container": "bank"}],
        ),
    )

    outcome = merge_sync_payload(
        session,
        build_payload(
            earlier,
            unlocks=[{"key": "rigour", "state": "locked"}],
            quests=[{"quest_id": "desert_treasure_i", "status": "not_started"}],
            observed_items=[{"item_id": VOIDWAKER, "quantity": 5, "container": "bank"}],
        ),
    )

    assert (outcome.unlocks_ignored, outcome.quests_ignored, outcome.items_ignored) == (1, 1, 1)
    item = session.get(ObservedItem, (outcome.player_id, VOIDWAKER, Container.BANK))
    assert item is not None
    assert item.quantity == 1


@pytest.mark.parametrize("key", ["spellbook_ancient", "diary_varrock_hard", "ca_grandmaster"])
def test_reserved_prefix_unlocks_need_no_special_handling(
    session: Session, build_payload: Callable[..., Any], key: str
) -> None:
    """A12 — spellbook, diary and combat-achievement state are ``Unlock`` rows. That they
    require no branch in the merge is the point of the decision, so this test asserts the
    absence of one.
    """
    outcome = merge_sync_payload(
        session, build_payload(unlocks=[{"key": key, "state": "unlocked"}])
    )

    assert session.get(Unlock, (outcome.player_id, key)) is not None


# ---------------------------------------------------------------------------
# §6.5 — the scan is the anchor, not the items
# ---------------------------------------------------------------------------


def test_an_empty_bank_scan_is_still_recorded(
    session: Session, build_payload: Callable[..., Any], now: datetime, to_iso: Callable[..., str]
) -> None:
    """The §6.5 rule that makes "unsatisfied" distinguishable from "unknown".

    This payload scans the bank and reports no items — a real state, not a malformed sync.
    Without the ``ContainerScan`` row an absent ``ObservedItem`` stays ``unknown``, and the
    UI says *"we have never seen your bank"* forever, no matter how often it is scanned. A
    merge that wrote scan rows only alongside items would produce exactly that.
    """
    outcome = merge_sync_payload(
        session,
        build_payload(
            now,
            observed_items=[],
            container_scans=[{"container": "bank", "scanned_at": to_iso(now)}],
        ),
    )

    scan = session.get(ContainerScan, (outcome.player_id, Container.BANK))
    assert scan is not None
    assert scan.scanned_at == now
    assert outcome.container_scans_written == 1
    assert outcome.items_written == 0


def test_a_scan_survives_the_items_key_being_absent_entirely(
    session: Session, build_payload: Callable[..., Any], now: datetime, to_iso: Callable[..., str]
) -> None:
    """The same rule with the array absent rather than empty — a plugin may omit a key it
    has nothing to say about, and the scan must survive that too.
    """
    outcome = merge_sync_payload(
        session,
        build_payload(now, container_scans=[{"container": "equipment", "scanned_at": to_iso(now)}]),
    )

    assert session.get(ContainerScan, (outcome.player_id, Container.EQUIPMENT)) is not None


def test_new_full_scan_removes_absent_items_in_that_container_only(
    session: Session, build_payload: Callable[..., Any], now: datetime, to_iso: Callable[..., str]
) -> None:
    later = now + timedelta(minutes=1)
    first = merge_sync_payload(
        session,
        build_payload(
            now,
            observed_items=[
                {"item_id": VOIDWAKER, "quantity": 1, "container": "bank"},
                {"item_id": VOIDWAKER, "quantity": 1, "container": "inventory"},
            ],
            container_scans=[
                {"container": "bank", "scanned_at": to_iso(now)},
                {"container": "inventory", "scanned_at": to_iso(now)},
            ],
        ),
    )
    merge_sync_payload(
        session,
        build_payload(
            later,
            observed_items=[],
            container_scans=[{"container": "bank", "scanned_at": to_iso(later)}],
        ),
    )
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.BANK)) is None
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.INVENTORY)) is not None


def test_stale_full_scan_does_not_remove_newer_item(
    session: Session,
    build_payload: Callable[..., Any],
    now: datetime,
    earlier: datetime,
    to_iso: Callable[..., str],
) -> None:
    first = merge_sync_payload(
        session,
        build_payload(
            now,
            observed_items=[{"item_id": VOIDWAKER, "quantity": 1, "container": "bank"}],
            container_scans=[{"container": "bank", "scanned_at": to_iso(now)}],
        ),
    )
    merge_sync_payload(
        session,
        build_payload(
            earlier,
            observed_items=[],
            container_scans=[{"container": "bank", "scanned_at": to_iso(earlier)}],
        ),
    )
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.BANK)) is not None


def test_full_scan_keeps_a_sighting_newer_than_its_scan_time(
    session: Session,
    build_payload: Callable[..., Any],
    now: datetime,
    earlier: datetime,
    to_iso: Callable[..., str],
) -> None:
    first = merge_sync_payload(
        session,
        build_payload(
            now, observed_items=[{"item_id": VOIDWAKER, "quantity": 1, "container": "bank"}]
        ),
    )
    merge_sync_payload(
        session,
        build_payload(
            now,
            observed_items=[],
            container_scans=[{"container": "bank", "scanned_at": to_iso(earlier)}],
        ),
    )
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.BANK)) is not None


def test_full_scan_moves_item_between_containers_without_stale_membership(
    session: Session, build_payload: Callable[..., Any], now: datetime, to_iso: Callable[..., str]
) -> None:
    later = now + timedelta(minutes=1)
    first = merge_sync_payload(
        session,
        build_payload(
            now,
            observed_items=[{"item_id": VOIDWAKER, "quantity": 1, "container": "bank"}],
            container_scans=[{"container": "bank", "scanned_at": to_iso(now)}],
        ),
    )
    merge_sync_payload(
        session,
        build_payload(
            later,
            observed_items=[{"item_id": VOIDWAKER, "quantity": 1, "container": "inventory"}],
            container_scans=[
                {"container": "bank", "scanned_at": to_iso(later)},
                {"container": "inventory", "scanned_at": to_iso(later)},
            ],
        ),
    )
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.BANK)) is None
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.INVENTORY)) is not None


def test_omitted_item_list_with_full_scan_clears_a_container(
    session: Session, build_payload: Callable[..., Any], now: datetime, to_iso: Callable[..., str]
) -> None:
    later = now + timedelta(minutes=1)
    first = merge_sync_payload(
        session,
        build_payload(
            now, observed_items=[{"item_id": VOIDWAKER, "quantity": 1, "container": "bank"}]
        ),
    )
    merge_sync_payload(
        session,
        build_payload(later, container_scans=[{"container": "bank", "scanned_at": to_iso(later)}]),
    )
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.BANK)) is None


def test_omitted_items_without_a_scan_leave_membership_unchanged(
    session: Session, build_payload: Callable[..., Any], now: datetime
) -> None:
    first = merge_sync_payload(
        session,
        build_payload(
            now, observed_items=[{"item_id": VOIDWAKER, "quantity": 1, "container": "bank"}]
        ),
    )
    merge_sync_payload(session, build_payload(now + timedelta(minutes=1)))
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.BANK)) is not None


def test_item_observation_older_than_latest_full_scan_cannot_restore_absent_item(
    session: Session,
    build_payload: Callable[..., Any],
    now: datetime,
    earlier: datetime,
    to_iso: Callable[..., str],
) -> None:
    first = merge_sync_payload(
        session,
        build_payload(
            now,
            observed_items=[],
            container_scans=[{"container": "bank", "scanned_at": to_iso(now)}],
        ),
    )
    outcome = merge_sync_payload(
        session,
        build_payload(
            earlier, observed_items=[{"item_id": VOIDWAKER, "quantity": 1, "container": "bank"}]
        ),
    )
    assert outcome.items_ignored == 1
    assert session.get(ObservedItem, (first.player_id, VOIDWAKER, Container.BANK)) is None


def test_duplicate_scans_in_one_payload_cannot_roll_back_latest_scan(
    session: Session,
    build_payload: Callable[..., Any],
    now: datetime,
    earlier: datetime,
    to_iso: Callable[..., str],
) -> None:
    result = merge_sync_payload(
        session,
        build_payload(
            now,
            observed_items=[],
            container_scans=[
                {"container": "bank", "scanned_at": to_iso(now)},
                {"container": "bank", "scanned_at": to_iso(earlier)},
            ],
        ),
    )
    scan = session.get(ContainerScan, (result.player_id, Container.BANK))
    assert scan is not None
    assert scan.scanned_at == now
    assert result.container_scans_ignored == 1


def test_a_scan_timestamp_never_moves_backwards(
    session: Session,
    build_payload: Callable[..., Any],
    now: datetime,
    earlier: datetime,
    to_iso: Callable[..., str],
) -> None:
    """``scanned_at`` is what §6.9's aged-observation rule (A4) measures against, so a
    stale scan winning would make a freshly-seen bank look aged.
    """
    merge_sync_payload(
        session,
        build_payload(now, container_scans=[{"container": "bank", "scanned_at": to_iso(now)}]),
    )
    outcome = merge_sync_payload(
        session,
        build_payload(
            earlier, container_scans=[{"container": "bank", "scanned_at": to_iso(earlier)}]
        ),
    )

    scan = session.get(ContainerScan, (outcome.player_id, Container.BANK))
    assert scan is not None
    assert scan.scanned_at == now
    assert outcome.container_scans_ignored == 1


def test_the_scan_timestamp_is_the_containers_own_not_the_payloads(
    session: Session,
    build_payload: Callable[..., Any],
    now: datetime,
    earlier: datetime,
    to_iso: Callable[..., str],
) -> None:
    """§4.5 — the bank was seen an hour ago and the snapshot was taken now. Collapsing the
    two would claim a scan that never happened, which is exactly the confusion between
    observation time and truth that §4.5 names.
    """
    outcome = merge_sync_payload(
        session,
        build_payload(now, container_scans=[{"container": "bank", "scanned_at": to_iso(earlier)}]),
    )

    scan = session.get(ContainerScan, (outcome.player_id, Container.BANK))
    assert scan is not None
    assert scan.scanned_at == earlier


# ---------------------------------------------------------------------------
# Deprecated v1 practice field
# ---------------------------------------------------------------------------


def test_v1_practice_events_do_not_change_the_account_merge(
    session: Session, build_payload: Callable[..., Any], now: datetime, to_iso: Callable[..., str]
) -> None:
    """Validated events from an old client are ignored at the merge boundary."""
    base = build_payload(now, skills=[{"skill": "magic", "level": 94, "xp": 7_195_629}])
    with_practice = dict(
        base,
        practice_events=[
            {
                "domain": "lms",
                "started_at": to_iso(now - timedelta(minutes=7)),
                "ended_at": to_iso(now),
                "evidence_type": "lms_match_completed",
            }
        ],
    )
    first = merge_sync_payload(session, with_practice)
    second = merge_sync_payload(session, base)

    assert first.skills_written == 1
    assert second.skills_written == 0
    assert not hasattr(first, "practice_events_written")
