"""§9.10's consequences, against the shipped corpus.

These run on the real ``content/`` for ``tests/recommendations/conftest.py``'s reason and
one of their own: the whole feature exists because *this* corpus produces recommendations
whose purpose is invisible, and the cases worth pinning are the ones a player actually saw.
A synthetic corpus would let every assertion here pass while the app still said nothing.

The account below is deliberately mid-levelled and fully synced. Both halves matter. A
bare account reports almost everything as *unknown* rather than as outstanding (G3), so it
would make these counts vacuously zero; a maxed one has no outstanding requirements left to
dent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest

from tracker.content.loader import Content
from tracker.domain.candidates import (
    MethodUnlockWinner,
    effective_capability_weights,
    unlock_flips,
)
from tracker.domain.consequences import consequences_for
from tracker.domain.types import PlayerState, RoadmapSelection
from tracker.recommendations.facts import GateOracle, LeverageOracle, _Worlds

#: Observed, and everywhere too low. Skills the account has never had observed evaluate
#: *unknown*, which is not a requirement anyone can be told to go and meet.
MID_LEVELS = {
    "attack": 40,
    "strength": 40,
    "defence": 40,
    "hitpoints": 45,
    "prayer": 30,
    "magic": 50,
    "slayer": 1,
    "thieving": 30,
    "firemaking": 40,
    "agility": 40,
    "ranged": 50,
    "herblore": 20,
}

#: The roadmap the user selected when they reported that the recommendations meant nothing.
PVM_LADDER = RoadmapSelection({"pvm_ladder": 1.0})


@pytest.fixture
def explain(
    player: Callable[..., PlayerState], seed_content: Content, now: datetime
) -> Callable[..., object]:
    """``explain(candidate_id, selection=...)`` — one candidate's consequences.

    Wires the same seams the engine wires, so a rule proved here is the rule the app runs:
    one :class:`_Worlds` shared by the oracles, and ``others`` set to every open candidate,
    which is the pool ``method_unlock`` measures against.
    """

    def build(
        candidate_id: str,
        *,
        selection: RoadmapSelection = PVM_LADDER,
        accelerated: MethodUnlockWinner | None = None,
    ) -> object:
        state = player(skills=MID_LEVELS)
        candidate = seed_content.candidates[candidate_id]
        worlds = _Worlds(state, seed_content)
        gates = GateOracle(worlds)
        return consequences_for(
            candidate,
            content=seed_content,
            weights=effective_capability_weights(selection, seed_content),
            unlocked_capability_ids=unlock_flips(
                candidate, state, seed_content, LeverageOracle(state, seed_content, now)
            ),
            accelerated=accelerated,
            others=list(seed_content.candidates.values()),
            outstanding_gate=gates,
            outstanding_capability_gate=gates.capability,
        )

    return build


class TestTheUsersOwnComplaint:
    """The three entries the PvM ladder actually produced, each pinned to what it is for."""

    def test_training_slayer_to_ten_is_reported_as_a_requirement_of_desert_treasure_i(
        self, explain: Callable[..., object]
    ) -> None:
        """The chain nothing computed before. The band advances no capability of its own —
        ``tools/generate_candidates.py`` gives every band ``advances: {}`` — so §9.4 scores
        it at the ε floor on goal value and it climbs the list on ``effort_decay``. What
        makes it worth doing is one hop away: Slayer 10 is a gate leaf of Desert Treasure I.
        """
        result = explain("train_slayer_1_to_10")

        quest = next(
            entry
            for entry in result.gate_progress  # type: ignore[attr-defined]
            if entry.candidate_id == "complete_desert_treasure_i"
        )
        assert (quest.remaining_before, quest.remaining_after) == (3, 2)
        assert [leaf.key for leaf in quest.satisfied] == ["slayer"]

    def test_training_slayer_to_ten_names_the_goal_beyond_the_quest(
        self, explain: Callable[..., object]
    ) -> None:
        """One hop past the gate: Desert Treasure I's own ``advances`` map. Ice Barrage NH
        leads because the corpus weights it 0.90 against Deep Wilderness NH's 0.60 — the
        editorial judgment §10.6 reserves for a human, used here as the tie-break the
        roadmap weight cannot supply when every link is off-roadmap."""
        links = explain("train_slayer_1_to_10").goal_links  # type: ignore[attr-defined]

        assert [link.name for link in links] == ["Ice Barrage NH", "Deep Wilderness NH"]
        assert links[0].via_name == "Complete Desert Treasure I"

    def test_the_goal_beyond_the_quest_is_flagged_as_off_the_pvm_ladder(
        self, explain: Callable[..., object]
    ) -> None:
        """The diagnostic the feature exists to deliver. Under the PvM ladder this band is
        working toward a PvP capability the player did not select — which is worth *saying*,
        not worth hiding, and not worth silently ranking as though it were a chosen goal."""
        links = explain("train_slayer_1_to_10").goal_links  # type: ignore[attr-defined]

        assert all(link.on_roadmap is False for link in links)

    def test_training_attack_to_sixty_dents_boss_fundamentals_directly(
        self, explain: Callable[..., object]
    ) -> None:
        """The band that *does* serve the chosen roadmap, and the contrast that makes the
        flag above legible. ``boss_fundamentals`` names ``skill: {attack: 60}`` outright, so
        this is measured against the capability's own requirements rather than inferred."""
        goals = explain("train_attack_1_to_60").goal_progress  # type: ignore[attr-defined]

        assert [(goal.name, goal.on_roadmap) for goal in goals] == [("Boss fundamentals", True)]
        assert (goals[0].remaining_before, goals[0].remaining_after) == (5, 4)

    def test_the_high_risk_setup_reveals_itself_as_serving_no_selected_goal(
        self, explain: Callable[..., object]
    ) -> None:
        """*"Buy a high-risk NH setup"* on a PvM roadmap was the entry that made least sense
        of the three. It advances ``anti_pk`` and ``deep_wildy_nh``, neither of which the PvM
        ladder weights, so its ``pvp_value`` is floored and it ranks on the other factors.
        Reporting both goals *and* flagging both is what turns a baffling row into a legible
        one."""
        goals = explain("buy_high_risk_gear").goal_progress  # type: ignore[attr-defined]

        assert goals
        assert all(goal.on_roadmap is False for goal in goals)

    def test_the_same_setup_is_not_flagged_when_the_player_picked_that_roadmap(
        self, explain: Callable[..., object]
    ) -> None:
        """The flag is about the *selection*, never about the candidate. Under Main NH the
        very same row is on-goal, and a flag that survived the switch would be a claim about
        content rather than about what the player asked for."""
        goals = explain(
            "buy_high_risk_gear", selection=RoadmapSelection({"main_nh": 1.0})
        ).goal_progress  # type: ignore[attr-defined]

        assert any(goal.on_roadmap for goal in goals)


class TestWhatItRefusesToSay:
    """The silences. Each is a sentence the engine could have invented and must not."""

    def test_a_measured_goal_suppresses_the_inferred_one(
        self, explain: Callable[..., object]
    ) -> None:
        """A guess shown beside a measurement reads as the same kind of claim. Attack 60
        dents ``boss_fundamentals`` outright, so nothing is gained by also reporting what
        the candidates it gates are hypothetically for."""
        result = explain("train_attack_1_to_60")

        assert result.goal_progress  # type: ignore[attr-defined]
        assert result.goal_links == ()  # type: ignore[attr-defined]

    def test_the_indirect_walk_stops_after_one_hop(self, explain: Callable[..., object]) -> None:
        """The capability DAG's closure from a low rung is most of the corpus. A transitive
        walk would name the top of the ladder for every band in the game, which is true,
        useless, and indistinguishable from saying nothing."""
        links = explain("train_slayer_1_to_10").goal_links  # type: ignore[attr-defined]

        assert "raid_ready" not in {link.capability_id for link in links}

    def test_the_accelerated_candidate_is_named_but_its_training_method_is_not(
        self, explain: Callable[..., object], seed_content: Content
    ) -> None:
        """``MethodDetail`` is descriptive content no ranking may read — two corpora
        differing only in it must produce byte-identical output. A consequence quoting a
        method name would put this one join away from breaking that."""
        winner = MethodUnlockWinner(
            other_id="train_magic_87_to_94", hours_before=113.0, hours_after=16.0, reduction=0.86
        )

        speeds_up = explain("train_slayer_1_to_10", accelerated=winner).speeds_up  # type: ignore[attr-defined]

        assert [entry.name for entry in speeds_up] == ["Train Magic 87 → 94"]
        method_names = {method.name for method in seed_content.training_methods.values()}
        assert not method_names & {entry.name for entry in speeds_up}

    def test_a_candidate_granting_no_facts_has_nothing_to_report(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """Silence, not a manufactured reason. A candidate that changes nothing objective
        cannot have unblocked, dented or accelerated anything, and inventing prose for it is
        precisely the authored justification §9.5 forbids."""
        state = player(skills=MID_LEVELS)
        gates = GateOracle(_Worlds(state, seed_content))
        candidate = seed_content.candidates["complete_desert_treasure_i"].model_copy(
            update={"grants_facts": None}
        )

        result = consequences_for(
            candidate,
            content=seed_content,
            weights=effective_capability_weights(PVM_LADDER, seed_content),
            unlocked_capability_ids=(),
            accelerated=None,
            others=list(seed_content.candidates.values()),
            outstanding_gate=gates,
            outstanding_capability_gate=gates.capability,
        )

        assert result.is_empty

    def test_a_candidate_is_never_reported_as_needed_for_itself(
        self, explain: Callable[..., object]
    ) -> None:
        """Its own grants clear its own gate trivially, which would make every gated
        candidate its own most urgent prerequisite."""
        result = explain("complete_desert_treasure_i")

        assert "complete_desert_treasure_i" not in {
            entry.candidate_id
            for entry in result.gate_progress  # type: ignore[attr-defined]
        }


class TestOrdering:
    """The card's contents must be a function of the corpus, not of the day it ran."""

    def test_two_identical_runs_report_identical_consequences(
        self, explain: Callable[..., object]
    ) -> None:
        assert explain("train_slayer_1_to_10") == explain("train_slayer_1_to_10")

    def test_the_nearest_unblock_is_reported_first(self, explain: Callable[..., object]) -> None:
        """``remaining_after`` ascending — what this most nearly finishes off leads, because
        that is the thing the player could act on next."""
        entries = explain("train_slayer_1_to_10").gate_progress  # type: ignore[attr-defined]

        assert [entry.remaining_after for entry in entries] == sorted(
            entry.remaining_after for entry in entries
        )

    def test_no_card_reports_more_than_the_documented_limits(
        self, explain: Callable[..., object]
    ) -> None:
        """The caps are what keep a card readable. A silent overflow would be a design
        regression that no other assertion here would notice."""
        for candidate_id in ("train_slayer_1_to_10", "train_attack_1_to_60", "buy_high_risk_gear"):
            result = explain(candidate_id)
            assert len(result.gate_progress) <= 3  # type: ignore[attr-defined]
            assert len(result.goal_progress) <= 2  # type: ignore[attr-defined]
            assert len(result.goal_links) <= 2  # type: ignore[attr-defined]
