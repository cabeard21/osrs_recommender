"""``estimate(candidate, ...) -> Estimate`` — §8 assembled (§16.4).

The two halves are unit-tested next door; what is tested here is the integration §8.4
specifies: which candidate kinds get hours, which get GP, and that ``estimate_confidence``
is the **minimum** of the two sub-confidences rather than either one of them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest

from tracker.content.loader import Content
from tracker.content.schema import Candidate, Item, RefresherTemplate, TrainingMethod
from tracker.domain.types import Confidence, PlayerState, QuestStatus, UnlockState
from tracker.estimation.estimate import estimate
from tracker.estimation.prices import (
    REASON_RECENT_HIGH,
    REASON_STATIC_HINT,
    REASON_UNKNOWN,
    PriceRecord,
)
from tracker.estimation.xp_table import xp_for_level

VOIDWAKER = Item(
    id="voidwaker",
    name="Voidwaker",
    item_id=27690,
    price_mode="live",
    fallback_price_gp=85_000_000,
    price_staleness_days=7,
)

MYSTIC_TOP = Item(id="mystic_robe_top", name="Mystic robe top", item_id=4091, price_mode="live")


@pytest.fixture
def table(method: Callable[..., TrainingMethod]) -> tuple[TrainingMethod, ...]:
    return (
        method(
            "bursting",
            xp_per_hour=250_000,
            levels=(82, 99),
            cost_per_hour_gp=400_000,
            requires={"unlock": "ancient_magicks"},
        ),
        method("splashing", xp_per_hour=35_000, levels=(1, 99), cost_per_hour_gp=40_000),
    )


class TestWhichKindGetsWhichNumber:
    """§10.6 authors neither ``hours`` nor ``gp_cost``, so every figure is derived — and
    where nothing can be derived the answer is ``None``, not a plausible-looking zero."""

    def test_skill_training_gets_both_hours_and_gp(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        now: datetime,
    ) -> None:
        train = candidate(
            "train_magic_87_to_94", kind="skill_training", completion={"skill": {"magic": 94}}
        )
        content = build_content(methods=table, candidates=[train])
        player = state(
            skills={"magic": 87},
            xp={"magic": xp_for_level(87)},
            unlocks={"ancient_magicks": UnlockState.UNLOCKED},
        )

        result = estimate(train, player, content, {}, now)

        assert result.hours is not None
        assert result.hours == pytest.approx((xp_for_level(94) - xp_for_level(87)) / 250_000)
        assert result.gp == round(result.hours * 400_000)
        assert [band.method_id for band in result.bands] == ["bursting"]
        assert result.price_selection_reason is None  # nothing to buy
        assert result.confidence is Confidence.HIGH

    def test_an_acquisition_gets_gp_but_no_hours(
        self,
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        """Nothing in the SDD says how long buying something takes, and §9.4's
        ``effort_decay`` would happily consume an invented figure."""
        buy = candidate("buy_voidwaker", kind="acquisition", completion={"item": "voidwaker"})
        content = build_content(items=[VOIDWAKER], candidates=[buy])
        player = state(skills={"magic": 87})
        prices = {
            27690: price_record(item_id=27690, high_price_gp=39_000_000, high_trade_at=ago(hours=2))
        }

        result = estimate(buy, player, content, prices, now)

        assert result.hours is None
        assert result.gp == 39_000_000
        assert result.bands == ()
        assert result.price_selection_reason == f"voidwaker: {REASON_RECENT_HIGH}"
        assert result.confidence is Confidence.HIGH

    def test_a_quest_candidate_gets_neither(
        self,
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        now: datetime,
    ) -> None:
        """No skill target and no item to buy. ``None`` twice, and ``low`` confidence
        because an estimate with no inputs has not earned anything better."""
        quest = candidate(
            "complete_desert_treasure_i",
            kind="quest",
            completion={"quest": "desert_treasure_i"},
        )
        content = build_content(candidates=[quest])
        player = state(skills={"magic": 87}, quests={"desert_treasure_i": QuestStatus.NOT_STARTED})

        result = estimate(quest, player, content, {}, now)

        assert result.hours is None
        assert result.gp is None
        assert result.confidence is Confidence.LOW

    def test_an_unlock_whose_completion_names_levels_gets_those_hours(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        now: datetime,
    ) -> None:
        """The rule is about the *predicate*, not the ``kind``: ``unlock_protect_item``
        completes at 25 Prayer, and the work is the Prayer levels."""
        unlock = candidate(
            "unlock_something",
            kind="unlock",
            completion={"all_of": [{"skill": {"magic": 90}}, {"unlock": "something"}]},
        )
        content = build_content(methods=table, candidates=[unlock])
        player = state(skills={"magic": 87}, xp={"magic": xp_for_level(87)})

        result = estimate(unlock, player, content, {}, now)

        assert result.hours is not None
        assert result.bands[-1].to_level == 90

    def test_a_practice_candidate_takes_its_hours_from_the_refresher_template(
        self,
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        now: datetime,
    ) -> None:
        """§10.4 / A8 — ``suggested_session_hours`` is mandatory precisely so a refresher
        cannot score ``effort_decay = exp(0) = 1.0``. GP is zero by the same section."""
        refresher = RefresherTemplate(
            id="refresh_nh_fundamentals",
            name="Refresh NH fundamentals",
            practice_group="nh_fundamentals",
            suggested_session="5 LMS matches",
            suggested_session_hours=0.5,
        )
        practice = candidate(
            "refresh_nh_fundamentals",
            kind="practice",
            completion={"milestone": "nh_switches"},
        )
        content = build_content(candidates=[practice], refreshers=[refresher])

        result = estimate(practice, state(), content, {}, now)

        assert result.hours == 0.5
        assert result.gp == 0
        assert result.confidence is Confidence.HIGH

    def test_a_never_observed_skill_withholds_the_estimate_rather_than_guessing(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        now: datetime,
    ) -> None:
        """§4.5. Assuming level 1 quotes forty hours the account may not owe; assuming the
        target is met quotes zero. Neither is a fact, so the answer is *sync this*."""
        train = candidate("train_magic", kind="skill_training", completion={"skill": {"magic": 94}})
        content = build_content(methods=table, candidates=[train])

        result = estimate(train, state(), content, {}, now)

        assert result.hours is None
        assert result.confidence is Confidence.LOW


class TestAcquisitionCosts:
    def test_items_named_by_completion_are_charged_at_the_resolved_price(
        self,
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        buy = candidate(
            "buy_a_set",
            kind="acquisition",
            completion={"all_of": [{"item": "voidwaker"}, {"item": "mystic_robe_top"}]},
        )
        content = build_content(items=[VOIDWAKER, MYSTIC_TOP], candidates=[buy])
        prices = {
            27690: price_record(
                item_id=27690, high_price_gp=39_000_000, high_trade_at=ago(hours=2)
            ),
            4091: price_record(item_id=4091, high_price_gp=120_000, high_trade_at=ago(hours=2)),
        }

        result = estimate(buy, state(), content, prices, now)

        assert result.gp == 39_120_000
        assert result.price_selection_reason == (
            f"voidwaker: {REASON_RECENT_HIGH}; mystic_robe_top: {REASON_RECENT_HIGH}"
        )

    def test_an_item_the_player_already_holds_is_not_charged_for(
        self,
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        """Billing a player for the Voidwaker in their bank would inflate the candidate
        they are closest to finishing."""
        buy = candidate(
            "buy_a_set",
            kind="acquisition",
            completion={"all_of": [{"item": "voidwaker"}, {"item": "mystic_robe_top"}]},
        )
        content = build_content(items=[VOIDWAKER, MYSTIC_TOP], candidates=[buy])
        holder = state(owned=[27690])
        prices = {
            27690: price_record(
                item_id=27690, high_price_gp=39_000_000, high_trade_at=ago(hours=2)
            ),
            4091: price_record(item_id=4091, high_price_gp=120_000, high_trade_at=ago(hours=2)),
        }

        result = estimate(buy, holder, content, prices, now)

        assert result.gp == 120_000
        assert result.price_selection_reason == f"mystic_robe_top: {REASON_RECENT_HIGH}"

    def test_an_unscanned_item_is_still_charged_for(
        self,
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        """§4.5 cuts the other way for cost: an item nobody has scanned for is not one we
        may claim the player holds, and §8.3 estimates acquisition conservatively."""
        buy = candidate("buy_voidwaker", kind="acquisition", completion={"item": "voidwaker"})
        content = build_content(items=[VOIDWAKER], candidates=[buy])
        never_scanned = state(scanned=False)
        prices = {
            27690: price_record(item_id=27690, high_price_gp=39_000_000, high_trade_at=ago(hours=2))
        }

        assert estimate(buy, never_scanned, content, prices, now).gp == 39_000_000

    def test_a_partially_unknown_basket_reports_what_it_knows_and_flags_it_low(
        self,
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        """§8.4's answer to a partly-known cost is to *qualify* it, not to hide it."""
        unpriced = Item(id="unpriced", name="Unpriced", item_id=5, price_mode="live")
        buy = candidate(
            "buy_a_set",
            kind="acquisition",
            completion={"all_of": [{"item": "voidwaker"}, {"item": "unpriced"}]},
        )
        content = build_content(items=[VOIDWAKER, unpriced], candidates=[buy])
        prices = {
            27690: price_record(item_id=27690, high_price_gp=39_000_000, high_trade_at=ago(hours=2))
        }

        result = estimate(buy, state(), content, prices, now)

        assert result.gp == 39_000_000
        assert result.confidence is Confidence.LOW
        assert result.price_selection_reason == (
            f"voidwaker: {REASON_RECENT_HIGH}; unpriced: {REASON_UNKNOWN}"
        )

    def test_training_cost_and_acquisition_cost_are_added_together(
        self,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        candidate: Callable[..., Candidate],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        train = candidate(
            "train_with_gear",
            kind="skill_training",
            completion={"all_of": [{"skill": {"magic": 94}}, {"item": "mystic_robe_top"}]},
        )
        content = build_content(methods=table, items=[MYSTIC_TOP], candidates=[train])
        player = state(
            skills={"magic": 87},
            xp={"magic": xp_for_level(87)},
            unlocks={"ancient_magicks": UnlockState.UNLOCKED},
        )
        prices = {
            4091: price_record(item_id=4091, high_price_gp=120_000, high_trade_at=ago(hours=2))
        }

        result = estimate(train, player, content, prices, now)

        assert result.hours is not None
        assert result.gp == round(result.hours * 400_000) + 120_000


class TestEstimateConfidenceIsTheMinimum:
    """§8.4 — *"the minimum across price confidence and training-method confidence"*.

    Tested in both directions because a ``max``, or either half taken alone, passes half
    of these. The pair is what pins the rule.
    """

    @pytest.fixture
    def buy_and_train(self, candidate: Callable[..., Candidate]) -> Candidate:
        return candidate(
            "train_with_gear",
            kind="skill_training",
            completion={"all_of": [{"skill": {"magic": 94}}, {"item": "voidwaker"}]},
        )

    def run(
        self,
        buy_and_train: Candidate,
        methods: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
        record: PriceRecord | None,
        now: datetime,
    ) -> Confidence:
        content = build_content(methods=methods, items=[VOIDWAKER], candidates=[buy_and_train])
        player = state(
            skills={"magic": 87},
            xp={"magic": xp_for_level(87)},
            unlocks={"ancient_magicks": UnlockState.UNLOCKED},
        )
        prices = {27690: record} if record is not None else {}
        return estimate(buy_and_train, player, content, prices, now).confidence

    def test_a_low_price_drags_a_fully_authored_training_plan_down(
        self,
        buy_and_train: Candidate,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
        now: datetime,
    ) -> None:
        """Method confidence ``high`` (every band authored), price confidence ``low``
        (nothing but the static hint) — the estimate is ``low``."""
        assert self.run(buy_and_train, table, build_content, state, None, now) is Confidence.LOW

    def test_a_fallback_band_drags_a_perfectly_fresh_price_down(
        self,
        buy_and_train: Candidate,
        method: Callable[..., TrainingMethod],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        """The mirror image: price confidence ``high``, one band with no authored method."""
        only_low_levels = (method("early", xp_per_hour=50_000, levels=(1, 88)),)
        fresh = price_record(item_id=27690, high_price_gp=39_000_000, high_trade_at=ago(hours=2))

        assert (
            self.run(buy_and_train, only_low_levels, build_content, state, fresh, now)
            is Confidence.LOW
        )

    def test_both_high_is_high(
        self,
        buy_and_train: Candidate,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        fresh = price_record(item_id=27690, high_price_gp=39_000_000, high_trade_at=ago(hours=2))
        assert self.run(buy_and_train, table, build_content, state, fresh, now) is Confidence.HIGH

    def test_a_medium_price_gives_a_medium_estimate(
        self,
        buy_and_train: Candidate,
        table: tuple[TrainingMethod, ...],
        build_content: Callable[..., Content],
        state: Callable[..., PlayerState],
        price_record: Callable[..., PriceRecord],
        ago: Callable[..., datetime],
        now: datetime,
    ) -> None:
        """The middle level exists because a cached price from yesterday is meaningfully
        better than a hand-authored fallback (§8.4) — and it has to survive the ``min``."""
        yesterday = price_record(item_id=27690, high_price_gp=39_000_000, high_trade_at=ago(days=3))
        assert (
            self.run(buy_and_train, table, build_content, state, yesterday, now)
            is Confidence.MEDIUM
        )


class TestAgainstTheShippedCorpus:
    """A smoke check that the synthetic shapes above are the real corpus's shapes."""

    def test_the_sdd_headline_estimate(
        self, seed_content: Content, state: Callable[..., PlayerState], now: datetime
    ) -> None:
        """*"Train Magic 87 → 94, ~N hours, ~M gp"* (§8), end to end through content."""
        train = seed_content.candidates["train_magic_87_to_94"]
        player = state(
            skills={"magic": 87},
            xp={"magic": xp_for_level(87)},
            unlocks={"ancient_magicks": UnlockState.UNLOCKED},
            quests={"desert_treasure_i": QuestStatus.COMPLETE},
        )

        result = estimate(train, player, seed_content, {}, now)

        assert result.hours == pytest.approx(
            (xp_for_level(94) - xp_for_level(87)) / 250_000, rel=1e-6
        )
        assert result.gp is not None and result.gp > 0
        assert result.confidence is Confidence.HIGH

    def test_buying_a_voidwaker_lands_on_the_static_hint_with_no_feed(
        self, seed_content: Content, state: Callable[..., PlayerState], now: datetime
    ) -> None:
        """The offline case: no price rows at all, so §8.3 walks to its last usable layer
        and the estimate is flagged ``low`` for it."""
        buy = seed_content.candidates["buy_voidwaker"]

        result = estimate(buy, state(scanned=False), seed_content, {}, now)

        assert result.gp == 85_000_000
        assert result.price_selection_reason == f"voidwaker: {REASON_STATIC_HINT}"
        assert result.confidence is Confidence.LOW
