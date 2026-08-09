"""What the UI reads out of the database, against the real schema and the real corpus.

These are the tests that catch the seam the pure tests cannot: a row shape that stores what
the view model expects but not what the engine writes, and — the one that matters most — a
capability or unlock with **no row at all**, which is the case §4.5 exists for and the one a
hand-built fixture tends to omit.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from tracker.content.loader import Content
from tracker.domain.types import Confidence, Status
from tracker.ui import read_model
from tracker.ui.states import UiState

STORED_CAPABILITIES = {"budget_nh", "ice_barrage_nh", "deep_wildy_nh", "vengeance_pvp"}
STORED_UNLOCKS = {"ancient_magicks", "rigour", "augury", "ca_grandmaster"}


def test_the_single_user_app_finds_its_one_player(session: Session, player_id: int) -> None:
    assert read_model.first_player_id(session) == player_id


def test_a_capability_with_no_stored_row_renders_as_unknown(
    session: Session, player_id: int, content: Content
) -> None:
    """The corpus declares five capabilities; the seed stores four.

    The fifth has no ``capability_state`` row, and the honest rendering of that is
    ``unknown`` — not omission. A view driven by the table rather than by content would drop
    it silently, which is the failure §15 complains about: states that disappear.
    """
    rows = read_model.capability_rows(session, player_id, content)
    assert len(rows) == len(content.capabilities)

    unstored = [row for row in rows if row.capability_id not in STORED_CAPABILITIES]
    assert unstored, "the corpus must declare a capability the seed leaves unstored"
    for row in unstored:
        assert row.status is Status.UNKNOWN
        assert row.state is UiState.UNKNOWN
        assert row.readiness is None


def test_the_three_layers_survive_the_round_trip(
    session: Session, player_id: int, content: Content
) -> None:
    """§4.4's middle case, read back out of storage rather than constructed in memory."""
    rows = {
        row.capability_id: row for row in read_model.capability_rows(session, player_id, content)
    }
    row = rows["ice_barrage_nh"]
    assert row.status is Status.UNLOCKED
    assert row.readiness is Confidence.LOW
    assert row.recommended_now is False
    assert row.recommended_label == "no — complete a refresher session first"
    assert row.warnings == ("last practised 5 weeks ago",)


def test_blockers_and_unknowns_are_rebuilt_as_separate_lists(
    session: Session, player_id: int, content: Content
) -> None:
    rows = {
        row.capability_id: row for row in read_model.capability_rows(session, player_id, content)
    }
    row = rows["vengeance_pvp"]
    assert [leaf.key for leaf in row.blockers] == ["magic"]
    assert [leaf.key for leaf in row.unknowns] == ["voidwaker"]


def test_an_unlock_the_corpus_requires_but_no_sync_reported_is_unknown(
    session: Session, player_id: int, content: Content
) -> None:
    """ "No row" is never "locked" (§4.5).

    The seed stores four unlocks. Every other key any capability requirement mentions has no
    row, and each must come back ``unknown`` — the state that asks for a sync — rather than
    being absent from the view or defaulted to locked.
    """
    referenced = set(read_model.referenced_unlock_keys(content))
    assert referenced, "the corpus must reference at least one unlock for this to mean anything"

    rows = {row.key: row for row in read_model.unlock_rows(session, player_id, content)}
    assert referenced <= set(rows)
    for key in referenced - STORED_UNLOCKS:
        assert rows[key].state is UiState.UNKNOWN


def test_all_four_unlock_states_come_back_distinct(
    session: Session, player_id: int, content: Content
) -> None:
    rows = {row.key: row.state for row in read_model.unlock_rows(session, player_id, content)}
    assert rows["ancient_magicks"] is UiState.UNLOCKED
    assert rows["rigour"] is UiState.AVAILABLE
    assert rows["augury"] is UiState.LOCKED
    assert rows["ca_grandmaster"] is UiState.UNKNOWN


def test_an_unranked_snapshot_reads_back_unranked(
    session: Session, player_id: int, content: Content
) -> None:
    """The stored row has ``level = 1`` and ``xp = NULL``. Only the second is meaningful."""
    rows = {row.skill_id: row for row in read_model.skill_rows(session, player_id, content)}
    assert rows["construction"].is_ranked is False
    assert rows["construction"].level is None
    assert rows["magic"].is_ranked is True
    assert rows["magic"].level == 94


def test_ranked_skills_sort_before_unranked_ones(
    session: Session, player_id: int, content: Content
) -> None:
    rows = read_model.skill_rows(session, player_id, content)
    ranked_flags = [row.is_ranked for row in rows]
    assert ranked_flags == sorted(ranked_flags, reverse=True)


def test_the_current_goal_is_the_top_entry_of_the_latest_snapshot(
    session: Session, player_id: int, content: Content
) -> None:
    """§15 names a current goal; §6 defines no model for one. It is derived, not stored."""
    goal = read_model.current_goal(session, player_id, content)
    assert goal is not None
    assert goal.candidate_id == "train_magic_87_to_94"
    assert goal.confidence is Confidence.MEDIUM


def test_the_why_line_is_the_persisted_reason_verbatim(
    session: Session, player_id: int, content: Content
) -> None:
    """Step 6 generated it from log contributions (§9.5). The UI must not recompose it."""
    goal = read_model.current_goal(session, player_id, content)
    assert goal is not None
    assert goal.reason == "high PvP value (+0.61) - unblocks 2 capabilities (+0.44)"


def test_a_never_scanned_container_still_produces_a_note(
    session: Session, player_id: int, now: datetime
) -> None:
    """The seed scans the bank and never scans equipment. Both must be reported."""
    notes = read_model.staleness_notes(session, player_id, now)
    assert "Last saw your bank 3 weeks ago." in notes
    assert any("never seen your equipment" in note for note in notes)


def test_unknown_capabilities_do_not_count_as_roadmap_progress(
    session: Session, player_id: int, content: Content
) -> None:
    """§4.4 keeps unknown off the locked-to-unlocked scale.

    A bar that crept upward as evidence went missing would be the backward progress the
    three-layer split exists to prevent.
    """
    rows = read_model.capability_rows(session, player_id, content)
    progress = read_model.roadmap_progress(session, player_id, content, rows)
    unlocked_ids = {row.capability_id for row in rows if row.status is Status.UNLOCKED}
    for roadmap in progress:
        capability_ids = set(content.roadmaps[roadmap.roadmap_id].capabilities)
        assert roadmap.unlocked == len(capability_ids & unlocked_ids)


def test_roadmaps_are_ordered_primary_first(
    session: Session, player_id: int, content: Content
) -> None:
    """§4.3's defaults are 1.00 primary and 0.25 secondary."""
    rows = read_model.capability_rows(session, player_id, content)
    progress = read_model.roadmap_progress(session, player_id, content, rows)
    assert [row.roadmap_id for row in progress] == ["main_nh", "anti_pk"]


def test_the_dashboard_reports_unknowns_as_their_own_figure(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    """Not folded into a single readiness percentage.

    See :mod:`tracker.ui.dashboard`: any single figure has to either count unknowns as
    locked or drop them from the denominator, and both misreport.
    """
    view = read_model.dashboard_view(session, player_id, content, now)
    assert view.display_name == "Zezima"
    assert view.unlocked_capabilities == 2
    assert view.unknown_capabilities >= 1
    assert view.total_capabilities == len(content.capabilities)
    assert view.current_goal is not None
