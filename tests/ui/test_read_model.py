"""What the UI reads out of the database, against the real schema and the real corpus.

These are the tests that catch the seam the pure tests cannot: a row shape that stores what
the view model expects but not what the engine writes, and — the one that matters most — a
capability or unlock with **no row at all**, which is the case §4.5 exists for and the one a
hand-built fixture tends to omit.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.content.schema import (
    KappaPresets,
    RefresherPolicy,
    RefresherTemplate,
    RefresherTrigger,
    ScoringProfile,
    ScoringWeights,
)
from tracker.content.schema import Milestone as ContentMilestone
from tracker.db.models import Base, Player, SkillSnapshot
from tracker.db.models import Milestone as MilestoneRow
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import (
    Confidence,
    GpSensitivity,
    MilestoneClass,
    MilestoneKind,
    Source,
    Status,
)
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


def test_legacy_runecrafting_uses_canonical_current_skill_row(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    session.add(
        SkillSnapshot(
            player_id=player_id,
            skill="runecrafting",
            level=20,
            xp=4470,
            source=Source.WISE_OLD_MAN,
            observed_at=now,
        )
    )
    session.flush()

    rows = {row.skill_id: row for row in read_model.skill_rows(session, player_id, content)}
    assert "runecrafting" not in rows
    assert rows["runecraft"].level == 20


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


# ---------------------------------------------------------------------------
# Step 11 — Recommendations (§9.10, §16.2)
# ---------------------------------------------------------------------------


def test_the_primary_list_excludes_blocked_entries(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    rows = read_model.recommendation_rows(session, player_id, content, now)
    assert "buy_high_risk_gear" not in {row.candidate_id for row in rows}


def test_the_persisted_refresher_is_flagged_and_carries_its_stale_members(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    rows = {
        row.candidate_id: row
        for row in read_model.recommendation_rows(session, player_id, content, now)
    }
    refresher = rows["refresh_nh_fundamentals"]
    assert refresher.is_refresher is True
    assert refresher.practice_members  # the group's stale members, recomputed live (§9.8)


def test_the_why_line_on_a_progression_entry_is_the_persisted_reason(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    rows = {
        row.candidate_id: row
        for row in read_model.recommendation_rows(session, player_id, content, now)
    }
    assert (
        rows["train_magic_87_to_94"].reason
        == "high PvP value (+0.61) - unblocks 2 capabilities (+0.44)"
    )


def test_at_most_one_refresher_reaches_the_primary_list(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    """G10, read back from storage rather than asserted in the abstract."""
    rows = read_model.recommendation_rows(session, player_id, content, now)
    assert sum(1 for row in rows if row.is_refresher) == 1


def test_blocked_entries_are_surfaced_separately(
    session: Session, player_id: int, content: Content
) -> None:
    blocked = read_model.blocked_recommendation_rows(session, player_id, content)
    assert [row.candidate_id for row in blocked] == ["buy_high_risk_gear"]


# ---------------------------------------------------------------------------
# Step 11 — Practice freshness (§9.8): the seeded account's two real practice groups
# ---------------------------------------------------------------------------


def test_stale_practice_groups_finds_every_triggered_group(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    groups = read_model.stale_practice_groups(session, player_id, content, now)
    assert {group.template_id for group in groups} == {
        "refresh_nh_fundamentals",
        "refresh_vengeance_fundamentals",
    }


def test_practice_freshness_excludes_the_primary_lists_refresher(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    """§9.8: "the rest" appear here — the one already shown in the primary list does not."""
    assert read_model.primary_refresher_id(session, player_id) == "refresh_nh_fundamentals"
    rows = read_model.practice_freshness_rows(session, player_id, content, now)
    assert {row.template_id for row in rows} == {"refresh_vengeance_fundamentals"}


def test_refresh_milestones_moves_only_the_requested_keys(
    session_factory: sessionmaker[Session], player_id: int, now: datetime
) -> None:
    """ "Mark session complete" refreshes exactly what is listed, and nothing else."""
    before = now - timedelta(days=60)

    with session_factory() as write_session:
        untouched = write_session.get(MilestoneRow, (player_id, "vengeance_timing"))
        assert untouched is not None and untouched.last_practiced_at == before

        refreshed = read_model.refresh_milestones(
            write_session, player_id, ["comfortable_4_way_switches"], now=now
        )
        assert refreshed == 1

    with session_factory() as check_session:
        moved = check_session.get(MilestoneRow, (player_id, "comfortable_4_way_switches"))
        assert moved is not None
        assert moved.last_practiced_at == now
        assert moved.source is Source.MANUAL

        unmoved = check_session.get(MilestoneRow, (player_id, "vengeance_timing"))
        assert unmoved is not None
        assert unmoved.last_practiced_at == before


def test_refresh_milestones_never_moves_last_practiced_at_backwards(
    session_factory: sessionmaker[Session], player_id: int, now: datetime
) -> None:
    with session_factory() as write_session:
        refreshed = read_model.refresh_milestones(
            write_session,
            player_id,
            ["vengeance_timing"],
            now=now - timedelta(days=90),
        )
    assert refreshed == 0

    with session_factory() as check_session:
        row = check_session.get(MilestoneRow, (player_id, "vengeance_timing"))
        assert row is not None
        assert row.last_practiced_at == now - timedelta(days=60)


# ---------------------------------------------------------------------------
# A7 — attestation, the half refresh_milestones deliberately leaves undone (§6.6)
# ---------------------------------------------------------------------------


def test_attesting_creates_the_row_a_refresh_would_have_skipped(
    session_factory: sessionmaker[Session], player_id: int, content: Content, now: datetime
) -> None:
    """The seeded account has never been prompted about this one, so no row exists yet.

    ``refresh_milestones`` skips it by design and names this function as the fix; the
    assertion that matters is that a row now exists at all.
    """
    with session_factory() as check_session:
        assert check_session.get(MilestoneRow, (player_id, "teleblock_understanding")) is None

    with session_factory() as write_session:
        assert read_model.attest_milestone(
            write_session,
            player_id,
            "teleblock_understanding",
            achieved=True,
            content=content,
            now=now,
        )

    with session_factory() as check_session:
        row = check_session.get(MilestoneRow, (player_id, "teleblock_understanding"))
        assert row is not None
        assert row.achieved
        assert row.attested_at == now
        assert row.source is Source.MANUAL


def test_declining_is_a_write_not_a_no_op(
    session_factory: sessionmaker[Session], player_id: int, content: Content, now: datetime
) -> None:
    """A7's whole point: "asked and said no" must be storable, and is not "never asked".

    Both are ``achieved=False``. Only ``attested_at`` separates them, and only the stored
    one resolves the leaf to ``unsatisfied`` rather than leaving it ``unknown`` (§4.5).
    """
    with session_factory() as write_session:
        assert read_model.attest_milestone(
            write_session,
            player_id,
            "successfully_freeze_log",
            achieved=False,
            content=content,
            now=now,
        )

    with session_factory() as check_session:
        row = check_session.get(MilestoneRow, (player_id, "successfully_freeze_log"))
        assert row is not None
        assert not row.achieved
        assert row.attested_at == now, (
            "a declined answer without a timestamp is indistinguishable from never "
            "having been asked"
        )


def test_attesting_does_not_count_as_having_practised(
    session_factory: sessionmaker[Session], player_id: int, content: Content, now: datetime
) -> None:
    """§6.6 keeps competence and recency in separate columns; this write touches one."""
    before = now - timedelta(days=60)

    with session_factory() as write_session:
        assert read_model.attest_milestone(
            write_session,
            player_id,
            "vengeance_timing",
            achieved=True,
            content=content,
            now=now,
        )

    with session_factory() as check_session:
        row = check_session.get(MilestoneRow, (player_id, "vengeance_timing"))
        assert row is not None
        assert row.achieved
        assert row.last_practiced_at == before, "answering a question is not a practice session"


def test_a_derived_milestone_cannot_be_attested(
    session_factory: sessionmaker[Session], player_id: int, content: Content, now: datetime
) -> None:
    """``first_anti_pk`` is measured from counters (§6.6), so an opinion must not overwrite it."""
    with session_factory() as write_session:
        assert not read_model.attest_milestone(
            write_session, player_id, "first_anti_pk", achieved=True, content=content, now=now
        )

    with session_factory() as check_session:
        assert check_session.get(MilestoneRow, (player_id, "first_anti_pk")) is None


def test_an_unauthored_key_is_refused(
    session_factory: sessionmaker[Session], player_id: int, content: Content, now: datetime
) -> None:
    with session_factory() as write_session:
        assert not read_model.attest_milestone(
            write_session, player_id, "not_a_milestone", achieved=True, content=content, now=now
        )


# ---------------------------------------------------------------------------
# Step 11 — G10 against a synthetic three-group scenario
#
# The real corpus only declares two practice groups; this builds a third so the "three
# stale groups still yield exactly one refresher in the primary list, with the rest in the
# Practice freshness view" exit criterion is checked against an actual count of three.
# ---------------------------------------------------------------------------


def _synthetic_profile() -> ScoringProfile:
    return ScoringProfile(
        version=1,
        tau_hours=10.0,
        kappa_gp=KappaPresets(high=8_000_000, normal=20_000_000, low=50_000_000),
        weights=ScoringWeights(
            pvp_value=1.0,
            leverage=0.8,
            proximity=0.6,
            effort_decay=0.7,
            cost_decay=0.5,
            method_unlock=0.0,
        ),
        refresher=RefresherPolicy(),
    )


def _synthetic_content() -> Content:
    """Three practice groups, one milestone each, no capabilities or candidates needed."""
    milestones = {
        f"m{i}": ContentMilestone(
            id=f"m{i}",
            name=f"Milestone {i}",
            class_=MilestoneClass.EXECUTION,
            kind=MilestoneKind.SELF_ATTESTED,
            practice_group=f"group{i}",
        )
        for i in range(1, 4)
    }
    refreshers = {
        f"refresh_group{i}": RefresherTemplate(
            id=f"refresh_group{i}",
            name=f"Refresh group {i}",
            practice_group=f"group{i}",
            trigger=RefresherTrigger(),
            suggested_session=f"session {i}",
            suggested_session_hours=0.5,
            advances=(),
        )
        for i in range(1, 4)
    }
    return Content(profile=_synthetic_profile(), milestones=milestones, refreshers=refreshers)


@pytest.fixture
def synthetic_session() -> Session:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as session:
        yield session
    engine.dispose()


def test_three_stale_groups_yield_exactly_one_primary_refresher_and_two_deferred(
    synthetic_session: Session, now: datetime
) -> None:
    session = synthetic_session
    content = _synthetic_content()

    player = Player(
        username="three_groups",
        display_name="Three Groups",
        created_at=now - timedelta(days=400),
        gp_sensitivity=GpSensitivity.NORMAL,
    )
    session.add(player)
    session.flush()
    player_id = int(player.id)

    stale_since = now - timedelta(days=60)
    for i in range(1, 4):
        session.add(
            MilestoneRow(
                player_id=player_id,
                key=f"m{i}",
                kind=MilestoneKind.SELF_ATTESTED,
                class_=MilestoneClass.EXECUTION,
                achieved=True,
                last_practiced_at=stale_since,
                source=Source.RUNELITE,
                observed_at=stale_since,
            )
        )
    session.commit()

    groups = read_model.stale_practice_groups(session, player_id, content, now)
    assert len(groups) == 3, "all three groups must have triggered"

    # Persist a snapshot naming one of the three as the primary list's one refresher
    # (G10) — exactly what Step 6's ``enforce_list_policy`` would have written.
    from tracker.db.enums import RecommendationCandidateKind
    from tracker.db.models import RecommendationEntry, RecommendationSnapshot

    snapshot = RecommendationSnapshot(
        player_id=player_id,
        run_at=now,
        roadmap_selection={},
        scoring_profile_version=1,
    )
    session.add(snapshot)
    session.flush()
    session.add(
        RecommendationEntry(
            snapshot_id=snapshot.id,
            candidate_id="refresh_group2",
            rank=1,
            candidate_kind=RecommendationCandidateKind.REFRESHER,
            score=0.5,
            factors={},
            reason="",
            estimate_confidence=Confidence.HIGH,
            blocked=False,
        )
    )
    session.commit()

    assert read_model.primary_refresher_id(session, player_id) == "refresh_group2"

    primary_list = read_model.recommendation_rows(session, player_id, content, now)
    assert sum(1 for row in primary_list if row.is_refresher) == 1

    deferred = read_model.practice_freshness_rows(session, player_id, content, now)
    assert {row.template_id for row in deferred} == {"refresh_group1", "refresh_group3"}


# ---------------------------------------------------------------------------
# Step 11 — Roadmaps (§4.3, §6.12)
# ---------------------------------------------------------------------------


def test_roadmap_options_cover_every_authored_roadmap(
    session: Session, player_id: int, content: Content
) -> None:
    options = read_model.roadmap_options(session, player_id, content)
    assert {option.roadmap_id for option in options} == set(content.roadmaps)


def test_select_primary_roadmap_writes_the_default_weight(
    session_factory: sessionmaker[Session], player_id: int
) -> None:
    with session_factory() as write_session:
        read_model.select_primary_roadmap(write_session, player_id, "anti_pk")

    with session_factory() as check_session:
        options = {
            option.roadmap_id: option
            for option in read_model.roadmap_options(check_session, player_id, _content_stub())
        }
        assert options["anti_pk"].selection_weight == pytest.approx(1.0)
        # main_nh held the primary weight before this call and must be demoted, not dropped.
        assert options["main_nh"].selected is True
        assert options["main_nh"].selection_weight == pytest.approx(0.25)

    # Restore the fixture's original selection so later tests in this module are unaffected
    # by test ordering (the player fixture is session-scoped).
    with session_factory() as restore_session:
        read_model.select_primary_roadmap(restore_session, player_id, "main_nh")
        read_model.set_secondary_roadmap(restore_session, player_id, "anti_pk", enabled=True)


def _content_stub() -> Content:
    """A minimal ``Content`` naming only the two roadmaps the seed account selects from."""
    from tracker.content.schema import Roadmap

    return Content(
        profile=_synthetic_profile(),
        roadmaps={
            "main_nh": Roadmap(id="main_nh", name="Main NH", capabilities={"budget_nh": 1.0}),
            "anti_pk": Roadmap(id="anti_pk", name="Anti-PKer", capabilities={"budget_nh": 1.0}),
        },
    )


def test_set_secondary_roadmap_toggles_selection(
    session_factory: sessionmaker[Session], player_id: int
) -> None:
    with session_factory() as write_session:
        read_model.set_secondary_roadmap(write_session, player_id, "anti_pk", enabled=False)

    with session_factory() as check_session:
        options = {
            option.roadmap_id: option
            for option in read_model.roadmap_options(check_session, player_id, _content_stub())
        }
        assert options["anti_pk"].selected is False

    with session_factory() as restore_session:
        read_model.set_secondary_roadmap(restore_session, player_id, "anti_pk", enabled=True)


# ---------------------------------------------------------------------------
# Step 11 — Settings (§9.6, §11.2, §15)
# ---------------------------------------------------------------------------


def test_settings_view_reads_the_players_live_sensitivity(session: Session, player_id: int) -> None:
    settings = Settings(bind_address="127.0.0.1", api_token="a-real-token-value")
    view = read_model.settings_view(session, player_id, settings)
    assert view.gp_sensitivity is GpSensitivity.NORMAL
    assert view.api_token_present is True
    assert view.bind_address == "127.0.0.1"


def test_set_gp_sensitivity_writes_the_players_row(
    session_factory: sessionmaker[Session], player_id: int
) -> None:
    with session_factory() as write_session:
        read_model.set_gp_sensitivity(write_session, player_id, GpSensitivity.LOW)
    with session_factory() as check_session:
        settings = Settings(bind_address="127.0.0.1", api_token="a-real-token-value")
        view = read_model.settings_view(check_session, player_id, settings)
        assert view.gp_sensitivity is GpSensitivity.LOW
        assert view.sensitivity_label == "Barely"

    with session_factory() as restore_session:
        read_model.set_gp_sensitivity(restore_session, player_id, GpSensitivity.NORMAL)


# ---------------------------------------------------------------------------
# Step 11 — History (§6.10)
# ---------------------------------------------------------------------------


def test_history_snapshots_carry_their_own_scoring_profile_version(
    session: Session, player_id: int, content: Content
) -> None:
    rows = read_model.history_snapshots(session, player_id, content)
    assert rows
    assert rows[0].scoring_profile_version == 1
    assert rows[0].top_candidate_id == "train_magic_87_to_94"


def test_xp_series_excludes_unranked_snapshots(session: Session, player_id: int) -> None:
    series = read_model.xp_series(session, player_id)
    assert "magic" in series
    assert "construction" not in series, "xp is NULL for this one (§6.2) - no chart point"
    assert series["magic"][-1].xp == 7_195_629


def test_xp_series_combines_legacy_runecrafting_history(
    session: Session, player_id: int, now: datetime
) -> None:
    session.add_all(
        [
            SkillSnapshot(
                player_id=player_id,
                skill="runecrafting",
                level=20,
                xp=4470,
                source=Source.WISE_OLD_MAN,
                observed_at=now - timedelta(days=1),
            ),
            SkillSnapshot(
                player_id=player_id,
                skill="runecraft",
                level=21,
                xp=5018,
                source=Source.RUNELITE,
                observed_at=now,
            ),
        ]
    )
    session.flush()

    series = read_model.xp_series(session, player_id)
    assert "runecrafting" not in series
    assert [point.xp for point in series["runecraft"]] == [4470, 5018]


def test_snapshot_diff_reports_the_same_snapshot_as_unchanged(
    session: Session, player_id: int
) -> None:
    rows = read_model.history_snapshots(session, player_id, Content(profile=_synthetic_profile()))
    snapshot_id = rows[0].snapshot_id
    diff = read_model.snapshot_diff(session, player_id, snapshot_id, snapshot_id)
    assert diff
    assert all(row.delta == 0.0 or row.delta is None for row in diff)


def test_consequences_are_read_from_the_snapshot_rather_than_recomputed(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    """§6.10's whole point, applied to the newest column.

    A consequence is a fact about the account *when the run happened*: "unblocks Desert
    Treasure I" stops being true the moment the quest is finished. Re-deriving it on read
    would relabel a historical entry with today's facts, which is what a snapshot exists to
    prevent — the same argument that already makes ``reason`` a stored string and ``bands`` a
    stored breakdown.

    The blob below names a capability the corpus does not declare, so nothing here could
    have been re-derived: if the row renders it, the row came from storage.
    """
    from tracker.db.enums import RecommendationCandidateKind
    from tracker.db.models import RecommendationEntry, RecommendationSnapshot

    snapshot = RecommendationSnapshot(
        player_id=player_id, run_at=now, roadmap_selection={}, scoring_profile_version=1
    )
    session.add(snapshot)
    session.flush()
    session.add(
        RecommendationEntry(
            snapshot_id=snapshot.id,
            candidate_id="train_magic_87_to_94",
            rank=1,
            candidate_kind=RecommendationCandidateKind.PROGRESSION,
            score=1.0,
            factors={},
            reason="",
            estimate_confidence=Confidence.HIGH,
            consequences={
                "unblocks_capabilities": [
                    {"capability_id": "retired_capability", "name": "A Capability Since Retired"}
                ],
                "gate_progress": [],
                "goal_progress": [],
                "speeds_up": [],
                "goal_links": [],
            },
            blocked=False,
        )
    )
    session.commit()

    row = read_model.recommendation_rows(session, player_id, content, now)[0]

    assert [entry.label for entry in row.unblocks] == ["A Capability Since Retired"]


def test_a_consequence_whose_capability_left_the_corpus_renders_the_stored_name(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    """``_band_rows``' degradation rule, applied to a second join.

    Content changes between runs. Renaming or dropping a capability must not turn a History
    page into a stack trace, and the name the run recorded is still the most truthful thing
    available about what that row described.
    """
    from tracker.db.enums import RecommendationCandidateKind
    from tracker.db.models import RecommendationEntry, RecommendationSnapshot

    snapshot = RecommendationSnapshot(
        player_id=player_id, run_at=now, roadmap_selection={}, scoring_profile_version=1
    )
    session.add(snapshot)
    session.flush()
    session.add(
        RecommendationEntry(
            snapshot_id=snapshot.id,
            candidate_id="train_magic_87_to_94",
            rank=1,
            candidate_kind=RecommendationCandidateKind.PROGRESSION,
            score=1.0,
            factors={},
            reason="",
            estimate_confidence=Confidence.HIGH,
            consequences={
                "gate_progress": [
                    {
                        "candidate_id": "a_candidate_since_deleted",
                        "name": "A Candidate Since Deleted",
                        "remaining_before": 2,
                        "remaining_after": 1,
                        "satisfied": [],
                    }
                ]
            },
            blocked=False,
        )
    )
    session.commit()

    row = read_model.recommendation_rows(session, player_id, content, now)[0]

    assert row.needed_for[0].label == "A Candidate Since Deleted (1 of 2 remaining)"


def test_an_entry_written_before_the_column_existed_reports_no_consequences(
    session: Session, player_id: int, content: Content, now: datetime
) -> None:
    """The migration's ``server_default="{}"`` means *nothing was recorded*, and the read
    path must render that as silence rather than raising or inventing a row."""
    from tracker.db.enums import RecommendationCandidateKind
    from tracker.db.models import RecommendationEntry, RecommendationSnapshot

    snapshot = RecommendationSnapshot(
        player_id=player_id, run_at=now, roadmap_selection={}, scoring_profile_version=1
    )
    session.add(snapshot)
    session.flush()
    session.add(
        RecommendationEntry(
            snapshot_id=snapshot.id,
            candidate_id="train_magic_87_to_94",
            rank=1,
            candidate_kind=RecommendationCandidateKind.PROGRESSION,
            score=1.0,
            factors={},
            reason="",
            estimate_confidence=Confidence.HIGH,
            consequences={},
            blocked=False,
        )
    )
    session.commit()

    row = read_model.recommendation_rows(session, player_id, content, now)[0]

    assert (row.unblocks, row.needed_for, row.works_toward, row.speeds_up) == ((), (), (), ())
