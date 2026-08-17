"""§23.4's selection rule, and the honesty invariants it exists to hold.

The rule itself is short. What is worth testing is the set of things it must *refuse* to
say: that an unknown gate means yes, that an unseen bank means no, and that a partial sum
is a total. Each is a plausible simplification that would make the code shorter and the
advice wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tracker.content.loader import Content
from tracker.content.schema import Item
from tracker.domain.types import Container, PlayerState, QuestStatus, Tri
from tracker.gear.setup import SetupSlot, gear_progress


def _slot(
    content: Content, state: PlayerState, style: str = "melee", slot: str = "weapon"
) -> SetupSlot:
    setup = gear_progress(state, content).setup(style)
    assert setup is not None
    return next(plan for plan in setup.slots if plan.slot == slot)


class TestTheRecommendation:
    """``recommended`` is the highest rung whose gate is *satisfied* — not the highest rung."""

    def test_it_stops_at_the_level_the_account_has(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        content = make_content(
            items=[
                make_item("rune_scimitar", tier=1, requires={"skill": {"attack": 40}}),
                make_item("dragon_scimitar", tier=2, requires={"skill": {"attack": 60}}),
                make_item("abyssal_whip", tier=3, requires={"skill": {"attack": 70}}),
            ]
        )
        plan = _slot(content, make_player_state(levels={"attack": 60}))

        assert plan.recommended is not None
        assert plan.recommended.item_id == "dragon_scimitar"
        assert plan.next_rung is not None
        assert plan.next_rung.item_id == "abyssal_whip"
        assert plan.next_rung.fit is Tri.UNSATISFIED

    def test_an_unknown_gate_never_promotes(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """The load-bearing one.

        A quest nobody has observed is *unknown*, and treating unknown as satisfied is the
        §4.5 conversion this whole design forbids: it produces the sentence *"you can wear
        this"* from no evidence at all. §10.6 lets an unknown gate not *block* a candidate,
        which is the same principle at the opposite polarity — see the module note in
        ``tracker/gear/setup.py``.
        """
        content = make_content(
            items=[
                make_item("rune_scimitar", tier=1, requires={"skill": {"attack": 40}}),
                make_item("dragon_scimitar", tier=2, requires={"quest": "monkey_madness_i"}),
            ],
            quests={"monkey_madness_i": "Monkey Madness I"},
        )
        plan = _slot(content, make_player_state(levels={"attack": 99}))

        assert plan.recommended is not None
        assert plan.recommended.item_id == "rune_scimitar"
        assert plan.aspirational[0].item_id == "dragon_scimitar"
        assert plan.aspirational[0].fit is Tri.UNKNOWN

    def test_an_observed_quest_does_promote(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """The other half: unknown is withheld for want of evidence, not on principle."""
        content = make_content(
            items=[
                make_item("rune_scimitar", tier=1),
                make_item("dragon_scimitar", tier=2, requires={"quest": "monkey_madness_i"}),
            ],
            quests={"monkey_madness_i": "Monkey Madness I"},
        )
        state = make_player_state(quests={"monkey_madness_i": QuestStatus.COMPLETE})

        plan = _slot(content, state)
        assert plan.recommended is not None
        assert plan.recommended.item_id == "dragon_scimitar"

    def test_an_untranscribed_gate_is_unknown_and_says_which_kind(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """A gap in the corpus is not a gap in the account, and the advice differs.

        One says *sync your account*; the other says *nobody wrote this requirement down*.
        Telling a player to log in and refresh when the tracker is what is missing wastes
        their time, so the two carry different flags even though both read as UNKNOWN.
        """
        content = make_content(
            items=[
                make_item("rune_scimitar", tier=1),
                make_item("ultor_ring", tier=2, gate_unknown=True),
            ]
        )
        plan = _slot(content, make_player_state())

        assert plan.recommended is not None
        assert plan.recommended.item_id == "rune_scimitar"
        assert plan.aspirational[0].fit is Tri.UNKNOWN
        assert plan.aspirational[0].gate_unknown is True

    def test_an_ungated_ladder_recommends_its_top_rung(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        content = make_content(
            items=[make_item("black_cape", tier=1), make_item("fire_cape", tier=2)]
        )
        plan = _slot(content, make_player_state())

        assert plan.recommended is not None
        assert plan.recommended.item_id == "fire_cape"
        assert plan.next_rung is None


class TestOwnershipIsSeparateFromFit:
    """Two questions, two answers. Collapsing them loses the case that needs saying."""

    def test_holding_a_rung_it_cannot_wear_reports_both(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """Silently taking the higher would hide a corpus bug behind a plausible answer."""
        content = make_content(
            items=[
                make_item("rune_scimitar", numeric_id=1333, tier=1),
                make_item(
                    "abyssal_whip", numeric_id=4151, tier=2, requires={"skill": {"attack": 70}}
                ),
            ]
        )
        plan = _slot(content, make_player_state(levels={"attack": 40}, holds=[4151]))

        assert plan.recommended is not None
        assert plan.recommended.item_id == "rune_scimitar"
        assert plan.best_held is not None
        assert plan.best_held.item_id == "abyssal_whip"
        assert plan.holds_what_it_cannot_wear is True

    def test_any_variant_id_counts_as_holding_it(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """§10.5: a charged blowpipe is a blowpipe. Matching ``item_id`` alone is the bug."""
        content = make_content(
            items=[make_item("toxic_blowpipe", numeric_id=12926, variant_item_ids=(12924,), tier=1)]
        )
        plan = _slot(content, make_player_state(holds=[12924]))

        assert plan.best_held is not None
        assert plan.best_held.held is Tri.SATISFIED


class TestFourFiveHonesty:
    """Absence is only evidence once every container has been looked in."""

    def test_an_unscanned_account_is_unknown_not_empty(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        content = make_content(items=[make_item("rune_scimitar", numeric_id=1333, tier=1)])
        plan = _slot(content, make_player_state())

        assert plan.certain is False
        assert plan.recommended is not None
        assert plan.recommended.held is Tri.UNKNOWN

    def test_a_bank_scan_alone_is_not_enough(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """They could be wearing it. The equipment slot has never been looked at."""
        content = make_content(items=[make_item("rune_scimitar", numeric_id=1333, tier=1)])
        plan = _slot(content, make_player_state(scanned=[Container.BANK]))

        assert plan.recommended is not None
        assert plan.recommended.held is Tri.UNKNOWN

    def test_every_container_scanned_makes_absence_evidence(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
        every_container: tuple[Container, ...],
    ) -> None:
        content = make_content(items=[make_item("rune_scimitar", numeric_id=1333, tier=1)])
        plan = _slot(content, make_player_state(scanned=every_container))

        assert plan.certain is True
        assert plan.recommended is not None
        assert plan.recommended.held is Tri.UNSATISFIED


class TestPricing:
    """A missing price is missing, and a total is a total or it is nothing."""

    def test_the_total_is_what_the_recommended_setup_still_costs(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
        every_container: tuple[Container, ...],
    ) -> None:
        content = make_content(
            items=[
                make_item("dragon_scimitar", numeric_id=4587, tier=1, slot="weapon"),
                make_item("dragon_boots", numeric_id=11840, tier=1, slot="feet"),
            ]
        )
        state = make_player_state(scanned=every_container)
        prices: dict[int, Any] = {4587: 15_000, 11840: 9_000}

        setup = gear_progress(state, content, prices=prices).setup("melee")
        assert setup is not None
        assert setup.to_complete_gp == 24_000

    def test_a_piece_already_held_is_not_charged_for(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
        every_container: tuple[Container, ...],
    ) -> None:
        content = make_content(
            items=[
                make_item("dragon_scimitar", numeric_id=4587, tier=1, slot="weapon"),
                make_item("dragon_boots", numeric_id=11840, tier=1, slot="feet"),
            ]
        )
        state = make_player_state(scanned=every_container, holds=[11840])
        prices: dict[int, Any] = {4587: 15_000, 11840: 9_000}

        setup = gear_progress(state, content, prices=prices).setup("melee")
        assert setup is not None
        assert [pick.item_id for pick in setup.missing] == ["dragon_scimitar"]
        assert setup.to_complete_gp == 15_000

    def test_one_absent_price_makes_the_total_unknown(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
        every_container: tuple[Container, ...],
    ) -> None:
        """Not a partial sum. It would read as *the* cost and understate it silently."""
        content = make_content(
            items=[
                make_item("dragon_scimitar", numeric_id=4587, tier=1, slot="weapon"),
                make_item("dragon_boots", numeric_id=11840, tier=1, slot="feet"),
            ]
        )
        state = make_player_state(scanned=every_container)

        setup = gear_progress(state, content, prices={4587: 15_000}).setup("melee")
        assert setup is not None
        assert setup.to_complete_gp is None

    def test_an_uncached_price_is_none_and_never_zero(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        content = make_content(items=[make_item("rune_scimitar", numeric_id=1333, tier=1)])
        plan = _slot(content, make_player_state())

        assert plan.recommended is not None
        assert plan.recommended.price_gp is None


class TestDeterminism:
    """§22.3 hashes the rendering of this, so two runs must not disagree."""

    def test_two_runs_over_the_same_inputs_are_identical(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        content = make_content(
            items=[
                make_item("rune_scimitar", tier=1),
                make_item("abyssal_whip", tier=2, requires={"skill": {"attack": 70}}),
                make_item("rune_boots", tier=1, slot="feet"),
                make_item("masori_body", tier=1, slot="body", style="ranged"),
            ]
        )
        state = make_player_state(levels={"attack": 70})

        assert gear_progress(state, content) == gear_progress(state, content)

    def test_styles_come_back_in_a_fixed_order(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        content = make_content(
            items=[
                make_item("kodai_wand", tier=1, style="magic"),
                make_item("twisted_bow", tier=1, style="ranged"),
                make_item("abyssal_whip", tier=1, style="melee"),
            ]
        )
        progress = gear_progress(make_player_state(), content)

        assert [setup.style for setup in progress.setups] == ["melee", "ranged", "magic"]


class TestAcquisition:
    """§23.2's second axis: whether a rung can be *got*, not merely worn.

    The bug this closed said an Infernal cape was the best a melee account could equip. It
    was true — the cape's whole wear gate is 40 Defence — and the page had no way to add the
    part that mattered, which is that no amount of gp buys one.
    """

    def test_a_rung_it_cannot_buy_is_not_the_recommendation(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """The reported bug, in three items."""
        content = make_content(
            items=[
                make_item("black_cape", tier=1, slot="cape"),
                make_item(
                    "fire_cape",
                    tier=2,
                    slot="cape",
                    acquisition="untradeable",
                    acquired_from="the Fight Caves",
                ),
                make_item(
                    "infernal_cape",
                    tier=3,
                    slot="cape",
                    acquisition="untradeable",
                    acquired_from="the Inferno",
                ),
            ]
        )
        plan = _slot(content, make_player_state(), slot="cape")

        assert plan.recommended is not None
        assert plan.recommended.item_id == "black_cape"
        # Its gate is met — the axis that stopped it is acquisition and nothing else.
        assert plan.aspirational[0].fit is Tri.SATISFIED
        assert plan.aspirational[0].obtainable is Tri.UNSATISFIED

    def test_the_earn_target_is_the_lowest_such_rung_and_not_the_highest(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """An account with no cape is served by the Fight Caves, not by the Inferno."""
        content = make_content(
            items=[
                make_item("black_cape", tier=1, slot="cape"),
                make_item(
                    "fire_cape",
                    tier=2,
                    slot="cape",
                    acquisition="untradeable",
                    acquired_from="the Fight Caves",
                ),
                make_item(
                    "infernal_cape",
                    tier=3,
                    slot="cape",
                    acquisition="untradeable",
                    acquired_from="the Inferno",
                ),
            ]
        )
        plan = _slot(content, make_player_state(), slot="cape")

        assert plan.earn is not None
        assert plan.earn.item_id == "fire_cape"
        assert plan.earn.acquired_from == "the Fight Caves"

    def test_holding_it_makes_it_the_recommendation_again(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
        every_container: tuple[Container, ...],
    ) -> None:
        """*Wear the one you own* is the most actionable sentence the page has.

        How a piece is acquired is a settled question once it is in the bank, so ownership
        is tested before the corpus is consulted. Without that branch the player who went and
        beat the Inferno would be told to put a black cape back on.
        """
        content = make_content(
            items=[
                make_item("black_cape", tier=1, slot="cape", numeric_id=1019),
                make_item(
                    "infernal_cape",
                    tier=2,
                    slot="cape",
                    numeric_id=21295,
                    acquisition="untradeable",
                    acquired_from="the Inferno",
                ),
            ]
        )
        state = make_player_state(holds=[21295], scanned=every_container)
        plan = _slot(content, state, slot="cape")

        assert plan.recommended is not None
        assert plan.recommended.item_id == "infernal_cape"
        assert plan.recommended.obtainable is Tri.SATISFIED
        assert plan.earn is None

    def test_an_unknown_acquisition_does_not_demote(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """The load-bearing one, and the deliberate opposite of the unknown-gate rule.

        An unknown *gate* does not promote, because asserting a capability from no evidence
        is the §4.5 conversion. An unknown *acquisition* does not demote, because it has no
        player-side remedy: withholding a rung the account can wear punishes them for a hole
        in the corpus and offers them nothing to do about it.
        """
        content = make_content(
            items=[
                make_item("black_cape", tier=1, slot="cape"),
                make_item("mystery_cape", tier=2, slot="cape", acquisition=None),
            ]
        )
        plan = _slot(content, make_player_state(), slot="cape")

        assert plan.recommended is not None
        assert plan.recommended.item_id == "mystery_cape"
        assert plan.recommended.obtainable is Tri.UNKNOWN
        assert plan.earn is None

    def test_an_untradeable_piece_never_reaches_the_bill(
        self,
        make_item: Callable[..., Item],
        make_content: Callable[..., Content],
        make_player_state: Callable[..., PlayerState],
    ) -> None:
        """And it gets there from the selection rule rather than from a filter of its own.

        A cached price against an untradeable piece is not hypothetical — the corpus carries
        one for the Avernic defender, where the figure is really its hilt. The total must not
        absorb it.
        """
        content = make_content(
            items=[
                make_item("black_cape", tier=1, slot="cape", numeric_id=1019),
                make_item(
                    "infernal_cape",
                    tier=2,
                    slot="cape",
                    numeric_id=21295,
                    acquisition="untradeable",
                    acquired_from="the Inferno",
                ),
            ]
        )
        prices = {1019: 1_000, 21295: 999_000_000}
        setup = gear_progress(make_player_state(), content, prices=prices).setup("melee")

        assert setup is not None
        assert [pick.item_id for pick in setup.missing] == ["black_cape"]
        assert setup.to_complete_gp == 1_000
