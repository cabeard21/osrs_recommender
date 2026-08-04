"""Band partitioning and method selection (§8.2, §16.4).

The synthetic table throughout is §8.1's own shape: one fast method gated behind an unlock
and valid only from level 82, one slow method available to everybody. That is the shape
the algorithm exists for — *"the fast method is frequently gated behind the very content
the recommender is trying to sequence"* — and it makes each rule below fail in isolation.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tracker.content.loader import Content
from tracker.content.schema import TrainingMethod
from tracker.domain.types import (
    BandEstimate,
    Confidence,
    PlayerState,
    QuestStatus,
    Tri,
    UnlockState,
)
from tracker.estimation.methods import (
    FALLBACK_XP_PER_HOUR,
    LevelBand,
    method_confidence,
    partition_bands,
    plan_bands,
    select_method,
)
from tracker.estimation.xp_table import xp_for_level
from tracker.progression.evaluate import Evaluator

BURSTING_GATE = {"unlock": "ancient_magicks"}


@pytest.fixture
def table(method: Callable[..., TrainingMethod]) -> tuple[TrainingMethod, ...]:
    """§8.1's example plus a conservative always-available default."""
    return (
        method(
            "bursting",
            xp_per_hour=250_000,
            levels=(82, 99),
            cost_per_hour_gp=400_000,
            requires=BURSTING_GATE,
        ),
        method("splashing", xp_per_hour=35_000, levels=(1, 99), cost_per_hour_gp=40_000),
    )


def plan(
    content: Content, player: PlayerState, *, from_level: int, to_level: int
) -> tuple[BandEstimate, ...]:
    return plan_bands(
        "magic",
        current_xp=xp_for_level(from_level),
        from_level=from_level,
        to_level=to_level,
        content=content,
        evaluator=Evaluator(player, content),
    )


class TestPartitioning:
    def test_a_method_valid_only_from_82_splits_the_span(
        self, table: tuple[TrainingMethod, ...]
    ) -> None:
        """§8.2 step 2. One rate over 70→94 would be wrong in both directions at once."""
        assert partition_bands(70, 94, table) == (LevelBand(70, 82), LevelBand(82, 94))

    def test_a_span_wholly_inside_one_method_is_one_band(
        self, table: tuple[TrainingMethod, ...]
    ) -> None:
        assert partition_bands(87, 94, table) == (LevelBand(87, 94),)

    def test_the_upper_boundary_cuts_at_max_plus_one(
        self, method: Callable[..., TrainingMethod]
    ) -> None:
        """A method capped at 80 stops applying *at* level 81, not at 80."""
        capped = (method("early", xp_per_hour=50_000, levels=(1, 80)),)
        assert partition_bands(70, 94, capped) == (LevelBand(70, 81), LevelBand(81, 94))

    def test_an_already_met_target_partitions_into_nothing(
        self, table: tuple[TrainingMethod, ...]
    ) -> None:
        """Not "zero hours at an unknown rate" — there is simply nothing to estimate."""
        assert partition_bands(94, 94, table) == ()
        assert partition_bands(96, 94, table) == ()


class TestSelection:
    def test_the_fastest_available_method_wins(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        content = build_content(methods=table)
        unlocked = state(skills={"magic": 87}, unlocks={"ancient_magicks": UnlockState.UNLOCKED})
        selected = select_method(LevelBand(87, 94), table, Evaluator(unlocked, content))
        assert selected is not None
        assert selected.id == "bursting"

    def test_a_locked_fast_method_is_skipped_for_a_slower_available_one(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        """§8.2 step 3 selects among methods the player *currently* satisfies."""
        content = build_content(methods=table)
        locked = state(skills={"magic": 87}, unlocks={"ancient_magicks": UnlockState.LOCKED})
        selected = select_method(LevelBand(87, 94), table, Evaluator(locked, content))
        assert selected is not None
        assert selected.id == "splashing"

    def test_a_method_whose_gate_is_unknown_is_likewise_not_selected(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        """§9.1's rule, one layer out: an account that has never synced its unlocks does
        not *currently satisfy* Ancients. Collapsing ``unknown`` into satisfied would quote
        bursting hours for training the player may not be able to start."""
        content = build_content(methods=table)
        never_synced = state(skills={"magic": 87})  # no unlocks observed at all

        gate = table[0].requires
        assert gate is not None
        assert Evaluator(never_synced, content).evaluate(gate).value is Tri.UNKNOWN

        selected = select_method(LevelBand(87, 94), table, Evaluator(never_synced, content))
        assert selected is not None
        assert selected.id == "splashing"

    def test_available_is_not_satisfied_here_either(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        """§6.3's trap (A5) reaching a method gate: *available* means purchasable."""
        content = build_content(methods=table)
        available = state(skills={"magic": 87}, unlocks={"ancient_magicks": UnlockState.AVAILABLE})
        selected = select_method(LevelBand(87, 94), table, Evaluator(available, content))
        assert selected is not None
        assert selected.id == "splashing"

    def test_a_band_below_the_fast_methods_range_gets_the_slow_one_even_when_unlocked(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        content = build_content(methods=table)
        unlocked = state(skills={"magic": 70}, unlocks={"ancient_magicks": UnlockState.UNLOCKED})
        selected = select_method(LevelBand(70, 82), table, Evaluator(unlocked, content))
        assert selected is not None
        assert selected.id == "splashing"


class TestIntegrationAcrossBands:
    def test_each_band_is_costed_at_its_own_rate(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        content = build_content(methods=table)
        unlocked = state(skills={"magic": 70}, unlocks={"ancient_magicks": UnlockState.UNLOCKED})

        bands = plan_bands(
            "magic",
            current_xp=xp_for_level(70),
            from_level=70,
            to_level=94,
            content=content,
            evaluator=Evaluator(unlocked, content),
        )

        assert [(band.from_level, band.to_level, band.method_id) for band in bands] == [
            (70, 82, "splashing"),
            (82, 94, "bursting"),
        ]
        assert bands[0].hours == pytest.approx((xp_for_level(82) - xp_for_level(70)) / 35_000)
        assert bands[1].hours == pytest.approx((xp_for_level(94) - xp_for_level(82)) / 250_000)
        assert bands[1].gp == round(bands[1].hours * 400_000)

    def test_the_first_band_charges_only_the_xp_not_already_earned(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        """A player two thirds through level 87 has done that XP already; charging for it
        again would overstate the first band by up to a full level."""
        content = build_content(methods=table)
        unlocked = state(skills={"magic": 87}, unlocks={"ancient_magicks": UnlockState.UNLOCKED})
        partway = xp_for_level(87) + (xp_for_level(88) - xp_for_level(87)) * 2 // 3

        bands = plan_bands(
            "magic",
            current_xp=partway,
            from_level=87,
            to_level=94,
            content=content,
            evaluator=Evaluator(unlocked, content),
        )

        assert bands[0].hours == pytest.approx((xp_for_level(94) - partway) / 250_000)


class TestTheFallbackBand:
    @pytest.fixture
    def only_high_levels(self, method: Callable[..., TrainingMethod]) -> tuple[TrainingMethod, ...]:
        """A corpus that authors nothing below 82 — the case §8.2 ends on."""
        return (method("bursting", xp_per_hour=250_000, levels=(82, 99), cost_per_hour_gp=400_000),)

    def test_a_band_with_no_method_falls_back_at_the_conservative_rate(
        self,
        only_high_levels: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        content = build_content(methods=only_high_levels)
        player = state(skills={"magic": 70})

        bands = plan_bands(
            "magic",
            current_xp=xp_for_level(70),
            from_level=70,
            to_level=94,
            content=content,
            evaluator=Evaluator(player, content),
        )

        low_band = bands[0]
        assert low_band.from_level == 70
        assert low_band.method_id is None
        assert low_band.fallback is True
        assert low_band.hours == pytest.approx(
            (xp_for_level(82) - xp_for_level(70)) / FALLBACK_XP_PER_HOUR
        )
        assert low_band.gp == 0

    def test_one_fallback_band_drags_method_confidence_to_low(
        self,
        only_high_levels: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
    ) -> None:
        """§8.4: high only when *every* band has an authored available method."""
        content = build_content(methods=only_high_levels)
        player = state(skills={"magic": 70}, unlocks={})

        mixed = plan_bands(
            "magic",
            current_xp=xp_for_level(70),
            from_level=70,
            to_level=94,
            content=content,
            evaluator=Evaluator(player, content),
        )
        covered = plan_bands(
            "magic",
            current_xp=xp_for_level(85),
            from_level=85,
            to_level=94,
            content=content,
            evaluator=Evaluator(player, content),
        )

        assert method_confidence(mixed) is Confidence.LOW
        assert method_confidence(covered) is Confidence.HIGH

    def test_the_fallback_rate_is_slower_than_anything_the_corpus_authors(
        self, seed_content: Content
    ) -> None:
        """An under-estimate is the dangerous direction: §9.4 ranks on ``effort_decay``,
        so a generous default would flatter the least-understood candidate."""
        authored = [m.xp_per_hour for m in seed_content.training_methods.values()]
        assert FALLBACK_XP_PER_HOUR < min(authored)


class TestAgainstTheShippedCorpus:
    def test_the_sdd_worked_example_selects_bursting_once_ancients_are_unlocked(
        self, seed_content: Content, state: Callable[..., PlayerState]
    ) -> None:
        """§8's headline line — *"Train Magic 87 → 94"* — through the real content.

        The corpus gates ``magic_bursting`` on Ancients **and** DT1, so both facts have to
        be positively observed; either one merely unsynced leaves the gate ``unknown``,
        which is the next test but one."""
        player = state(
            skills={"magic": 87},
            xp={"magic": xp_for_level(87)},
            unlocks={"ancient_magicks": UnlockState.UNLOCKED},
            quests={"desert_treasure_i": QuestStatus.COMPLETE},
        )
        bands = plan(seed_content, player, from_level=87, to_level=94)

        assert [band.method_id for band in bands] == ["magic_bursting"]

    def test_the_same_account_without_ancients_gets_the_conservative_method(
        self, seed_content: Content, state: Callable[..., PlayerState]
    ) -> None:
        player = state(
            skills={"magic": 87},
            unlocks={"ancient_magicks": UnlockState.LOCKED},
            quests={"desert_treasure_i": QuestStatus.COMPLETE},
        )
        bands = plan(seed_content, player, from_level=87, to_level=94)

        assert [band.method_id for band in bands] == ["magic_conservative"]
        assert method_confidence(bands) is Confidence.HIGH  # authored, just slower

    def test_an_unsynced_quest_alone_is_enough_to_lose_the_fast_method(
        self, seed_content: Content, state: Callable[..., PlayerState]
    ) -> None:
        """Half the gate observed is not the gate satisfied (§9.1's ``all_of`` table)."""
        player = state(skills={"magic": 87}, unlocks={"ancient_magicks": UnlockState.UNLOCKED})
        bands = plan(seed_content, player, from_level=87, to_level=94)

        assert [band.method_id for band in bands] == ["magic_conservative"]
