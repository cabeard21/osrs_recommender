"""Ancient spells consume one reviewed rune recipe per cast."""

import pytest

from tests.gear.test_running_costs import evaluate, prices
from tracker.gear.running_costs import SPELL_RECIPES, resource_item_ids

# OSRS Wiki: Ancient Magicks / individual spell pages. Rune IDs are physical.
RECIPES = {
    "smoke_rush": {554: 1, 556: 1, 562: 2, 560: 2},
    "shadow_rush": {556: 1, 566: 1, 562: 2, 560: 2},
    "blood_rush": {565: 1, 562: 2, 560: 2},
    "ice_rush": {555: 2, 562: 2, 560: 2},
    "smoke_burst": {554: 2, 556: 2, 562: 4, 560: 2},
    "shadow_burst": {556: 1, 566: 2, 562: 4, 560: 2},
    "blood_burst": {565: 2, 562: 4, 560: 2},
    "ice_burst": {555: 4, 562: 4, 560: 2},
    "smoke_blitz": {554: 2, 556: 2, 565: 2, 560: 2},
    "shadow_blitz": {556: 2, 566: 2, 565: 2, 560: 2},
    "blood_blitz": {565: 4, 560: 2},
    "ice_blitz": {555: 3, 565: 2, 560: 2},
    "smoke_barrage": {554: 4, 556: 4, 565: 2, 560: 4},
    "shadow_barrage": {556: 4, 566: 3, 565: 2, 560: 4},
    "blood_barrage": {565: 4, 560: 4, 566: 1},
    "ice_barrage": {555: 6, 565: 2, 560: 4},
}


@pytest.mark.parametrize("spell,recipe", RECIPES.items())
def test_ancient_spell_costs_each_required_rune_once_per_cast(spell, recipe):
    records = prices(**{str(rune): rune for rune in recipe})
    result = evaluate(spell=spell, staff=4675, records=records)
    assert result["status"] == "known"
    assert dict(SPELL_RECIPES[spell]) == recipe
    assert {row["item_id"]: row["consumed_quantity"] for row in result["resources"]} == recipe
    assert result["gp_per_attack"] == sum(rune * quantity for rune, quantity in recipe.items())
    assert result["gp_per_hour"] == pytest.approx(result["gp_per_attack"] * 1200)


def test_soul_rune_is_in_market_scope_and_has_its_name():
    assert 566 in resource_item_ids()
    result = evaluate(
        spell="blood_barrage", staff=4675, records=prices(**{"565": 2, "560": 3, "566": 5})
    )
    soul = next(row for row in result["resources"] if row["item_id"] == 566)
    assert soul["name"] == "Soul rune"
    assert soul["consumed_quantity"] == 1


def test_missing_soul_price_does_not_make_ancient_spell_free():
    result = evaluate(spell="blood_barrage", staff=4675, records=prices(**{"565": 2, "560": 3}))
    assert result["status"] == "unavailable"
    assert result["gp_per_attack"] is None
