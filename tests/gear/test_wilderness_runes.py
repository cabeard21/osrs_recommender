from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tracker.gear.models import EquipmentDefinition, TomeEffect
from tracker.gear.wilderness import DeathItem, WildernessPolicy, WildernessRisk
from tracker.gear.wilderness_runes import wilderness_spell_runes
from tracker.integrations.prices.client import PriceDTO, PriceSource


def test_spell_casts_are_optional_with_a_strict_positive_bound():
    assert "spell_casts" not in WildernessPolicy(spell_casts=None).model_dump()
    assert WildernessPolicy(spell_casts=10_000).model_dump()["spell_casts"] == 10_000
    for invalid in (0, 10_001, "100", 100.0, True):
        with pytest.raises(ValidationError, match="spell_casts"):
            WildernessPolicy.model_validate({"spell_casts": invalid})


def test_spell_runes_are_shared_stacks_across_resolved_magic_roles():
    staff_id = 1387
    tome_id = 25574
    items = {
        staff_id: EquipmentDefinition(id=staff_id, name="Staff of fire", slot="weapon"),
        tome_id: EquipmentDefinition(
            id=tome_id,
            name="Tome of water",
            slot="shield",
            tome_effect=TomeEffect(element="water", rune_id=555),
        ),
    }
    loadouts = {
        "standard": {"weapon": staff_id, "shield": tome_id},
        "ancient": {"shield": tome_id},
        "powered": {},
        "melee": {},
        "special": {},
    }
    options = {
        "standard": {"attack_type": "magic", "spell": "fire_blast"},
        "ancient": {"attack_type": "magic", "spell": "ice_burst"},
        "powered": {"attack_type": "magic", "powered_attack": "warped_sceptre"},
        "melee": {"attack_type": "stab"},
        "special": None,
    }
    assert wilderness_spell_runes(loadouts, options, items, 3) == {556: 12, 560: 9, 562: 12}
    assert wilderness_spell_runes(loadouts, options, items, None) == {}
    assert (
        wilderness_spell_runes(
            loadouts, options | {"standard": {"attack_type": "magic", "spell": "unknown"}}, items, 3
        )
        is None
    )


def test_exact_lost_runes_are_budgeted_before_ammo_quantity():
    risk = WildernessRisk(
        WildernessPolicy(skulled=True, spell_casts=10),
        100,
        {1: DeathItem(1000, 10, ammo=True)},
        rune_rules={554: DeathItem(1, 7, ammo=True)},
    )
    runes = {554: 10}
    assert risk.rune_partial_feasible({1}, runes)
    assert risk.rune_feasible({1}, runes)
    assert not risk.rune_feasible({1}, {554: 13})
    result = risk.report({"base": {"ammunition": 1}}, runes=runes)
    assert result["loss_gp"] == 100
    assert result["quantities"] == [
        {"item_id": 554, "resource_id": 554, "kind": "rune", "quantity": 10},
        {"item_id": 1, "resource_id": 1, "kind": "ammo", "quantity": 3},
    ]
    assert {"item_id": 554, "outcome": "dropped", "loss_gp": 70, "quantity": 10} in result["items"]


def test_fixed_runes_can_take_a_keep_slot_when_the_resulting_loss_fits():
    risk = WildernessRisk(
        WildernessPolicy(skulled=True, protect_item=True, spell_casts=10),
        100,
        {1: DeathItem(50, 50), 2: DeathItem(200, 200)},
        rune_rules={554: DeathItem(10, 3, ammo=True)},
    )
    assert risk.rune_partial_feasible({1}, {554: 10})
    assert risk.rune_feasible({1}, {554: 10})
    report = risk.report({"base": {"weapon": 1}}, runes={554: 10})
    assert report["loss_gp"] == 50
    assert {"item_id": 1, "outcome": "dropped", "loss_gp": 50, "quantity": 1} in report["items"]
    assert risk.rune_feasible({1, 2}, {554: 10})


def test_auto_ammo_does_not_displace_the_protection_set_after_fixed_runes():
    risk = WildernessRisk(
        WildernessPolicy(skulled=True, protect_item=True, spell_casts=10),
        1000,
        {1: DeathItem(50, 50), 2: DeathItem(20, 1, ammo=True)},
        rune_rules={554: DeathItem(10, 3, ammo=True)},
    )
    assert risk.rune_feasible({1, 2}, {554: 10})
    report = risk.report({"base": {"weapon": 1, "ammunition": 2}}, runes={554: 10})
    assert report["loss_gp"] == 54
    assert report["quantities"] == [
        {"item_id": 554, "resource_id": 554, "kind": "rune", "quantity": 10},
        {"item_id": 2, "resource_id": 2, "kind": "ammo", "quantity": 4},
    ]


def test_fixed_runes_can_make_a_gear_only_ammo_displacement_irrelevant():
    risk = WildernessRisk(
        WildernessPolicy(skulled=True, protect_item=True, spell_casts=1),
        100,
        {1: DeathItem(10, 10), 2: DeathItem(20, 20, ammo=True)},
        rune_rules={554: DeathItem(30, 30, ammo=True)},
    )
    assert not risk.feasible({1, 2})
    assert risk.rune_partial_feasible({1, 2}, {554: 1})
    assert risk.rune_feasible({1, 2}, {554: 1})
    result = risk.report({"base": {"body": 1, "ammunition": 2}}, runes={554: 1})
    assert result["loss_gp"] == 30
    assert result["quantities"][-1]["quantity"] == 1


def test_prayer_off_counterfactual_preserves_the_requested_cast_stack():
    risk = WildernessRisk(
        WildernessPolicy(skulled=True, protect_item=True, spell_casts=10),
        100,
        {1: DeathItem(300, 300)},
        rune_rules={554: DeathItem(10, 7, ammo=True)},
    )
    result = risk.report({"base": {"weapon": 1}}, runes={554: 10})
    assert result["loss_gp"] == 70
    assert result["without_protect_item_gp"] == 370


def test_missing_rune_price_or_recipe_cannot_be_counted_as_free():
    risk = WildernessRisk(
        WildernessPolicy(spell_casts=10), 100, {}, rune_rules={554: DeathItem(1, None, ammo=True)}
    )
    assert not risk.rune_partial_feasible(set(), {554: 10})
    assert not risk.rune_feasible(set(), {554: 10})
    assert risk.report({}, runes={554: 10})["loss_gp"] is None
    assert not risk.rune_feasible(set(), None)
    assert risk.report({}, runes=None)["loss_gp"] is None


def test_cached_rune_price_is_loaded_even_without_an_equipped_catalog_row():
    now = datetime(2026, 11, 18, tzinfo=UTC)
    price = PriceDTO(
        item_id=554,
        high_price_gp=5,
        high_trade_at=now,
        low_price_gp=None,
        low_trade_at=None,
        provider="osrs_wiki",
        fetched_at=now,
        source=PriceSource.LIVE,
    )
    risk = WildernessRisk.build(
        WildernessPolicy(skulled=True, spell_casts=5), 25, {}, {}, {554: price}, now
    )
    assert risk.rune_feasible(set(), {554: 5})
    assert risk.report({}, runes={554: 5})["loss_gp"] == 25
