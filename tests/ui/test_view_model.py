"""Fast checks for account observation and status wording in retained UI views."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from tracker.domain.types import Confidence, Container, LeafRef, Status, UnlockState
from tracker.ui.capabilities import sort_rows, split_unknowns
from tracker.ui.staleness import humanize_age, ownership_note, scan_note
from tracker.ui.states import (
    STATE_CLASSES,
    STATE_LABELS,
    UiState,
    ui_state_for_status,
    ui_state_for_unlock,
)
from tracker.ui.unlocks import GROUPS, group_rows
from tracker.ui.view_model import (
    NO_READINESS,
    CapabilityRow,
    LeafRow,
    capability_row,
    readiness_label,
    skill_row,
    unlock_row,
)

NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)


def _capability(
    status: Status,
    *,
    capability_id: str = "budget_nh",
    unlock_fraction: float = 1.0,
    blockers: Sequence[LeafRef] = (),
    unknowns: Sequence[LeafRef] = (),
    readiness: Confidence | None = Confidence.HIGH,
    warnings: Sequence[str] = (),
    recommended_now: bool = False,
    recommended_now_reason: str | None = None,
) -> CapabilityRow:
    return capability_row(
        capability_id=capability_id,
        name="Budget Wilderness NH",
        status=status,
        unlock_fraction=unlock_fraction,
        blockers=blockers,
        unknowns=unknowns,
        readiness=readiness,
        warnings=warnings,
        recommended_now=recommended_now,
        recommended_now_reason=recommended_now_reason,
    )


# ---------------------------------------------------------------------------
# The state vocabulary (§15)
# ---------------------------------------------------------------------------


def test_every_state_maps_to_a_distinct_css_class() -> None:
    """The structural form of §15's rule, one level below the DOM.

    The browser test proves the *rendered* selectors are disjoint. This proves they cannot
    be otherwise: if two states ever shared a class, the DOM assertion would still pass on
    a page that happened not to show both.
    """
    assert len(set(STATE_CLASSES.values())) == len(UiState)


def test_unknown_and_locked_share_no_class_and_no_label() -> None:
    assert STATE_CLASSES[UiState.UNKNOWN] != STATE_CLASSES[UiState.LOCKED]
    assert STATE_LABELS[UiState.UNKNOWN] != STATE_LABELS[UiState.LOCKED]


def test_the_unknown_label_asks_for_a_sync_rather_than_for_work() -> None:
    """§15: unknown means "sync RuneLite", not "go do this"."""
    assert "observed" in STATE_LABELS[UiState.UNKNOWN]


@pytest.mark.parametrize("status", list(Status))
def test_every_capability_status_has_a_render_state(status: Status) -> None:
    assert ui_state_for_status(status).value == status.value


@pytest.mark.parametrize("state", list(UnlockState))
def test_every_unlock_state_has_a_render_state(state: UnlockState) -> None:
    assert ui_state_for_unlock(state).value == state.value


def test_available_does_not_collapse_into_locked() -> None:
    """§6.3 calls ``available`` the most likely place for an implementation to go wrong."""
    assert ui_state_for_unlock(UnlockState.AVAILABLE) is UiState.AVAILABLE


# ---------------------------------------------------------------------------
# §4.4's three layers
# ---------------------------------------------------------------------------


def test_readiness_renders_as_a_dash_when_status_is_unknown() -> None:
    """G3: unknown evidence stops at ``status`` and never flows down."""
    assert readiness_label(Status.UNKNOWN, None) == NO_READINESS


def test_a_readiness_stored_against_a_non_unlocked_status_is_not_rendered() -> None:
    """A stale ``CapabilityState`` row can hold a readiness its status does not license.

    The engine cannot produce that pair — ``CapabilityView`` makes it unrepresentable — but
    the two are independent columns in storage, and the UI reads the columns.
    """
    assert readiness_label(Status.LOCKED, Confidence.HIGH) == NO_READINESS
    row = _capability(Status.LOCKED, readiness=Confidence.HIGH)
    assert row.readiness is None
    assert row.readiness_label == NO_READINESS


def test_the_three_layers_are_three_separate_fields() -> None:
    """§4.4's middle worked example: unlocked, low confidence, not recommended."""
    row = _capability(
        Status.UNLOCKED,
        readiness=Confidence.LOW,
        recommended_now=False,
        recommended_now_reason="complete a refresher session first",
    )
    assert row.status_label == "unlocked"
    assert row.readiness_label == "low"
    assert row.recommended_label == "no — complete a refresher session first"


def test_conservative_coaching_never_reaches_back_and_revokes_status() -> None:
    """§4.4: coaching lives entirely in ``recommended_now``."""
    row = _capability(Status.UNLOCKED, readiness=Confidence.LOW, recommended_now=False)
    assert row.status is Status.UNLOCKED
    assert row.state is UiState.UNLOCKED


def test_blockers_and_unknowns_stay_separate_collections() -> None:
    row = _capability(
        Status.UNKNOWN,
        readiness=None,
        blockers=(LeafRef("skill", "magic", "Magic 94", 94),),
        unknowns=(LeafRef("item", "voidwaker", "Voidwaker"),),
    )
    assert [leaf.key for leaf in row.blockers] == ["magic"]
    assert [leaf.key for leaf in row.unknowns] == ["voidwaker"]


def test_a_milestone_unknown_is_a_question_not_a_sync() -> None:
    """§6.6/A7: no amount of syncing resolves "can you freeze-log?" — only being asked does.

    Left in the sync list, the leaf tells the reader to do something that cannot work, which
    reads as a broken app rather than a waiting one.
    """
    unknowns = (
        LeafRow.of(LeafRef("item", "voidwaker", "Voidwaker")),
        LeafRow.of(LeafRef("milestone", "teleblock_understanding", "Teleblock understanding")),
    )

    sync, questions = split_unknowns(unknowns)

    assert [leaf.key for leaf in sync] == ["voidwaker"]
    assert [leaf.key for leaf in questions] == ["teleblock_understanding"]


def test_splitting_unknowns_keeps_every_leaf() -> None:
    """The split partitions; it never drops. A leaf in neither list is a leaf nobody acts on."""
    unknowns = tuple(
        LeafRow.of(LeafRef(leaf_type, f"k_{leaf_type}", leaf_type))
        for leaf_type in ("item", "milestone", "skill", "quest", "unlock")
    )

    sync, questions = split_unknowns(unknowns)

    assert len(sync) + len(questions) == len(unknowns)
    assert set(sync).isdisjoint(questions)


def test_unknown_capabilities_sort_first() -> None:
    """§15 treats unknown as a call to action, and actions at the bottom go unread."""
    rows = [
        _capability(Status.UNLOCKED, capability_id="a"),
        _capability(Status.UNKNOWN, capability_id="b", readiness=None),
        _capability(Status.LOCKED, capability_id="c", readiness=None),
    ]
    assert sort_rows(rows)[0].capability_id == "b"


# ---------------------------------------------------------------------------
# §6.2 — unranked is not level 1
# ---------------------------------------------------------------------------


def test_unranked_skill_never_displays_a_level_or_progress() -> None:
    row = skill_row(skill_id="construction", name="Construction", is_combat=False, level=1, xp=None)
    assert row.is_ranked is False
    assert row.level is None
    assert row.level_label == "unranked"
    assert not any(character.isdigit() for character in row.level_label)
    assert row.progress == 0.0


def test_a_ranked_skill_keeps_its_level_and_xp() -> None:
    row = skill_row(skill_id="magic", name="Magic", is_combat=True, level=94, xp=7_195_629)
    assert row.is_ranked is True
    assert row.level_label == "94"
    assert row.progress == pytest.approx(94 / 99)


# ---------------------------------------------------------------------------
# §6.5 — observation, not ownership
# ---------------------------------------------------------------------------


def test_a_never_scanned_container_makes_no_claim_about_ownership() -> None:
    note = scan_note(Container.BANK, None, NOW)
    assert "never seen your bank" in note
    assert "don't have" not in note


def test_a_scanned_container_reports_the_age_of_the_look() -> None:
    """§6.5's own worked sentence."""
    assert scan_note(Container.BANK, NOW - timedelta(days=21), NOW) == (
        "Last saw your bank 3 weeks ago."
    )


def test_an_unmet_item_requirement_is_phrased_as_a_look_not_a_conclusion() -> None:
    note = ownership_note("Voidwaker", Container.BANK, NOW - timedelta(days=21), NOW)
    assert "not seen when we last looked" in note
    assert "you do not have" not in note.lower()


def test_an_item_in_a_never_scanned_container_says_we_cannot_tell() -> None:
    note = ownership_note("Voidwaker", Container.BANK, None, NOW)
    assert "we cannot tell" in note


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=5), "5 minutes ago"),
        (timedelta(hours=3), "3 hours ago"),
        (timedelta(days=2), "2 days ago"),
        (timedelta(days=21), "3 weeks ago"),
        (timedelta(days=60), "2 months ago"),
        (timedelta(days=800), "2 years ago"),
    ],
)
def test_ages_read_coarsely(delta: timedelta, expected: str) -> None:
    assert humanize_age(NOW - delta, NOW) == expected


def test_a_future_timestamp_does_not_render_a_negative_age() -> None:
    """Clock skew between the plugin's host and this one is a real case, not a hypothetical."""
    assert humanize_age(NOW + timedelta(hours=1), NOW) == "just now"


# ---------------------------------------------------------------------------
# Unlocks (§6.3, §15)
# ---------------------------------------------------------------------------


def test_unlocks_group_into_all_four_states() -> None:
    rows = [
        unlock_row("ancient_magicks", UnlockState.UNLOCKED),
        unlock_row("rigour", UnlockState.AVAILABLE),
        unlock_row("augury", UnlockState.LOCKED),
        unlock_row("ca_grandmaster", UnlockState.UNKNOWN),
    ]
    grouped = group_rows(rows)
    assert {state: len(items) for state, items in grouped.items()} == {
        UiState.UNLOCKED: 1,
        UiState.AVAILABLE: 1,
        UiState.LOCKED: 1,
        UiState.UNKNOWN: 1,
    }


def test_the_unknown_group_is_rendered_first() -> None:
    assert GROUPS[0][0] is UiState.UNKNOWN


def test_an_unlock_key_with_no_content_name_still_reads_as_words() -> None:
    assert unlock_row("diary_varrock_hard", UnlockState.UNKNOWN).name == "Diary Varrock Hard"
