"""Exact dragonbane arithmetic, including task and elemental ordering."""

from types import SimpleNamespace

import pytest

from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.scoring import prepare_equipment

LEVELS = dict.fromkeys(("attack", "strength", "ranged", "magic", "defence", "slayer"), 99)
MASK = EquipmentDefinition(id=11865, name="Mask", slot="head", slayer_bonus="all")


def weapon(item_id, style):
    return EquipmentDefinition(
        id=item_id,
        name="Fixture",
        slot="weapon",
        attack_speed=4,
        attack_styles=(style,),
        spell_compatibility=("fire_wave", "water_wave", "ice_barrage"),
        bonuses=EquipmentBonuses(
            stab=85,
            crush=31,
            ranged=95,
            ranged_strength=100,
            melee_strength=70,
            magic=16,
            magic_damage=10,
        ),
    )


def role(style, *, dragon=True, task=False, spell="fire_wave", **target):
    return SimpleNamespace(
        style=style,
        stance="accurate",
        spell=spell,
        on_slayer_task=task,
        target=CombatTarget(traits=("dragon",) if dragon else (), **target),
    )


@pytest.mark.parametrize(
    "item_id,style,accuracy,damage",
    [
        (22978, "stab", 20, 20),
        (21012, "ranged", 30, 25),
        (25916, "ranged", 30, 25),
        (25918, "ranged", 30, 25),
        (30070, "crush", 75, 40),
    ],
)
@pytest.mark.parametrize("task", [False, True])
def test_physical_bonus_and_task_order(item_id, style, accuracy, damage, task):
    item = weapon(item_id, style)
    baseline = evaluate_loadout([item], role(style, dragon=False), LEVELS)
    actual = evaluate_loadout([item, MASK], role(style, task=task), LEVELS)
    maximum = baseline.max_hit
    attack = baseline.attack_roll
    if task:
        maximum = maximum * (23 if style == "ranged" else 7) // (20 if style == "ranged" else 6)
        attack = attack * (23 if style == "ranged" else 7) // (20 if style == "ranged" else 6)
    expected = (
        baseline.max_hit * 140 // 100
        if task and style == "ranged"
        else maximum * (100 + damage) // 100
    )
    assert actual.supported
    assert actual.max_hit == expected
    assert actual.attack_roll == attack * (100 + accuracy) // 100
    assert actual.dragonbane_bonus.damage_percent == damage
    assert actual.dragonbane_bonus.slayer_damage_additive is (task and style == "ranged")


@pytest.mark.parametrize("task", [False, True])
@pytest.mark.parametrize("element,tome_id", [("fire", 20714), ("water", 25574)])
def test_magic_weakness_is_added_after_dragonbane(task, element, tome_id):
    item = weapon(30070, "magic")
    tome = EquipmentDefinition(
        id=tome_id,
        name="Tome",
        slot="shield",
        tome_effect={"element": element, "rune_id": 554 if element == "fire" else 555},
    )
    configured = role(
        "magic", task=task, spell=element + "_wave", weakness_element=element, weakness_percent=50
    )
    actual = evaluate_loadout([item, MASK, tome], configured, LEVELS)
    base = 20
    maximum = base * 110 // 100
    attack_base = (99 + 9 + 2) * (16 + 64)
    attack = attack_base * 175 // 100
    if task:
        maximum = maximum * 23 // 20
        attack = attack * 23 // 20
    maximum = maximum * 140 // 100
    if element == "water":
        attack = attack * 120 // 100
    assert actual.max_hit == (maximum + base * 50 // 100) * 110 // 100
    assert actual.attack_roll == attack + attack_base * 50 // 100
    assert actual.attack_interval == 3
    score = evaluate_prepared_score(prepare_equipment([item, MASK, tome]), configured, LEVELS)
    assert score.dps == actual.dps


@pytest.mark.parametrize("item_id,style", [(22978, "stab"), (21012, "ranged"), (30070, "magic")])
def test_non_dragon_control_and_score_agreement(item_id, style):
    item = weapon(item_id, style)
    configured = role(style, dragon=False)
    actual = evaluate_loadout([item], configured, LEVELS)
    assert actual.supported
    assert actual.dragonbane_bonus is None
    score = evaluate_prepared_score(prepare_equipment([item]), configured, LEVELS)
    assert score.dps == actual.dps


@pytest.mark.parametrize("style,item_id", [("stab", 22978), ("ranged", 21012), ("magic", 30070)])
def test_cache_contexts_preserve_target_specific_bonus(style, item_id):
    from tracker.gear.prepared_combat import prepared_combat
    from tracker.gear.ranged_numerics import ranged_experiment

    item = weapon(item_id, style)
    dragon = role(style)
    ordinary = role(style, dragon=False)
    expected = [evaluate_loadout([item], r, LEVELS) for r in (ordinary, dragon)]
    with prepared_combat(), ranged_experiment(capacity=8):
        for configured, reference in zip(
            (ordinary, dragon, ordinary, dragon), expected * 2, strict=True
        ):
            actual = evaluate_loadout([item], configured, LEVELS)
            score = evaluate_prepared_score(prepare_equipment([item]), configured, LEVELS)
            assert actual == reference
            assert score.dps == reference.dps


def test_ruby_proc_is_not_scaled_by_dragonbane():
    item = weapon(21012, "ranged").model_copy(update={"ammo_for": ("bolt:21944",)})
    ammo = EquipmentDefinition(
        id=21944, name="Ruby", slot="ammunition", ammo_type="bolt:21944", bolt_effect="ruby"
    )
    configured = role("ranged", hitpoints=500)
    result = evaluate_loadout([item, ammo], configured, LEVELS)
    assert result.supported
    assert result.bolt_effect.total_max_hit == 100
    assert result.bolt_effect.normal_max_hit == 35


def test_wand_ancient_spell_and_damage_cap():
    item = weapon(30070, "magic")
    configured = role("magic", spell="ice_barrage")
    result = evaluate_loadout([item], configured, LEVELS)
    assert result.max_hit == (30 * 110 // 100) * 140 // 100
    assert result.attack_interval == 3
    assert not evaluate_loadout(
        [item], role("magic", spell="ice_barrage", damage_cap=40), LEVELS
    ).supported
