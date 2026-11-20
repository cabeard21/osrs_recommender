"""Salve roll order and exact integer arithmetic for ordinary combat."""

import pytest

from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.prepared_combat import prepared_combat
from tracker.gear.ranged_numerics import ranged_experiment
from tracker.gear.scoring import prepare_equipment

from .test_revenant_combat import LEVELS, MASK, role_for


@pytest.mark.parametrize(
    "style,weapon_id,salve_id,variant,factor,maximum",
    [
        ("crush", 22545, 10588, 2, (6, 5), 39),
        ("ranged", 22550, 12017, 3, (7, 6), 36),
        ("ranged", 22550, 12018, 4, (6, 5), 37),
    ],
)
def test_salve_precedes_slayer_and_stacks_with_wilderness(
    style, weapon_id, salve_id, variant, factor, maximum
):
    weapon = EquipmentDefinition(
        id=weapon_id,
        name="Weapon",
        slot="weapon",
        attack_styles=(style,),
        bonuses=EquipmentBonuses(crush=53, melee_strength=66, ranged=70, ranged_strength=60),
    )
    amulet = EquipmentDefinition(id=salve_id, name="Salve amulet", slot="neck", salve_bonus=variant)
    role = role_for(style, True, task=True).model_copy(
        update={"target": CombatTarget(traits=("undead",))}
    )
    gear = [weapon, MASK, amulet]
    result = evaluate_loadout(gear, role, LEVELS)
    base = evaluate_loadout([weapon], role_for(style, False), LEVELS)
    assert result.max_hit == maximum
    assert result.attack_roll == base.attack_roll * factor[0] // factor[1] * 3 // 2
    assert result.salve_bonus.item_id == salve_id
    assert result.salve_bonus.suppresses_slayer
    assert not result.slayer_effects
    with prepared_combat(), ranged_experiment():
        score = evaluate_prepared_score(prepare_equipment(gear), role, LEVELS)
        assert (score.accuracy, score.dps) == (result.accuracy, result.dps)


@pytest.mark.parametrize("trait", ["undead", "spectral"])
def test_unimbued_salve_leaves_magic_mask_active(trait):
    role = role_for("magic", False, task=True).model_copy(
        update={"target": CombatTarget(traits=(trait,))}
    )
    salve = EquipmentDefinition(id=4081, name="Salve amulet", slot="neck", salve_bonus=1)
    assert evaluate_loadout([MASK, salve], role, LEVELS) == evaluate_loadout([MASK], role, LEVELS)


def test_magic_damage_is_additive_and_weakness_uses_base_roll():
    role = role_for("magic", False, task=True)
    role = role.model_copy(
        update={"target": role.target.model_copy(update={"traits": ("undead",)})}
    )
    staff = EquipmentDefinition(
        id=1, name="Staff", slot="weapon", bonuses=EquipmentBonuses(magic=20, magic_damage=20)
    )
    salve = EquipmentDefinition(id=12017, name="Salve amulet(i)", slot="neck", salve_bonus=3)
    result = evaluate_loadout([staff, salve, MASK], role, LEVELS)
    assert result.supported
    assert result.max_hit == 37  # 20 base, +20% equipment, +15% Salve and +10 weakness.
    base = 110 * 84
    assert result.attack_roll == base * 115 // 100 + base // 2
    assert result.salve_bonus.damage_percent == 15
    assert not result.slayer_effects


def test_hunter_spear_uses_melee_strength_for_damage_only():
    role = role_for("ranged", False, task=True).model_copy(
        update={"target": CombatTarget(traits=("undead",))}
    )
    spear = EquipmentDefinition(
        id=29305,
        name="Hunter's spear",
        slot="weapon",
        attack_styles=("ranged",),
        bonuses=EquipmentBonuses(ranged=40, melee_strength=48),
    )
    salve = EquipmentDefinition(id=10588, name="Salve amulet (e)", slot="neck", salve_bonus=2)
    levels = {**LEVELS, "strength": 65}
    gear = [spear, salve, MASK]
    result = evaluate_loadout(gear, role, levels)
    assert result.supported
    assert result.max_hit == 13 * 6 // 5
    assert result.attack_roll == 107 * 104 * 23 // 20
    assert result.salve_bonus.accuracy_percent == 0
    assert result.salve_bonus.suppresses_slayer
    assert result.slayer_effects[0].damage_numerator == result.slayer_effects[0].denominator
    for equipment in (gear, [spear]):
        expected = evaluate_loadout(equipment, role, levels)
        with prepared_combat():
            prepared = evaluate_prepared_score(prepare_equipment(equipment), role, levels)
        with ranged_experiment():
            cached = evaluate_prepared_score(prepare_equipment(equipment), role, levels)
        assert prepared == cached
        assert (prepared.accuracy, prepared.dps) == (expected.accuracy, expected.dps)
