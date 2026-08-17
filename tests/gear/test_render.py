"""§23.4's markdown, at the place it can mislead the model reading it.

The renderer is not merely formatting: it is the whole of what §22's ``get_gear_setup``
returns, so a line that reads as a distinction becomes a distinction the advisor repeats to
the user. These are about a *restatement* being mistaken for new information.
"""

from __future__ import annotations

from tracker.domain.types import Tri
from tracker.gear.render import render_setup
from tracker.gear.setup import GearPick, GearSetup, SetupSlot


def pick(item_id: str, name: str, tier: int, *, held: Tri = Tri.SATISFIED) -> GearPick:
    return GearPick(item_id=item_id, name=name, tier=tier, fit=Tri.SATISFIED, held=held)


def one_slot(slot: SetupSlot) -> str:
    return render_setup(GearSetup(style="melee", slots=(slot,)))


class TestTheHoldingLine:
    def test_the_same_rung_is_not_spelled_out_twice(self) -> None:
        """Two identical lines spend the result's budget saying one thing."""
        gloves = pick("leather_gloves", "Leather gloves", 1)
        body = one_slot(
            SetupSlot(
                style="melee", slot="hands", ladder_size=3, recommended=gloves, best_held=gloves
            )
        )
        assert body.count("Leather gloves") == 1
        assert "- holding: the same rung" in body

    def test_a_different_rung_held_is_still_named_in_full(self) -> None:
        """The collapse must not swallow the case the section exists to show."""
        body = one_slot(
            SetupSlot(
                style="melee",
                slot="feet",
                ladder_size=5,
                recommended=pick("rune_boots", "Rune boots", 2, held=Tri.UNSATISFIED),
                best_held=pick("leather_boots", "Leather boots", 1),
            )
        )
        assert "- best you can equip: Rune boots" in body
        assert "- holding: Leather boots" in body
        assert "the same rung" not in body

    def test_nothing_seen_still_says_so(self) -> None:
        """``best_held is None`` must not be dragged into the same-rung branch."""
        body = one_slot(
            SetupSlot(
                style="melee",
                slot="cape",
                ladder_size=2,
                recommended=pick("team_cape", "Team cape", 1, held=Tri.UNSATISFIED),
            )
        )
        assert "- holding: nothing on this ladder has been seen" in body


class TestAcquisitionIsRenderedAsAFactAndNotAsAPrice:
    """§23.5: a piece the market does not sell carries what wins it, never a gp figure."""

    def test_an_untradeable_rung_names_its_content_and_quotes_no_price(self) -> None:
        """A cached price on an untradeable piece is not hypothetical — the corpus holds one
        for the Avernic defender, where the figure is really its hilt — and a gp label beside
        something nobody can buy invites a purchase that cannot be made."""
        body = one_slot(
            SetupSlot(
                style="melee",
                slot="cape",
                ladder_size=2,
                recommended=pick("black_cape", "Black cape", 1),
                earn=GearPick(
                    item_id="infernal_cape",
                    name="Infernal cape",
                    tier=2,
                    fit=Tri.SATISFIED,
                    held=Tri.UNSATISFIED,
                    obtainable=Tri.UNSATISFIED,
                    acquired_from="the Inferno",
                    price_gp=999_000_000,
                ),
            )
        )

        assert "cannot be bought — earned from the Inferno" in body
        assert "999,000,000" not in body

    def test_the_bill_says_what_it_left_out_and_why(self) -> None:
        """An absence and a stated absence are different claims (§4.5).

        A model reading a bill with no cape in it has two ways to explain the gap, and one of
        them is to price the cape from its own knowledge of the game.
        """
        body = one_slot(
            SetupSlot(
                style="melee",
                slot="cape",
                ladder_size=2,
                recommended=pick("black_cape", "Black cape", 1),
                earn=GearPick(
                    item_id="fire_cape",
                    name="Fire cape",
                    tier=2,
                    fit=Tri.SATISFIED,
                    held=Tri.UNSATISFIED,
                    obtainable=Tri.UNSATISFIED,
                    acquired_from="the Fight Caves",
                ),
            )
        )

        assert "Not in that figure: Fire cape (the Fight Caves)" in body

    def test_a_tradeable_rung_says_nothing_about_acquisition(self) -> None:
        """An answer of *yes* earns no space in a bounded result."""
        body = one_slot(
            SetupSlot(
                style="melee",
                slot="cape",
                ladder_size=1,
                recommended=GearPick(
                    item_id="black_cape",
                    name="Black cape",
                    tier=1,
                    fit=Tri.SATISFIED,
                    held=Tri.SATISFIED,
                    obtainable=Tri.SATISFIED,
                ),
            )
        )

        assert "cannot be bought" not in body
        assert "Not in that figure" not in body
