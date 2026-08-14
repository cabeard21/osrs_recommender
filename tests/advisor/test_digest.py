"""§22.2's digest: completeness, three-valued honesty, and determinism.

The three-valued tests are the ones worth reading first. Everything else here can fail loudly;
those fail *quietly*, by producing a fluent, confident sentence about an account fact nobody
ever observed.
"""

from __future__ import annotations

from datetime import timedelta

from tests.advisor.conftest import (
    NOW,
    make_capability_view,
    make_content,
    make_snapshot,
    make_state,
    make_task,
    scanned,
    skill_at,
)
from tracker.advisor.digest import MAX_RANKED, build_digest, render_digest
from tracker.advisor.snapshot import ObservationAge
from tracker.domain.types import (
    Acceleration,
    AccountType,
    Consequences,
    GateProgress,
    LeafRef,
    QuestStatus,
    RoadmapSelection,
    Status,
    UnblockedCapability,
    UnlockState,
)


def _render(**overrides: object) -> str:
    return render_digest(build_digest(make_snapshot(**overrides)))


class TestTheConsequenceLine:
    """§9.10 reaching §22.2 at all.

    These are regression tests before they are feature tests: ``RankedTask.consequences`` was
    declared, defaulted and never populated, so the advisor could say what the engine scored but
    never what completing the thing would *do*.
    """

    def test_an_unblocked_capability_is_named(self) -> None:
        capability = UnblockedCapability(capability_id="ice_barrage_nh", name="Ice Barrage NH")
        rendered = _render(
            ranked=(
                make_task(
                    consequences=Consequences(unblocks_capabilities=(capability,)),
                ),
            )
        )
        assert "What it would do: unlocks Ice Barrage NH" in rendered

    def test_only_a_gate_it_would_finish_is_named(self) -> None:
        """A gate dented is not a gate cleared, and only one of them earns a line here."""
        rendered = _render(
            ranked=(
                make_task(
                    consequences=Consequences(
                        gate_progress=(
                            GateProgress(
                                candidate_id="dt1",
                                name="Desert Treasure I",
                                remaining_before=1,
                                remaining_after=0,
                            ),
                            GateProgress(
                                candidate_id="mm2",
                                name="Monkey Madness II",
                                remaining_before=4,
                                remaining_after=3,
                            ),
                        )
                    ),
                ),
            )
        )
        assert "clears the last requirement of Desert Treasure I" in rendered
        assert "Monkey Madness II" not in rendered

    def test_an_entry_with_nothing_to_say_gets_no_line(self) -> None:
        """§9.5: an entry that ranked on cheapness alone is not owed a justification."""
        assert "What it would do" not in _render(ranked=(make_task(),))

    def test_the_digest_does_not_move_when_an_acceleration_is_repriced(self) -> None:
        """``speeds_up`` renders as a count for exactly this reason.

        Prices move without the player doing anything. If the hours behind an acceleration
        reached the digest, every reprice would retire the cached prefix of every open
        conversation — a bill for a change the account never made.
        """

        def rendered(hours_after: float) -> str:
            acceleration = Acceleration(
                candidate_id="train_slayer",
                name="Train Slayer",
                hours_before=40.0,
                hours_after=hours_after,
            )
            return _render(
                ranked=(make_task(consequences=Consequences(speeds_up=(acceleration,))),)
            )

        assert rendered(22.0) == rendered(19.5)
        assert "shortens 1 other task" in rendered(22.0)


class TestThreeValuedFacts:
    """§4.5 and D8 at the prompt boundary. Each of these is a specific wrong answer avoided."""

    def test_an_unobserved_account_type_is_unknown_and_not_main(self) -> None:
        """A model that assumes *main* tells an ironman to buy things."""
        rendered = _render(state=make_state(account_type=None))
        assert "Account type: unknown" in rendered
        assert "do not assume main" in rendered

    def test_an_observed_account_type_is_stated_plainly(self) -> None:
        rendered = _render(state=make_state(account_type=AccountType.IRONMAN))
        assert f"Account type: {AccountType.IRONMAN.value}" in rendered
        assert "do not assume main" not in rendered

    def test_unobserved_members_is_unknown_and_not_free_to_play(self) -> None:
        rendered = _render(state=make_state(members=None))
        assert "Members: unknown" in rendered
        assert "not the same as free-to-play" in rendered

    def test_members_false_is_rendered_as_no(self) -> None:
        assert "Members: no" in _render(state=make_state(members=False))

    def test_unobserved_coins_are_not_zero(self) -> None:
        """*Nobody looked* and *they have none* lead to different advice (§6.5, G3)."""
        rendered = _render(state=make_state())
        assert "Coins on hand: unknown" in rendered
        assert "do not assume they have coins or that they have none" in rendered

    def test_a_scan_that_found_no_coins_is_stated_as_zero(self) -> None:
        """Someone looked and there were none — a fact, and not the same as the line above."""
        assert "Coins on hand: 0 gp (observed)" in _render(state=make_state(**scanned()))

    def test_observed_coins_render_with_their_quantity(self) -> None:
        assert "Coins on hand: 5,000,000 gp (observed)" in _render(
            state=make_state(**scanned(5_000_000))
        )

    def test_an_unobserved_skill_is_never_observed_and_not_level_one(self) -> None:
        rendered = _render(state=make_state(skills={}))
        assert "- Magic: never observed" in rendered
        assert "level 1" not in rendered

    def test_an_unranked_skill_says_so_rather_than_reading_as_ranked(self) -> None:
        """G5 — unranked is not zero, and the two lead to different first steps."""
        rendered = _render(state=make_state(skills={"magic": skill_at(70, xp=None)}))
        assert "- Magic: level 70 (unranked — no XP recorded)" in rendered

    def test_an_unobserved_unlock_renders_unknown(self) -> None:
        assert "ancient_magicks: unknown" in _render(state=make_state(unlocks={}))

    def test_available_unlocks_carry_the_gloss_that_they_are_not_held(self) -> None:
        rendered = _render(state=make_state(unlocks={"ancient_magicks": UnlockState.AVAILABLE}))
        assert "ancient_magicks: available" in rendered
        assert "obtainable but **not** held" in rendered


class TestCompleteness:
    def test_every_declared_skill_appears_even_when_unobserved(self) -> None:
        rendered = _render(state=make_state(skills={"magic": skill_at(94)}))
        for name in ("Magic", "Slayer", "Agility"):
            assert f"- {name}:" in rendered

    def test_every_capability_appears(self) -> None:
        rendered = _render(capabilities=(make_capability_view(),))
        assert "## Ice Barrage NH" in rendered
        assert "Requirements met: 50%" in rendered

    def test_a_capability_with_no_readiness_reads_unknown_rather_than_low(self) -> None:
        rendered = _render(capabilities=(make_capability_view(readiness_confidence=None),))
        assert "Readiness confidence: unknown" in rendered

    def test_capability_blockers_are_capped_with_a_count(self) -> None:
        blockers = tuple(
            LeafRef(leaf_type="skill", key=f"s{index}", description=f"needs skill {index}")
            for index in range(5)
        )
        rendered = _render(capabilities=(make_capability_view(blockers=blockers),))
        assert "needs skill 0" in rendered
        assert "and 2 more" in rendered

    def test_the_engines_reason_is_carried_verbatim(self) -> None:
        """§9.5 computes that sentence; a paraphrase here would be a second, worse one."""
        rendered = _render(ranked=(make_task(reason="cuts Train Magic from 113h to 16h"),))
        assert "cuts Train Magic from 113h to 16h" in rendered

    def test_the_observation_age_bucket_is_stated(self) -> None:
        rendered = _render(state=make_state(last_sync_at=NOW - timedelta(days=45)))
        assert f"Account last observed: {ObservationAge.OLDER.value}" in rendered

    def test_a_never_synced_account_says_so(self) -> None:
        rendered = _render(state=make_state(last_sync_at=None))
        assert f"Account last observed: {ObservationAge.NEVER.value}" in rendered

    def test_roadmap_weights_render_with_capability_names(self) -> None:
        rendered = _render(roadmaps=RoadmapSelection(weights={"ice_barrage_nh": 0.75}))
        assert "- Ice Barrage NH: 75%" in rendered

    def test_an_account_with_no_run_says_so_rather_than_omitting_the_section(self) -> None:
        """Silence would read as *no tasks*, which is a different claim from *no run yet*."""
        assert "There is no recommendation run for this account yet" in _render(ranked=())


class TestTruncationIsAnnounced:
    """A truncated list that does not say so reads as a complete one."""

    def test_the_ranked_list_is_capped_and_names_the_tool_that_reaches_the_rest(self) -> None:
        tasks = tuple(
            make_task(candidate_id=f"c{index}", name=f"Task {index}", rank=index)
            for index in range(1, MAX_RANKED + 6)
        )
        rendered = _render(ranked=tasks)
        assert "Task 1" in rendered
        assert f"Task {MAX_RANKED + 5}" not in rendered
        assert "5 further ranked entries are not listed" in rendered
        assert "search_candidates" in rendered

    def test_a_short_ranked_list_does_not_claim_omissions(self) -> None:
        assert "further ranked entries" not in _render(ranked=(make_task(),))

    def test_the_capability_section_names_its_drill_down_tool(self) -> None:
        assert "get_capability_detail" in _render(capabilities=(make_capability_view(),))

    def test_the_quest_section_names_its_drill_down_tool(self) -> None:
        assert "get_quest_status" in _render()


class TestQuests:
    def test_counts_cover_the_whole_corpus(self) -> None:
        rendered = _render(state=make_state(quests={"desert_treasure_i": QuestStatus.COMPLETE}))
        assert f"- {QuestStatus.COMPLETE.value}: 1" in rendered
        assert "- never observed: 1" in rendered

    def test_gated_incomplete_quests_are_named(self) -> None:
        """Named because a capability tree asks for it, not because it exists."""
        rendered = _render(state=make_state(quests={}))
        assert "Incomplete quests that something is waiting on" in rendered
        assert "- Desert Treasure I: unknown" in rendered

    def test_a_completed_gated_quest_is_not_named_as_outstanding(self) -> None:
        rendered = _render(state=make_state(quests={"desert_treasure_i": QuestStatus.COMPLETE}))
        assert "Incomplete quests that something is waiting on" not in rendered


class TestDeterminism:
    """§22.3 hashes this. A render that varies costs a cache miss the account never earned."""

    def test_building_twice_is_byte_identical(self) -> None:
        snapshot = make_snapshot(
            state=make_state(
                skills={"magic": skill_at(94), "slayer": skill_at(55)},
                quests={"desert_treasure_i": QuestStatus.IN_PROGRESS},
                unlocks={"ancient_magicks": UnlockState.AVAILABLE},
            ),
            capabilities=(make_capability_view(),),
            ranked=(make_task(),),
        )
        assert render_digest(build_digest(snapshot)) == render_digest(build_digest(snapshot))

    def test_corpus_insertion_order_does_not_change_the_render(self) -> None:
        forwards = make_content()
        backwards = make_content(
            skills=dict(reversed(list(make_content().skills.items()))),
            quests=dict(reversed(list(make_content().quests.items()))),
        )
        assert _render(content=forwards) == _render(content=backwards)


class TestEmptySectionsAreDropped:
    def test_no_capabilities_means_no_capability_heading(self) -> None:
        """An empty heading reads as *there are none* when the truth is *this does not apply*."""
        assert "# Capabilities" not in _render(capabilities=())

    def test_no_stale_practice_means_no_practice_heading(self) -> None:
        assert "# Practice freshness" not in _render(stale_practice=())

    def test_stale_practice_renders_when_present(self) -> None:
        rendered = _render(stale_practice=(("Barrage accuracy", "stale"),))
        assert "- Barrage accuracy: stale" in rendered
        assert "never revokes a capability" in rendered

    def test_no_roadmap_means_no_roadmap_heading(self) -> None:
        assert "# Active roadmap weighting" not in _render(roadmaps=RoadmapSelection())


class TestBlocked:
    def test_blocked_entries_render_with_their_blockers(self) -> None:
        blocked = make_task(
            candidate_id="quest_desert_treasure_i",
            name="Desert Treasure I",
            kind="quest",
            blocked=True,
            blockers=(LeafRef(leaf_type="skill", key="magic", description="Magic 50", target=50),),
        )
        rendered = _render(blocked=(blocked,))
        assert "## Desert Treasure I (quest)" in rendered
        assert "Not yet met: Magic 50" in rendered

    def test_the_status_word_comes_from_the_domain_enum(self) -> None:
        rendered = _render(capabilities=(make_capability_view(status=Status.UNKNOWN),))
        assert f"Status: {Status.UNKNOWN.value}" in rendered
