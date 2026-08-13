"""§15's honesty rules, asserted where they are decided rather than where they are drawn.

Every test here runs without a browser and without a database. That is the point: a rule
that can only be checked by rendering a page is a rule that stops being checked the first
time the render gets slow or flaky, and these are the rules the whole design rests on.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from tracker.domain.types import Confidence, Container, GpSensitivity, LeafRef, Status, UnlockState
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
    GP_SENSITIVITY_LABELS,
    NO_READINESS,
    CapabilityRow,
    GoalProgressRow,
    LeafRow,
    NeededForRow,
    RoadmapOptionRow,
    SpeedUpRow,
    UnblockRow,
    assert_at_most_one_refresher,
    capability_row,
    mark_primary,
    readiness_label,
    recommendation_entry_row,
    roadmap_selector_model,
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


def test_an_unranked_skill_has_no_level_at_all() -> None:
    row = skill_row(skill_id="construction", name="Construction", is_combat=False, level=1, xp=None)
    assert row.is_ranked is False
    assert row.level is None
    assert row.level_label == "unranked"


def test_an_unranked_skill_label_contains_no_digit() -> None:
    """The plan's exit criterion, stated as the property rather than as the token "1"."""
    row = skill_row(skill_id="construction", name="Construction", is_combat=False, level=1, xp=None)
    assert not any(character.isdigit() for character in row.level_label)


def test_an_unranked_skill_shows_no_progress() -> None:
    """1/99 of a bar is the level-1 claim smuggled back in as pixels."""
    row = skill_row(skill_id="construction", name="Construction", is_combat=False, level=1, xp=None)
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


# ---------------------------------------------------------------------------
# Step 11 — Recommendations: G10, and factor rows read off the persisted JSON (§9.10)
# ---------------------------------------------------------------------------


def _entry(*, candidate_id: str = "train_magic_87_to_94", is_refresher: bool = False):
    return recommendation_entry_row(
        candidate_id=candidate_id,
        rank=1,
        name="Train Magic 87 -> 94",
        is_refresher=is_refresher,
        score=1.42,
        factors={"pvp_value": {"value": 0.9, "weight": 1.0, "log_contribution": 0.61}},
        reason="high PvP value (+0.61)",
        estimated_hours=4.5,
        estimated_gp=1_800_000,
        confidence=Confidence.MEDIUM,
    )


def test_factor_rows_read_the_persisted_json_verbatim() -> None:
    """§9.5: the breakdown drawer's numbers are the same ones the "Why" line came from."""
    row = _entry()
    assert len(row.factors) == 1
    factor = row.factors[0]
    assert factor.name == "pvp_value"
    assert factor.value == pytest.approx(0.9)
    assert factor.log_contribution == pytest.approx(0.61)


def test_at_most_one_refresher_passes_with_zero_or_one() -> None:
    assert_at_most_one_refresher(())
    assert_at_most_one_refresher((_entry(is_refresher=False),))
    assert_at_most_one_refresher((_entry(is_refresher=True),))


def test_g10_fails_loudly_on_two_refreshers() -> None:
    """The render-time assertion (belt-and-braces over Step 6's own guarantee, §9.8, D9)."""
    rows = (
        _entry(candidate_id="refresh_a", is_refresher=True),
        _entry(candidate_id="refresh_b", is_refresher=True),
    )
    with pytest.raises(AssertionError, match="G10"):
        assert_at_most_one_refresher(rows)


def test_priority_stars_are_clamped_between_one_and_five() -> None:
    assert _entry().priority_stars.count("★") >= 1
    low = recommendation_entry_row(
        candidate_id="x",
        rank=1,
        name="x",
        is_refresher=False,
        score=0.0,
        factors={},
        reason="",
        estimated_hours=None,
        estimated_gp=None,
        confidence=Confidence.LOW,
    )
    assert low.priority_stars.count("★") == 1


# ---------------------------------------------------------------------------
# Step 11 — Roadmaps: primary is a display rule over the live §6.12 selection
# ---------------------------------------------------------------------------


def test_mark_primary_is_the_highest_selected_weight() -> None:
    options = (
        RoadmapOptionRow("anti_pk", "Anti-PKer", selected=True, selection_weight=0.25),
        RoadmapOptionRow("main_nh", "Main NH", selected=True, selection_weight=1.0),
    )
    assert mark_primary(options)[0].roadmap_id == "main_nh"


def test_mark_primary_is_empty_when_nothing_is_selected() -> None:
    options = (RoadmapOptionRow("main_nh", "Main NH", selected=False, selection_weight=0.0),)
    assert mark_primary(options) == ()


def test_ties_break_by_id_so_primary_is_deterministic() -> None:
    options = (
        RoadmapOptionRow("b_roadmap", "B", selected=True, selection_weight=1.0),
        RoadmapOptionRow("a_roadmap", "A", selected=True, selection_weight=1.0),
    )
    assert mark_primary(options)[0].roadmap_id == "a_roadmap"


# ---------------------------------------------------------------------------
# The global selector — a model, so "is there a dropdown" needs no browser
# ---------------------------------------------------------------------------


def _noop(_roadmap_id: str) -> None:  # pragma: no cover — never called by these tests
    return None


def test_no_selector_when_there_is_nothing_to_choose_between() -> None:
    """No player and no corpus roadmaps are the same answer: draw no control at all."""
    assert roadmap_selector_model((), _noop) is None


def test_the_selector_shows_mark_primarys_answer() -> None:
    options = (
        RoadmapOptionRow("anti_pk", "Anti-PKer", selected=True, selection_weight=0.25),
        RoadmapOptionRow("main_nh", "Main NH", selected=True, selection_weight=1.0),
    )
    model = roadmap_selector_model(options, _noop)
    assert model is not None
    assert model.value == mark_primary(options)[0].roadmap_id == "main_nh"


def test_the_selector_inherits_the_tie_break_rather_than_inventing_one() -> None:
    options = (
        RoadmapOptionRow("b_roadmap", "B", selected=True, selection_weight=1.0),
        RoadmapOptionRow("a_roadmap", "A", selected=True, selection_weight=1.0),
    )
    model = roadmap_selector_model(options, _noop)
    assert model is not None
    assert model.value == "a_roadmap"


def test_the_selector_has_no_value_when_nothing_is_selected_yet() -> None:
    """A fresh player row with no ``ActiveRoadmap``: the options exist, the choice does not.

    ``value`` must be ``None`` rather than the first option — preselecting one would be the
    UI asserting a roadmap the player never chose.
    """
    options = (RoadmapOptionRow("main_nh", "Main NH", selected=False, selection_weight=0.0),)
    model = roadmap_selector_model(options, _noop)
    assert model is not None
    assert model.value is None
    assert model.options == options


# ---------------------------------------------------------------------------
# Step 11 — Settings: user language only (§9.6)
# ---------------------------------------------------------------------------


def test_every_sensitivity_level_has_a_user_facing_label() -> None:
    assert set(GP_SENSITIVITY_LABELS) == set(GpSensitivity)


def test_sensitivity_labels_never_say_kappa_or_gp_sensitivity() -> None:
    for label in GP_SENSITIVITY_LABELS.values():
        assert "κ" not in label
        assert "kappa" not in label.lower()
        assert "gp sensitivity" not in label.lower()


# ---------------------------------------------------------------------------
# Step 12 — §9.10's consequences: what a recommendation is *for*
# ---------------------------------------------------------------------------


def test_a_needed_for_row_says_how_much_of_the_gate_it_clears() -> None:
    """A bare "Desert Treasure I" is a goal with no sense of distance. The point of the row
    is that the reader can tell a one-step prerequisite from a ten-step one."""
    row = NeededForRow(name="Complete Desert Treasure I", remaining_before=3, remaining_after=2)

    assert row.label == "Complete Desert Treasure I (1 of 3 remaining)"


def test_a_gate_fully_cleared_reads_as_an_unblock_rather_than_as_zero() -> None:
    """ "0 of 3 remaining" reads as a broken template, and the whole point of the case is
    that the counting has stopped."""
    row = NeededForRow(name="Complete Desert Treasure I", remaining_before=3, remaining_after=0)

    assert row.label == "Complete Desert Treasure I (unblocks it)"
    assert "0 of" not in row.label


def test_a_needed_for_row_never_calls_the_count_the_requirements() -> None:
    """G3, in the one place a reader would be misled by the shorter word.

    The counts are over leaves the account is *known* to fail; a gate also holds leaves
    nobody has been asked about. Saying "1 of 3 requirements" would quietly promise that
    the three are all of them, when the corpus may name eleven.
    """
    label = NeededForRow(name="Q", remaining_before=3, remaining_after=2).label

    assert "requirement" not in label
    assert "remaining" in label


def test_a_needed_for_row_carries_the_goal_one_hop_further() -> None:
    """The sentence the user asked for, end to end: the chore, the task it unlocks, and the
    point of that task."""
    row = NeededForRow(
        name="Complete Desert Treasure I",
        remaining_before=3,
        remaining_after=2,
        goal_name="Ice Barrage NH",
        goal_on_roadmap=False,
    )

    assert row.label == (
        "Complete Desert Treasure I (1 of 3 remaining) → Ice Barrage NH (not on your roadmap)"
    )


def test_an_off_roadmap_goal_says_so_in_words_a_player_would_use() -> None:
    """The flag is about the player's *selection*, so it is phrased about their roadmap and
    not about the corpus — and it is words, because a colour cannot be read aloud."""
    row = GoalProgressRow(name="Anti-PK", remaining_before=4, remaining_after=2, on_roadmap=False)

    assert row.label == "Anti-PK (2 of 4 remaining) (not on your roadmap)"


def test_an_on_roadmap_goal_carries_no_flag_at_all() -> None:
    """Silence is the unmarked case. Flagging both would make the distinction invisible,
    which is the only thing the flag is for."""
    row = GoalProgressRow(
        name="Boss fundamentals", remaining_before=5, remaining_after=4, on_roadmap=True
    )

    assert row.label == "Boss fundamentals (1 of 5 remaining)"
    assert "roadmap" not in row.label


def test_a_speed_up_row_quotes_both_sizings_rather_than_a_saving() -> None:
    """ "97 hours saved" is a fact about the arithmetic; "113h → 16h" is a fact about the
    player's evening, and only one of them answers "should I do this first?"."""
    row = SpeedUpRow(name="Train Magic 87 → 94", hours_before=113.0, hours_after=16.0)

    assert row.label == "Train Magic 87 → 94: 113h → 16h"


def test_a_short_grind_keeps_the_decimal_a_long_one_drops() -> None:
    """Below ten hours the decimal separates two different evenings; above it, it would
    imply a precision §8's sizing does not have."""
    assert SpeedUpRow(name="X", hours_before=7.5, hours_after=2.25).label == "X: 7.5h → 2.2h"


def test_the_renderer_is_handed_labels_it_does_not_have_to_compose() -> None:
    """§15's split, applied to the newest rows. A sentence assembled inside a `ui.html(...)`
    call can only be checked by driving a browser, and a rule that expensive to check stops
    being checked — so every one of these types answers for its own words here."""
    rows = (
        UnblockRow(name="Ice Barrage NH"),
        NeededForRow(name="Q", remaining_before=2, remaining_after=1),
        GoalProgressRow(name="C", remaining_before=2, remaining_after=1),
        SpeedUpRow(name="G", hours_before=10.0, hours_after=1.0),
    )

    assert all(row.label for row in rows)
