from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.gear.combat import SPELLS
from tracker.gear.models import EquipmentDefinition
from tracker.gear.running_costs import SPELL_RECIPES, evaluate_running_cost, resource_item_ids

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def prices(**values):
    return {
        int(key): SimpleNamespace(
            high_price_gp=value,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source="live",
        )
        for key, value in values.items()
    }


def evaluate(spell="fire_strike", staff=1381, records=None, **performance):
    equipment = {"weapon": EquipmentDefinition(id=staff, name="Test staff", slot="weapon")}
    return evaluate_running_cost(
        equipment,
        {"attack_type": "magic", "spell": spell},
        {"supported": True, "attack_interval": 3, "dps": 2, **performance},
        records if records is not None else prices(**{"556": 5, "554": 4, "558": 3}),
        NOW,
    )


def test_all_current_spells_have_recipes():
    assert set(SPELL_RECIPES) == set(SPELLS)
    assert {556, 555, 557, 554, 558, 562, 560, 565, 21880} <= resource_item_ids()


def test_staff_removes_only_its_element_before_pricing():
    result = evaluate(records=prices(**{"554": 4, "558": 3}))
    assert result["status"] == "known"
    assert result["gp_per_attack"] == 15
    assert result["gp_per_hour"] == 18000
    assert result["gp_per_damage"] == 2.5
    air = next(row for row in result["resources"] if row["item_id"] == 556)
    assert air["consumed_quantity"] == 0
    assert air["supplied_quantity"] == 2
    assert air["supplied_by"] == "Test staff"


def test_combination_staff_supplies_both_elements():
    result = evaluate(staff=11998, records=prices(**{"558": 3}))
    assert result["gp_per_attack"] == 3


def test_missing_consumed_rune_price_is_not_free():
    result = evaluate(records={})
    assert result["status"] == "unavailable"
    assert result["gp_per_attack"] is None
    assert result["reasons"]


def test_zero_dps_keeps_attack_price_but_not_efficiency():
    result = evaluate(dps=0)
    assert result["gp_per_attack"] == 15
    assert result["gp_per_damage"] is None


def test_misses_do_not_reduce_rune_cost():
    assert evaluate(accuracy=0.1)["gp_per_attack"] == evaluate(accuracy=0.9)["gp_per_attack"]


def test_unknown_spell_and_powered_attack_fail_closed():
    assert evaluate(spell="unknown")["status"] == "unavailable"
    result = evaluate_running_cost(
        {},
        {"attack_type": "magic", "powered_attack": "fixture"},
        {"dps": 2, "attack_interval": 2.4},
        {},
        NOW,
    )
    assert result["gp_per_attack"] is None


def test_melee_is_zero_cost():
    result = evaluate_running_cost(
        {}, {"attack_type": "slash"}, {"dps": 2, "attack_interval": 2.4}, {}, NOW
    )
    assert result["gp_per_attack"] == result["gp_per_damage"] == 0


def test_reviewed_powered_recipe_includes_coins_and_ignores_staff_substitutions():
    equipment = {
        "weapon": EquipmentDefinition(
            id=11905, name="Trident of the seas", slot="weapon", powered_attack="trident"
        )
    }
    result = evaluate_running_cost(
        equipment,
        {"attack_type": "magic", "powered_attack": "trident"},
        {"dps": 2, "attack_interval": 2.4},
        prices(**{"554": 4, "562": 20, "560": 50}),
        NOW,
    )
    assert result["gp_per_attack"] == 100
    assert 995 in {r["item_id"] for r in result["resources"]}


@pytest.mark.parametrize(
    "cape,body_bonus,expected", [(None, 0, 10), (10499, 0, 2.8), (22109, 0, 2), (10499, -10, 10)]
)
def test_ranged_automatic_recovery(cape, body_bonus, expected):
    from tracker.gear.models import EquipmentBonuses

    equipment = {
        "weapon": EquipmentDefinition(
            id=841, name="Shortbow", slot="weapon", ammo_for=("arrow:882",)
        ),
        "ammunition": EquipmentDefinition(
            id=882, name="Bronze arrow", slot="ammunition", ammo_type="arrow:882"
        ),
        "body": EquipmentDefinition(
            id=1115, name="Iron platebody", slot="body", bonuses=EquipmentBonuses(ranged=body_bonus)
        ),
    }
    if cape:
        equipment["cape"] = EquipmentDefinition(id=cape, name="Ava device", slot="cape")
    result = evaluate_running_cost(
        equipment,
        {"attack_type": "ranged"},
        {"dps": 2, "attack_interval": 2.4},
        prices(**{"882": 10}),
        NOW,
    )
    assert result["gp_per_attack"] == pytest.approx(expected)


@pytest.mark.parametrize(
    "weapon_id,ammo_type,expected_type",
    [
        (806, None, "light"),
        (841, "arrow:882", "standard"),
        (9174, "bolt:877", "heavy"),
    ],
)
def test_real_eligible_ranged_options_have_costs(weapon_id, ammo_type, expected_type):
    from tracker.accounts.snapshot import AccountSnapshot
    from tracker.domain.types import SkillState, Source
    from tracker.gear.combat_options import eligible_combat_options

    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            "ranged": SkillState(50, None, Source.RUNELITE, NOW),
        },
    )
    weapon = EquipmentDefinition(
        id=weapon_id,
        name="Ranged weapon",
        slot="weapon",
        attack_profiles=(("ranged", "rapid"),),
        ammo_for=(ammo_type,) if ammo_type else (),
    )
    equipment = {"weapon": weapon}
    resource_id = weapon_id
    if ammo_type:
        resource_id = int(ammo_type.split(":")[1])
        equipment["ammunition"] = EquipmentDefinition(
            id=resource_id, name="Ammo", slot="ammunition", ammo_type=ammo_type
        )
    option = eligible_combat_options(weapon, snapshot, discipline="ranged", levels={})[0]
    assert option.attack_type == expected_type
    cost = evaluate_running_cost(
        equipment,
        option.model_dump(),
        {"dps": 2, "attack_interval": 2.4},
        prices(**{str(resource_id): 10}),
        NOW,
    )
    assert cost["status"] == "known"
    assert cost["gp_per_attack"] == 10
