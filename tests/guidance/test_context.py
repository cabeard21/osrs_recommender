"""§21.2 — the slice is a slice, three-valued facts survive it, and it is deterministic.

Three properties, and each has a distinct failure mode worth naming:

* **Relevance.** A context that quietly grows to the whole account still produces good advice;
  it just costs several times as much and buries the two facts that mattered. Nothing fails.
* **Three-valued facts.** Collapsing ``unknown`` into a default produces advice that is
  confidently wrong for exactly the accounts §4.5 exists to protect. Nothing fails.
* **Determinism.** A set iteration leaking into the rendering gives §21.5 a cache that misses
  at random and re-bills the user for advice already bought. Nothing fails.

None of the three announce themselves, which is why they are asserted rather than reviewed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tracker.content.loader import Content
from tracker.content.schema import Candidate, Item, MethodDetail, TrainingMethod
from tracker.domain.types import (
    Acceleration,
    AccountType,
    BandEstimate,
    CandidateKind,
    Consequences,
    Container,
    GateProgress,
    GoalProgress,
    ItemObservation,
    LeafRef,
    PlayerState,
    QuestStatus,
    Recommendation,
    RoadmapSelection,
    UnblockedCapability,
    UnlockState,
)
from tracker.guidance.context import UNKNOWN, build_task_context

ALL_SKILLS: tuple[str, ...] = (
    "attack",
    "strength",
    "defence",
    "ranged",
    "prayer",
    "magic",
    "runecraft",
    "construction",
    "hitpoints",
    "agility",
    "herblore",
    "thieving",
    "crafting",
    "fletching",
    "slayer",
    "hunter",
    "mining",
    "smithing",
    "fishing",
    "cooking",
    "firemaking",
    "woodcutting",
    "farming",
)


class TestRelevance:
    def test_only_skills_the_task_names_are_included(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """Twenty-three skills in, two out. This is the whole point of §21.2."""
        state = make_player_state(skills=dict.fromkeys(ALL_SKILLS, 70))
        candidate = make_candidate(
            "train_slayer_10",
            completion={"skill": {"slayer": 10}},
            requires={"skill": {"attack": 40}},
        )
        context = build_task_context(
            state=state,
            recommendation=make_recommendation(),
            content=make_content(candidates=[candidate]),
            roadmaps=no_roadmaps,
        )

        assert [skill.skill_id for skill in context.relevant_skills] == ["attack", "slayer"]

    def test_a_skill_carries_the_target_that_makes_it_a_task(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """*87* is a level. *87 -> 94* is a piece of work, and only the second is useful."""
        state = make_player_state(skills={"magic": 87})
        candidate = make_candidate("train_magic_94", completion={"skill": {"magic": 94}})
        context = build_task_context(
            state=state,
            recommendation=make_recommendation("train_magic_94"),
            content=make_content(candidates=[candidate]),
            roadmaps=no_roadmaps,
        )

        magic = context.relevant_skills[0]
        assert (magic.level, magic.target) == (87, 94)

    def test_the_highest_target_wins_when_two_trees_name_one_skill(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        candidate = make_candidate(
            "train_magic_94",
            requires={"skill": {"magic": 75}},
            completion={"skill": {"magic": 94}},
        )
        context = build_task_context(
            state=make_player_state(skills={"magic": 80}),
            recommendation=make_recommendation("train_magic_94"),
            content=make_content(candidates=[candidate]),
            roadmaps=no_roadmaps,
        )

        assert context.relevant_skills[0].target == 94

    def test_a_never_observed_skill_is_none_rather_than_level_one(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """ "We have never seen this skill" and "you are level 1" start differently."""
        context = build_task_context(
            state=make_player_state(skills={}),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        slayer = context.relevant_skills[0]
        assert slayer.level is None
        assert slayer.is_ranked is False

    def test_an_unranked_skill_is_distinguishable_from_a_ranked_one(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """G5 - ``xp is None`` is unranked, which is not the same as zero XP."""
        context = build_task_context(
            state=make_player_state(skills={"slayer": 1}, unranked=["slayer"]),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert context.relevant_skills[0].is_ranked is False

    def test_quests_and_unlocks_come_only_from_the_task_and_its_blockers(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        state = make_player_state(
            skills={"magic": 87},
            quests={
                "desert_treasure_i": QuestStatus.IN_PROGRESS,
                "cooks_assistant": QuestStatus.COMPLETE,
            },
            unlocks={
                "ancient_magicks": UnlockState.LOCKED,
                "rigour": UnlockState.AVAILABLE,
            },
        )
        candidate = make_candidate(
            "train_magic_94",
            requires={"quest": "desert_treasure_i"},
            completion={"skill": {"magic": 94}},
        )
        recommendation = make_recommendation(
            "train_magic_94",
            blockers=[LeafRef(leaf_type="unlock", key="ancient_magicks", description="Ancients")],
        )
        context = build_task_context(
            state=state,
            recommendation=recommendation,
            content=make_content(
                candidates=[candidate], quests={"desert_treasure_i": "Desert Treasure I"}
            ),
            roadmaps=no_roadmaps,
        )

        assert context.relevant_quests == (("Desert Treasure I", "in_progress"),)
        assert context.relevant_unlocks == (("ancient_magicks", "locked"),)

    def test_a_candidate_absent_from_the_corpus_yields_an_empty_slice_not_an_error(
        self,
        make_player_state: Callable[..., PlayerState],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """§9.8's synthesized refreshers have ids no content file declares."""
        context = build_task_context(
            state=make_player_state(skills=dict.fromkeys(ALL_SKILLS, 70)),
            recommendation=make_recommendation("practice_nh_combat", kind=CandidateKind.PRACTICE),
            content=make_content(),
            roadmaps=no_roadmaps,
        )

        assert context.relevant_skills == ()
        assert context.methods == ()
        assert context.task_name == "Train Slayer to 10"


class TestMethods:
    def test_methods_are_filtered_to_the_skill_and_the_estimated_band(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """A level-1 method and a level-92 method are both wrong answers to a 70 -> 75 task."""
        methods = [
            make_method("low", skill="magic", from_level=1, to_level=20),
            make_method("mid", skill="magic", from_level=60, to_level=80),
            make_method("high", skill="magic", from_level=92, to_level=99),
            make_method("other_skill", skill="slayer", from_level=1, to_level=99),
        ]
        recommendation = make_recommendation(
            "train_magic_75",
            bands=[BandEstimate(from_level=70, to_level=75, method_id="mid", hours=3.0, gp=0)],
        )
        context = build_task_context(
            state=make_player_state(skills={"magic": 70}),
            recommendation=recommendation,
            content=make_content(
                candidates=[make_candidate("train_magic_75", completion={"skill": {"magic": 75}})],
                methods=methods,
            ),
            roadmaps=no_roadmaps,
        )

        assert [method.method_id for method in context.methods] == ["mid"]

    def test_the_band_selected_method_is_marked_and_sorted_first(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """Without the marker, the app can say *16 hours* about a plan the model didn't give."""
        methods = [
            make_method("fast", skill="magic", from_level=1, to_level=99, xp_per_hour=250_000),
            make_method("slow", skill="magic", from_level=1, to_level=99, xp_per_hour=35_000),
        ]
        recommendation = make_recommendation(
            "train_magic_75",
            bands=[BandEstimate(from_level=70, to_level=75, method_id="slow", hours=9.0, gp=0)],
        )
        context = build_task_context(
            state=make_player_state(skills={"magic": 70}),
            recommendation=recommendation,
            content=make_content(
                candidates=[make_candidate("train_magic_75", completion={"skill": {"magic": 75}})],
                methods=methods,
            ),
            roadmaps=no_roadmaps,
        )

        assert [(m.method_id, m.selected) for m in context.methods] == [
            ("slow", True),
            ("fast", False),
        ]

    def test_a_method_detail_reaches_the_context_intact(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """§10.5's detail exists for exactly this - it is the "how" the ranking may not read."""
        detail = MethodDetail(
            location="Turael, Burthorpe",
            target="low-level assigned tasks",
            gear=("any melee weapon",),
            inventory=("food",),
            notes="Turael tasks are short and safe.",
            wiki_url="https://example.invalid/turael",
        )
        method = make_method("turael", skill="slayer", detail=detail)
        context = build_task_context(
            state=make_player_state(skills={"slayer": 1}),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")], methods=[method]),
            roadmaps=no_roadmaps,
        )

        fact = context.methods[0]
        assert fact.location == "Turael, Burthorpe"
        assert fact.gear == ("any melee weapon",)
        assert fact.wiki_url == "https://example.invalid/turael"

    def test_a_methods_own_gate_is_rendered(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        requirement: Callable[..., Any],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        method = make_method(
            "bursting",
            skill="magic",
            requires=requirement({"all_of": [{"quest": "desert_treasure_i"}, {"members": True}]}),
        )
        context = build_task_context(
            state=make_player_state(skills={"magic": 87}),
            recommendation=make_recommendation("train_magic_94"),
            content=make_content(
                candidates=[make_candidate("train_magic_94", completion={"skill": {"magic": 94}})],
                methods=[method],
            ),
            roadmaps=no_roadmaps,
        )

        assert context.methods[0].gate == "members, quest desert_treasure_i"

    def test_the_method_list_is_bounded(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """A model handed twelve options writes about the choice instead of about the task."""
        methods = [
            make_method(f"method_{index:02d}", skill="slayer", xp_per_hour=1_000 * index)
            for index in range(1, 13)
        ]
        context = build_task_context(
            state=make_player_state(skills={"slayer": 1}),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")], methods=methods),
            roadmaps=no_roadmaps,
        )

        assert len(context.methods) == 6

    def test_a_methods_skill_joins_the_skill_table_even_if_no_leaf_named_it(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """Otherwise the model is told to train something whose level it was never shown."""
        context = build_task_context(
            state=make_player_state(skills={"slayer": 4}),
            recommendation=make_recommendation(),
            content=make_content(
                candidates=[make_candidate("train_slayer_10")],
                methods=[make_method("turael", skill="slayer")],
            ),
            roadmaps=no_roadmaps,
        )

        assert [skill.skill_id for skill in context.relevant_skills] == ["slayer"]
        assert context.relevant_skills[0].level == 4


class TestThreeValuedFacts:
    """§4.5 and D8 at the prompt boundary. Every one of these has a named victim."""

    def test_an_unrecorded_account_type_is_unknown_not_main(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """The victim is the ironman who gets told to buy a Voidwaker."""
        context = build_task_context(
            state=make_player_state(account_type=None),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert context.account_type == UNKNOWN

    def test_a_recorded_account_type_is_carried(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        context = build_task_context(
            state=make_player_state(account_type=AccountType.IRONMAN),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert context.account_type == "ironman"

    @pytest.mark.parametrize(
        ("members", "expected"),
        [(None, UNKNOWN), (True, "yes"), (False, "no")],
    )
    def test_membership_keeps_all_three_states(
        self,
        members: bool | None,
        expected: str,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        context = build_task_context(
            state=make_player_state(members=members),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert context.members == expected

    def test_unscanned_coins_are_none_and_an_empty_bank_is_zero(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        """§6.5's middle state. ``None`` means nobody looked; ``0`` means someone did."""
        content = make_content(candidates=[make_candidate("train_slayer_10")])
        recommendation = make_recommendation()

        never_scanned = build_task_context(
            state=make_player_state(),
            recommendation=recommendation,
            content=content,
            roadmaps=no_roadmaps,
        )
        scanned_and_empty = build_task_context(
            state=make_player_state(container_scans={Container.BANK: observed_at}),
            recommendation=recommendation,
            content=content,
            roadmaps=no_roadmaps,
        )
        scanned_with_coins = build_task_context(
            state=make_player_state(
                container_scans={Container.BANK: observed_at},
                observed_items={
                    995: ItemObservation(
                        item_id=995,
                        quantity=1_500_000,
                        containers=frozenset({Container.BANK}),
                        observed_at=observed_at,
                    )
                },
            ),
            recommendation=recommendation,
            content=content,
            roadmaps=no_roadmaps,
        )

        assert never_scanned.liquid_gp is None
        assert scanned_and_empty.liquid_gp == 0
        assert scanned_with_coins.liquid_gp == 1_500_000

    def test_an_unobserved_quest_or_unlock_reads_unknown(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        candidate = make_candidate(
            "train_magic_94",
            requires={"all_of": [{"quest": "desert_treasure_i"}, {"unlock": "ancient_magicks"}]},
            completion={"skill": {"magic": 94}},
        )
        context = build_task_context(
            state=make_player_state(skills={"magic": 87}),
            recommendation=make_recommendation("train_magic_94"),
            content=make_content(candidates=[candidate]),
            roadmaps=no_roadmaps,
        )

        assert context.relevant_quests == (("desert_treasure_i", UNKNOWN),)
        assert context.relevant_unlocks == (("ancient_magicks", UNKNOWN),)


class TestEngineOutputIsRelayedNotRecomputed:
    """D14 from the input side: whatever the engine said arrives unchanged."""

    def test_the_reason_line_is_carried_verbatim(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        reason = "unblocks Ice Barrage NH; quick to finish"
        context = build_task_context(
            state=make_player_state(),
            recommendation=make_recommendation(reason=reason),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert context.reason == reason

    def test_consequences_are_rendered_into_the_four_purpose_lists(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        consequences = Consequences(
            unblocks_capabilities=(
                UnblockedCapability(capability_id="ice_barrage_nh", name="Ice Barrage NH"),
            ),
            gate_progress=(
                GateProgress(
                    candidate_id="desert_treasure_i",
                    name="Desert Treasure I",
                    remaining_before=4,
                    remaining_after=3,
                ),
            ),
            goal_progress=(
                GoalProgress(
                    capability_id="boss_fundamentals",
                    name="Boss fundamentals",
                    weight=0.5,
                    remaining_before=3,
                    remaining_after=2,
                    on_roadmap=False,
                ),
            ),
            speeds_up=(
                Acceleration(
                    candidate_id="train_magic_94",
                    name="Train Magic to 94",
                    hours_before=113.0,
                    hours_after=16.0,
                ),
            ),
        )
        context = build_task_context(
            state=make_player_state(),
            recommendation=make_recommendation(consequences=consequences),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert context.unblocks == ("Ice Barrage NH",)
        assert context.needed_for == ("Desert Treasure I (3 of 4 requirements would remain)",)
        assert context.works_toward == ("Boss fundamentals (not on a chosen roadmap)",)
        assert context.speeds_up == ("Train Magic to 94: 113h -> 16h",)

    def test_a_cleared_gate_says_so_rather_than_counting_to_zero(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        consequences = Consequences(
            gate_progress=(
                GateProgress(
                    candidate_id="desert_treasure_i",
                    name="Desert Treasure I",
                    remaining_before=1,
                    remaining_after=0,
                ),
            )
        )
        context = build_task_context(
            state=make_player_state(),
            recommendation=make_recommendation(consequences=consequences),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert context.needed_for == ("Desert Treasure I (this clears the last requirement)",)

    def test_blockers_and_the_blocked_flag_are_carried(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        blocker = LeafRef(leaf_type="quest", key="lunar_diplomacy", description="Lunar Diplomacy")
        context = build_task_context(
            state=make_player_state(),
            recommendation=make_recommendation(blocked=True, blockers=[blocker]),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert context.blocked is True
        assert context.blockers == (blocker,)

    def test_roadmaps_are_normalized_and_named(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
    ) -> None:
        context = build_task_context(
            state=make_player_state(),
            recommendation=make_recommendation(),
            content=make_content(
                candidates=[make_candidate("train_slayer_10")],
                roadmaps={"main_nh": "Main NH", "pvm_ladder": "PvM ladder"},
            ),
            roadmaps=RoadmapSelection(weights={"main_nh": 3.0, "pvm_ladder": 1.0}),
        )

        assert context.roadmaps == (("Main NH", 0.75), ("PvM ladder", 0.25))


class TestDeterminism:
    def test_building_twice_gives_an_identical_context(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        state = make_player_state(skills=dict.fromkeys(ALL_SKILLS, 70))
        content = make_content(
            candidates=[make_candidate("train_slayer_10")],
            methods=[make_method(f"m{index}", skill="slayer") for index in range(4)],
        )
        recommendation = make_recommendation()

        first = build_task_context(
            state=state, recommendation=recommendation, content=content, roadmaps=no_roadmaps
        )
        second = build_task_context(
            state=state, recommendation=recommendation, content=content, roadmaps=no_roadmaps
        )

        assert first == second

    def test_reordering_the_corpus_does_not_reorder_the_context(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """A YAML file's key order must not decide whether §21.5's cache hits."""
        methods = [
            make_method("alpha", skill="slayer", xp_per_hour=5_000),
            make_method("beta", skill="slayer", xp_per_hour=5_000),
            make_method("gamma", skill="slayer", xp_per_hour=5_000),
        ]
        state = make_player_state(skills={"slayer": 1})
        recommendation = make_recommendation()
        candidate = make_candidate("train_slayer_10")

        forward = build_task_context(
            state=state,
            recommendation=recommendation,
            content=make_content(candidates=[candidate], methods=methods),
            roadmaps=no_roadmaps,
        )
        reversed_ = build_task_context(
            state=state,
            recommendation=recommendation,
            content=make_content(candidates=[candidate], methods=list(reversed(methods))),
            roadmaps=no_roadmaps,
        )

        assert forward.methods == reversed_.methods


class TestItems:
    """§4.5's three states, applied to the one fact a player asks about by name.

    "What am I wearing" is not a requirement leaf and never appears in one, so none of the
    slice logic above reaches it. Left unsaid, the model fills the gap with a guess and
    prefaces otherwise-good advice with a caveat about gear it could have been shown — which
    is the failure these tests exist to hold shut.
    """

    def test_a_held_item_is_reported_with_its_containers(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        context = build_task_context(
            state=make_player_state(
                container_scans={Container.EQUIPMENT: observed_at},
                observed_items={
                    27690: ItemObservation(
                        item_id=27690,
                        quantity=1,
                        containers=frozenset({Container.EQUIPMENT}),
                        observed_at=observed_at,
                    )
                },
            ),
            recommendation=make_recommendation(),
            content=make_content(
                candidates=[make_candidate("train_slayer_10")],
                items=[Item(id="voidwaker", name="Voidwaker", item_id=27690)],
            ),
            roadmaps=no_roadmaps,
        )

        assert [(fact.name, fact.state) for fact in context.items] == [("Voidwaker", "held")]
        assert context.items[0].containers == ("equipment",)

    def test_an_unseen_item_is_unknown_until_every_container_is_scanned(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        """A bank scan alone cannot prove they are not *wearing* the thing (§4.5)."""
        content = make_content(
            candidates=[make_candidate("train_slayer_10", requires={"item": "voidwaker"})],
            items=[Item(id="voidwaker", name="Voidwaker", item_id=27690)],
        )

        def state_with(*scanned: Container) -> PlayerState:
            return make_player_state(container_scans=dict.fromkeys(scanned, observed_at))

        def item_state(*scanned: Container) -> str:
            context = build_task_context(
                state=state_with(*scanned),
                recommendation=make_recommendation(),
                content=content,
                roadmaps=no_roadmaps,
            )
            return context.items[0].state

        assert item_state(Container.BANK) == UNKNOWN
        assert item_state(Container.BANK, Container.INVENTORY) == UNKNOWN
        assert item_state(Container.BANK, Container.INVENTORY, Container.EQUIPMENT) == "not held"

    def test_an_unheld_item_this_task_does_not_need_is_not_listed(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        """Relevance again: *"they do not have this irrelevant thing"* is bought tokens."""
        context = build_task_context(
            state=make_player_state(
                container_scans=dict.fromkeys(Container, observed_at),
            ),
            recommendation=make_recommendation(),
            content=make_content(
                candidates=[make_candidate("train_slayer_10")],
                items=[Item(id="voidwaker", name="Voidwaker", item_id=27690)],
            ),
            roadmaps=no_roadmaps,
        )

        assert context.items == ()

    def test_a_required_item_is_listed_even_when_not_held(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        context = build_task_context(
            state=make_player_state(container_scans=dict.fromkeys(Container, observed_at)),
            recommendation=make_recommendation(),
            content=make_content(
                candidates=[make_candidate("train_slayer_10", requires={"item": "voidwaker"})],
                items=[Item(id="voidwaker", name="Voidwaker", item_id=27690)],
            ),
            roadmaps=no_roadmaps,
        )

        assert [(fact.name, fact.state, fact.required) for fact in context.items] == [
            ("Voidwaker", "not held", True)
        ]

    def test_an_item_with_no_numeric_id_is_skipped_rather_than_reported_absent(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        """It can never appear in an observation, so *"not held"* would be a permanent lie."""
        context = build_task_context(
            state=make_player_state(container_scans=dict.fromkeys(Container, observed_at)),
            recommendation=make_recommendation(),
            content=make_content(
                candidates=[make_candidate("train_slayer_10", requires={"item": "blowpipe"})],
                items=[Item(id="blowpipe", name="Toxic blowpipe")],
            ),
            roadmaps=no_roadmaps,
        )

        assert context.items == ()

    def test_scanned_containers_are_reported_in_a_fixed_order(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        """A dict insertion order leaking here would move §21.5's hash at random."""

        def scanned(*containers: Container) -> tuple[str, ...]:
            context = build_task_context(
                state=make_player_state(container_scans=dict.fromkeys(containers, observed_at)),
                recommendation=make_recommendation(),
                content=make_content(candidates=[make_candidate("train_slayer_10")]),
                roadmaps=no_roadmaps,
            )
            return context.scanned_containers

        assert scanned(Container.EQUIPMENT, Container.BANK) == ("bank", "equipment")
        assert scanned(Container.BANK, Container.EQUIPMENT) == ("bank", "equipment")
        assert scanned() == ()


class TestGearLadders:
    """§10.5's rungs — the answer to *"what am I actually using?"*.

    No requirement leaf asks that question, so none of the slice logic above reaches it, and
    a guidance answer that has to guess at it opens with an apology instead of advice.
    """

    def test_the_best_held_rung_wins_and_names_the_next_one(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        ladder = [
            Item(id="bronze", name="Bronze", item_id=1, slot="weapon", style="melee", tier=1),
            Item(id="rune", name="Rune", item_id=2, slot="weapon", style="melee", tier=2),
            Item(id="dragon", name="Dragon", item_id=3, slot="weapon", style="melee", tier=3),
        ]
        # Holding two rungs is the ordinary case — the old one stays in the bank.
        context = build_task_context(
            state=make_player_state(
                container_scans=dict.fromkeys(Container, observed_at),
                observed_items={
                    1: ItemObservation(
                        item_id=1,
                        quantity=1,
                        containers=frozenset({Container.BANK}),
                        observed_at=observed_at,
                    ),
                    2: ItemObservation(
                        item_id=2,
                        quantity=1,
                        containers=frozenset({Container.EQUIPMENT}),
                        observed_at=observed_at,
                    ),
                },
            ),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")], items=ladder),
            roadmaps=no_roadmaps,
        )

        rung = context.gear[0]
        assert (rung.best_held, rung.best_tier) == ("Rune", 2)
        assert (rung.next_name, rung.next_tier) == ("Dragon", 3)
        assert rung.ladder_size == 3

    def test_a_variant_id_counts_as_owning_the_item(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        """The charged blowpipe again: matching ``item_id`` alone would report it missing."""
        blowpipe = Item(
            id="toxic_blowpipe",
            name="Toxic blowpipe",
            item_id=12924,  # the empty form — the only one with a market price
            variant_item_ids=(12926,),  # charged, and untradeable
            slot="weapon",
            style="ranged",
            tier=1,
        )
        context = build_task_context(
            state=make_player_state(
                container_scans=dict.fromkeys(Container, observed_at),
                observed_items={
                    12926: ItemObservation(
                        item_id=12926,
                        quantity=1,
                        containers=frozenset({Container.EQUIPMENT}),
                        observed_at=observed_at,
                    )
                },
            ),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")], items=[blowpipe]),
            roadmaps=no_roadmaps,
        )

        assert context.gear[0].best_held == "Toxic blowpipe"

    def test_an_empty_ladder_is_uncertain_until_every_container_is_scanned(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        """*"They own no weapon"* off a bank scan alone is a guess about the equipment slot."""
        ladder = [Item(id="rune", name="Rune", item_id=2, slot="weapon", style="melee", tier=1)]
        content = make_content(candidates=[make_candidate("train_slayer_10")], items=ladder)

        def certain_with(*scanned: Container) -> bool:
            context = build_task_context(
                state=make_player_state(container_scans=dict.fromkeys(scanned, observed_at)),
                recommendation=make_recommendation(),
                content=content,
                roadmaps=no_roadmaps,
            )
            return context.gear[0].certain

        assert certain_with(Container.BANK) is False
        assert certain_with(*Container) is True

    def test_a_held_item_on_a_ladder_is_not_also_listed_as_a_loose_item(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: Any,
    ) -> None:
        """Two mentions of one sword invite the model to infer two swords."""
        ladder = [Item(id="rune", name="Rune", item_id=2, slot="weapon", style="melee", tier=1)]
        context = build_task_context(
            state=make_player_state(
                container_scans=dict.fromkeys(Container, observed_at),
                observed_items={
                    2: ItemObservation(
                        item_id=2,
                        quantity=1,
                        containers=frozenset({Container.EQUIPMENT}),
                        observed_at=observed_at,
                    )
                },
            ),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")], items=ladder),
            roadmaps=no_roadmaps,
        )

        assert context.gear[0].best_held == "Rune"
        assert context.items == ()

    def test_ladders_are_ordered_independently_of_the_corpus(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """A YAML reordering must not move §21.5's hash."""
        ladder = [
            Item(id="a", name="A", item_id=1, slot="weapon", style="melee", tier=1),
            Item(id="b", name="B", item_id=2, slot="head", style="magic", tier=1),
            Item(id="c", name="C", item_id=3, slot="weapon", style="ranged", tier=1),
        ]

        def gear_for(items: list[Item]) -> tuple[Any, ...]:
            context = build_task_context(
                state=make_player_state(),
                recommendation=make_recommendation(),
                content=make_content(candidates=[make_candidate("train_slayer_10")], items=items),
                roadmaps=no_roadmaps,
            )
            return context.gear

        assert gear_for(ladder) == gear_for(list(reversed(ladder)))
