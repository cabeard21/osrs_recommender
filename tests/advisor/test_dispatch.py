"""§22.4's dispatch: one class per tool, plus the two conventions that run through all of them.

The error-result tests are not politeness checks. A raised exception ends the turn; an error
result is something the model reads and corrects on the next iteration, and the difference is
whether a mistyped id costs the user an answer.
"""

from __future__ import annotations

from typing import Any

from tests.advisor.conftest import (
    make_capability_view,
    make_content,
    make_price,
    make_snapshot,
    make_state,
    make_task,
    scanned,
    skill_at,
)
from tracker.advisor.dispatch import execute_tool
from tracker.advisor.tools import MAX_TOOL_RESULT_CHARS
from tracker.content.schema import Candidate, Quest, TrainingMethod
from tracker.domain.types import BandEstimate, QuestStatus, UnlockState
from tracker.integrations.llm.types import ToolCall, ToolResult


def _run(name: str, snapshot: Any = None, **arguments: Any) -> ToolResult:
    return execute_tool(
        snapshot if snapshot is not None else make_snapshot(),
        ToolCall(call_id="call-1", name=name, arguments=arguments),
    )


def _item_candidate() -> Candidate:
    return Candidate(
        id="buy_coins", name="Buy coins", kind="acquisition", completion={"item": "coins"}
    )


class TestUnknownToolsAndBadArguments:
    def test_an_unknown_tool_is_an_error_result_not_an_exception(self) -> None:
        result = _run("no_such_tool")
        assert result.is_error
        assert "no tool named" in result.content

    def test_a_missing_required_argument_is_an_error_result(self) -> None:
        result = _run("get_candidate_detail")
        assert result.is_error
        assert "candidate_id" in result.content

    def test_a_wrongly_typed_argument_is_an_error_result(self) -> None:
        assert _run("get_skill_detail", skill_id=7).is_error

    def test_an_unknown_id_is_an_error_free_result_that_says_so(self) -> None:
        """Not an error: the lookup succeeded and the answer is *there is no such thing*."""
        result = _run("get_candidate_detail", candidate_id="nope")
        assert not result.is_error
        assert "No candidate with id" in result.content

    def test_the_call_id_is_echoed_back(self) -> None:
        """The provider matches results to calls by this; a dropped id breaks the turn."""
        assert _run("get_skill_detail", skill_id="magic").call_id == "call-1"

    def test_results_are_bounded_and_announce_truncation(self) -> None:
        quests = {
            f"quest_{index:03d}": Quest(
                id=f"quest_{index:03d}", name=f"A Rather Long Quest Name Number {index}"
            )
            for index in range(500)
        }
        snapshot = make_snapshot(content=make_content(quests=quests))
        result = _run("get_quest_status", snapshot, name_query="quest")
        assert len(result.content) <= MAX_TOOL_RESULT_CHARS


class TestSearchCandidates:
    def test_it_finds_by_substring(self) -> None:
        assert "train_magic_87_94" in _run("search_candidates", query="magic").content

    def test_it_filters_by_kind(self) -> None:
        result = _run("search_candidates", kind="quest")
        assert "quest_desert_treasure_i" in result.content
        assert "train_magic_87_94" not in result.content

    def test_it_filters_by_skill_named_in_the_trees(self) -> None:
        assert "train_magic_87_94" in _run("search_candidates", skill="magic").content

    def test_it_reports_rank_when_the_candidate_is_ranked(self) -> None:
        snapshot = make_snapshot(ranked=(make_task(rank=3),))
        assert "rank 3" in _run("search_candidates", snapshot, query="magic").content

    def test_it_says_so_when_a_candidate_is_not_ranked(self) -> None:
        assert "not in the latest ranked run" in _run("search_candidates", query="magic").content

    def test_no_match_is_stated_plainly(self) -> None:
        assert (
            "No candidate in the corpus matches" in _run("search_candidates", query="zzz").content
        )

    def test_the_limit_is_clamped_rather_than_rejected(self) -> None:
        """A model asking for 500 wants *lots*, not an error."""
        assert not _run("search_candidates", limit=500).is_error


class TestGetCandidateDetail:
    def test_it_renders_trees_with_three_valued_leaf_state(self) -> None:
        snapshot = make_snapshot(state=make_state(skills={"magic": skill_at(87)}))
        result = _run("get_candidate_detail", snapshot, candidate_id="train_magic_87_94")
        assert "Magic 94 (currently 87) — unsatisfied" in result.content

    def test_an_unobserved_skill_leaf_is_unknown_not_unsatisfied(self) -> None:
        result = _run("get_candidate_detail", candidate_id="train_magic_87_94")
        assert "never observed) — unknown" in result.content

    def test_a_satisfied_leaf_says_so(self) -> None:
        snapshot = make_snapshot(state=make_state(skills={"magic": skill_at(95)}))
        result = _run("get_candidate_detail", snapshot, candidate_id="train_magic_87_94")
        assert "— satisfied" in result.content

    def test_it_carries_the_engines_reason_and_rank(self) -> None:
        snapshot = make_snapshot(ranked=(make_task(rank=2, reason="unblocks Ice Barrage NH"),))
        result = _run("get_candidate_detail", snapshot, candidate_id="train_magic_87_94")
        assert "rank in the latest run: 2" in result.content
        assert "unblocks Ice Barrage NH" in result.content

    def test_it_renders_estimate_bands_with_their_method(self) -> None:
        band = BandEstimate(
            from_level=87, to_level=94, method_id="magic_bursting", hours=16.0, gp=19_200_000
        )
        snapshot = make_snapshot(ranked=(make_task(bands=(band,)),))
        result = _run("get_candidate_detail", snapshot, candidate_id="train_magic_87_94")
        assert "87→94 via magic_bursting" in result.content


class TestGetCapabilityDetail:
    def test_it_renders_status_and_the_full_tree(self) -> None:
        snapshot = make_snapshot(capabilities=(make_capability_view(),))
        result = _run("get_capability_detail", snapshot, capability_id="ice_barrage_nh")
        assert "requirements met: 50%" in result.content
        assert "all of:" in result.content
        assert "quest: Desert Treasure I" in result.content

    def test_an_unknown_id_lists_what_is_declared(self) -> None:
        assert "ice_barrage_nh" in _run("get_capability_detail", capability_id="nope").content

    def test_an_uncomputed_capability_says_so_rather_than_reading_as_locked(self) -> None:
        result = _run("get_capability_detail", capability_id="ice_barrage_nh")
        assert "not computed for this account" in result.content

    def test_an_available_unlock_leaf_is_unsatisfied(self) -> None:
        """§9.1 — obtainable is not held."""
        snapshot = make_snapshot(
            state=make_state(unlocks={"ancient_magicks": UnlockState.AVAILABLE})
        )
        result = _run("get_capability_detail", snapshot, capability_id="ice_barrage_nh")
        assert "unlock: ancient_magicks — unsatisfied" in result.content


class TestListTrainingMethods:
    def test_it_returns_the_authored_method_with_its_detail(self) -> None:
        result = _run("list_training_methods", skill_id="magic")
        assert "Barrage at Nechryael" in result.content
        assert "Catacombs of Kourend" in result.content

    def test_gear_is_labelled_as_descriptive(self) -> None:
        """§10.5 — an item requirement would reprice the candidate."""
        method = TrainingMethod(
            id="m",
            name="M",
            skill="magic",
            xp_per_hour=1000,
            level_range={"min": 1, "max": 99},
            detail={"gear": ("Ahrim's robetop",)},
        )
        snapshot = make_snapshot(content=make_content(training_methods={"m": method}))
        result = _run("list_training_methods", snapshot, skill_id="magic")
        assert "gear (descriptive, gates nothing): Ahrim's robetop" in result.content

    def test_a_skill_with_no_authored_method_says_so_explicitly(self) -> None:
        """The Slayer case — silence here would invite the model to invent the corpus."""
        result = _run("list_training_methods", skill_id="slayer")
        assert "holds no training method for Slayer" in result.content
        assert "rather than presenting your own suggestion" in result.content

    def test_a_level_range_outside_the_method_excludes_it(self) -> None:
        assert (
            "holds no training method"
            in _run("list_training_methods", skill_id="magic", to_level=50).content
        )


class TestGetQuestStatus:
    def test_an_unobserved_quest_is_unknown(self) -> None:
        result = _run("get_quest_status", name_query="desert")
        assert "Desert Treasure I" in result.content
        assert ": unknown" in result.content

    def test_it_explains_that_unknown_is_not_not_started(self) -> None:
        assert (
            "not the same as not started" in _run("get_quest_status", name_query="desert").content
        )

    def test_it_filters_by_status(self) -> None:
        snapshot = make_snapshot(
            state=make_state(quests={"desert_treasure_i": QuestStatus.COMPLETE})
        )
        result = _run("get_quest_status", snapshot, status="complete")
        assert "Desert Treasure I" in result.content
        assert "Dragon Slayer I" not in result.content

    def test_an_unknown_quest_id_is_named_back(self) -> None:
        assert "not_a_quest" in _run("get_quest_status", quest_ids=["not_a_quest"]).content

    def test_a_non_array_quest_ids_is_an_error_result(self) -> None:
        assert _run("get_quest_status", quest_ids="desert_treasure_i").is_error


class TestGetSkillDetail:
    def test_it_reports_xp_remaining(self) -> None:
        snapshot = make_snapshot(state=make_state(skills={"magic": skill_at(92, xp=6_517_253)}))
        result = _run("get_skill_detail", snapshot, skill_id="magic")
        assert "level 92" in result.content
        assert "xp to 99" in result.content

    def test_an_unranked_skill_says_so_and_offers_no_xp_arithmetic(self) -> None:
        snapshot = make_snapshot(state=make_state(skills={"magic": skill_at(70, xp=None)}))
        result = _run("get_skill_detail", snapshot, skill_id="magic")
        assert "unranked (no XP recorded)" in result.content
        assert "xp to 99" not in result.content

    def test_a_never_observed_skill_says_so(self) -> None:
        assert "never observed" in _run("get_skill_detail", skill_id="agility").content

    def test_it_names_the_capabilities_that_depend_on_it(self) -> None:
        assert "Ice Barrage NH" in _run("get_skill_detail", skill_id="magic").content

    def test_an_unknown_skill_says_so(self) -> None:
        assert "No skill with id" in _run("get_skill_detail", skill_id="cooking").content


class TestGetItemPrice:
    def test_it_returns_a_cached_price_with_both_timestamps(self) -> None:
        snapshot = make_snapshot(prices={995: make_price(price_gp=1)})
        result = _run("get_item_price", snapshot, item_ids=[995])
        assert "Coins" in result.content
        assert "traded" in result.content
        assert "fetched" in result.content

    def test_it_explains_why_the_two_timestamps_differ(self) -> None:
        """D10 — a fresh fetch of an old trade is not a current price."""
        snapshot = make_snapshot(prices={995: make_price()})
        assert "not a current price" in _run("get_item_price", snapshot, item_ids=[995]).content

    def test_an_uncached_item_is_reported_as_absent_rather_than_guessed(self) -> None:
        result = _run("get_item_price", item_ids=[4151])
        assert "Not in the price cache: 4151" in result.content
        assert "do not substitute a price of your own" in result.content

    def test_a_row_with_no_usable_figure_is_distinct_from_an_absent_row(self) -> None:
        snapshot = make_snapshot(prices={995: make_price(price_gp=None)})
        result = _run("get_item_price", snapshot, item_ids=[995])
        assert "no usable price recorded" in result.content
        assert "Not in the price cache" not in result.content

    def test_it_searches_by_name(self) -> None:
        snapshot = make_snapshot(prices={995: make_price(name="Coins")})
        assert "Coins" in _run("get_item_price", snapshot, name_query="coin").content

    def test_no_criteria_is_an_error_result(self) -> None:
        result = _run("get_item_price")
        assert result.is_error
        assert "item_ids" in result.content


class TestItemLeavesHonourG3:
    def test_an_item_is_unknown_when_nothing_has_been_scanned(self) -> None:
        """Absence from the observation map is not evidence when nobody has looked."""
        snapshot = make_snapshot(content=make_content(candidates={"buy_coins": _item_candidate()}))
        result = _run("get_candidate_detail", snapshot, candidate_id="buy_coins")
        assert "item: Coins — unknown" in result.content

    def test_an_item_is_unsatisfied_once_a_container_has_been_scanned(self) -> None:
        snapshot = make_snapshot(
            content=make_content(candidates={"buy_coins": _item_candidate()}),
            state=make_state(**scanned()),
        )
        result = _run("get_candidate_detail", snapshot, candidate_id="buy_coins")
        assert "item: Coins — unsatisfied" in result.content

    def test_an_observed_item_is_satisfied(self) -> None:
        snapshot = make_snapshot(
            content=make_content(candidates={"buy_coins": _item_candidate()}),
            state=make_state(**scanned(1_000)),
        )
        result = _run("get_candidate_detail", snapshot, candidate_id="buy_coins")
        assert "item: Coins — satisfied" in result.content
