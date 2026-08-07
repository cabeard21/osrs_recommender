"""§10.6's counterfactual: what would be true if this candidate were done."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest

from tracker.content.loader import Content
from tracker.content.requirements import parse
from tracker.domain.types import (
    PlayerState,
    QuestStatus,
    Source,
    Status,
    Tri,
    UnlockState,
)
from tracker.recommendations.facts import LeverageOracle, apply_facts

from .conftest import MYSTIC_ROBE_TOP, VOIDWAKER


class TestApplyFacts:
    """Each leaf type, and the two that are deliberately not facts."""

    def test_a_skill_grant_raises_the_level(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        state = player(skills={"magic": 87})

        after = apply_facts(state, parse({"skill": {"magic": 94}}), seed_content)

        assert after.skills["magic"].level == 94
        assert after.skills["magic"].source is Source.DERIVED

    def test_a_skill_grant_never_lowers_a_level(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """A grant that *reduced* a level would be a decrement from a derived source, which
        G4 forbids outright — and a completion predicate naming a level the player has
        already passed is ordinary content, not a mistake."""
        state = player(skills={"magic": 99})

        after = apply_facts(state, parse({"skill": {"magic": 94}}), seed_content)

        assert after.skills["magic"].level == 99

    def test_an_unlock_grant_unlocks(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        after = apply_facts(player(), parse({"unlock": "ancient_magicks"}), seed_content)

        assert after.unlocks["ancient_magicks"] is UnlockState.UNLOCKED

    def test_a_quest_grant_completes(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        after = apply_facts(player(), parse({"quest": "desert_treasure_i"}), seed_content)

        assert after.quests["desert_treasure_i"] is QuestStatus.COMPLETE

    def test_an_item_grant_records_a_scan_as_well_as_the_item(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """An item is only *visible* where a scan covers it (§6.5), so granting one without
        the scan would build a state the evaluator reads differently from the one this
        function claims to have built."""
        after = apply_facts(player(scanned=False), parse({"item": "voidwaker"}), seed_content)

        assert after.observed_items[VOIDWAKER].quantity == 1
        assert after.container_scans != {}

    def test_a_milestone_grant_does_not_manufacture_practice(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """Achieving an execution milestone is not the same as having practiced it — that is
        what a practice event records. Inventing a ``last_practiced_at`` here would let a
        progression candidate fabricate freshness, the mirror image of what G6 forbids."""
        after = apply_facts(
            player(), parse({"milestone": "comfortable_4_way_switches"}), seed_content
        )

        granted = after.milestones["comfortable_4_way_switches"]
        assert granted.achieved is True
        assert granted.attested is Tri.SATISFIED
        assert granted.last_practiced_at is None

    def test_a_capability_grant_is_refused(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """A capability is a *conclusion* about facts, not a fact. Writing one into the
        state would let a candidate claim an unlock it never earned."""
        state = player()

        after = apply_facts(state, parse({"capability": "ice_barrage_nh"}), seed_content)

        assert after == state

    def test_a_negated_grant_retracts_nothing(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """*"You will not have X"* is not something completing a candidate brings about, and
        retracting a fact is a decrement no derived source may make (G4)."""
        state = player(unlocks=["ancient_magicks"])

        after = apply_facts(state, parse({"not": {"unlock": "ancient_magicks"}}), seed_content)

        assert after.unlocks["ancient_magicks"] is UnlockState.UNLOCKED

    def test_all_of_applies_every_child(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """DT1's real ``grants_facts``: the quest *and* the unlock, since a ``quest:`` leaf
        alone would leave ``leverage`` unable to see what the reward actually opened."""
        grants = seed_content.candidates["complete_desert_treasure_i"].grants_facts
        assert grants is not None

        after = apply_facts(player(), grants, seed_content)

        assert after.quests["desert_treasure_i"] is QuestStatus.COMPLETE
        assert after.unlocks["ancient_magicks"] is UnlockState.UNLOCKED

    def test_any_of_applies_only_the_first_branch(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """The candidate does not say which branch it takes, so crediting it with all of
        them would grant more than it promises. First is arbitrary but deterministic, and it
        errs low."""
        grants = parse({"any_of": [{"unlock": "rigour"}, {"unlock": "protect_item"}]})

        after = apply_facts(player(), grants, seed_content)

        assert after.unlocks["rigour"] is UnlockState.UNLOCKED
        assert "protect_item" not in after.unlocks

    def test_the_original_state_is_never_mutated(
        self, player: Callable[..., PlayerState], seed_content: Content
    ) -> None:
        """A counterfactual that leaked into the real state would be indistinguishable from
        an observation — §4.5's error in its most damaging form."""
        state = player(skills={"magic": 87})

        apply_facts(state, parse({"skill": {"magic": 94}}), seed_content)

        assert state.skills["magic"].level == 87
        assert "ancient_magicks" not in state.unlocks


class TestLeverageOracle:
    """§10.6's *flip* question, and the caching that makes it affordable."""

    def _barrage_ready_but_for_magic(self, player: Callable[..., PlayerState]) -> PlayerState:
        """Everything ``ice_barrage_nh`` needs except the 94 Magic (§10.2's example)."""
        return player(
            skills={"magic": 87},
            unlocks=["ancient_magicks"],
            quests=["desert_treasure_i"],
            items=[MYSTIC_ROBE_TOP],
        )

    def test_it_reports_a_genuine_flip(
        self, player: Callable[..., PlayerState], seed_content: Content, now: datetime
    ) -> None:
        state = self._barrage_ready_but_for_magic(player)
        oracle = LeverageOracle(state, seed_content, now)
        grants = seed_content.candidates["train_magic_87_to_94"].grants_facts
        assert grants is not None

        assert oracle.baseline_status("ice_barrage_nh") is Status.LOCKED
        assert oracle("ice_barrage_nh", grants, state, seed_content) is True

    def test_an_already_unlocked_capability_does_not_count(
        self, player: Callable[..., PlayerState], seed_content: Content, now: datetime
    ) -> None:
        """*Flip*, not *state* (§10.6). Crediting a candidate for what the player already
        has would give every candidate the same number, which is no signal at all."""
        state = player(
            skills={"magic": 94},
            unlocks=["ancient_magicks"],
            quests=["desert_treasure_i"],
            items=[MYSTIC_ROBE_TOP],
        )
        oracle = LeverageOracle(state, seed_content, now)
        grants = seed_content.candidates["train_magic_87_to_94"].grants_facts
        assert grants is not None

        assert oracle.baseline_status("ice_barrage_nh") is Status.UNLOCKED
        assert oracle("ice_barrage_nh", grants, state, seed_content) is False

    def test_a_capability_still_short_of_other_requirements_does_not_flip(
        self, player: Callable[..., PlayerState], seed_content: Content, now: datetime
    ) -> None:
        """94 Magic alone does not open Deep Wilderness NH: it also wants the freeze-log and
        switch milestones and a spec weapon. Leverage counts what a grant *finishes*."""
        state = self._barrage_ready_but_for_magic(player)
        oracle = LeverageOracle(state, seed_content, now)
        grants = seed_content.candidates["train_magic_87_to_94"].grants_facts
        assert grants is not None

        assert oracle("deep_wildy_nh", grants, state, seed_content) is False

    def test_repeated_questions_agree(
        self, player: Callable[..., PlayerState], seed_content: Content, now: datetime
    ) -> None:
        """The memo is keyed on the grants tree's identity; asking twice must not differ."""
        state = self._barrage_ready_but_for_magic(player)
        oracle = LeverageOracle(state, seed_content, now)
        grants = seed_content.candidates["train_magic_87_to_94"].grants_facts
        assert grants is not None

        first = oracle("ice_barrage_nh", grants, state, seed_content)
        second = oracle("ice_barrage_nh", grants, state, seed_content)

        assert first == second is True

    def test_it_refuses_a_state_it_was_not_built_for(
        self, player: Callable[..., PlayerState], seed_content: Content, now: datetime
    ) -> None:
        """The memo table is only sound for the pinned pair, so a mismatch must fail loudly
        rather than answer confidently from another account's cache."""
        oracle = LeverageOracle(player(), seed_content, now)
        grants = seed_content.candidates["train_magic_87_to_94"].grants_facts
        assert grants is not None

        with pytest.raises(ValueError, match="pinned"):
            oracle("ice_barrage_nh", grants, player(), seed_content)
