"""Exact compiled/Python differential coverage for bolt and hopper candidates."""

from types import SimpleNamespace

import pytest

from tracker.gear.combat import evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig
from tracker.gear.scoring import prepare_equipment

FAMILIES = (None, "opal", "pearl", "ruby", "diamond", "dragonstone", "onyx")


def compare(
    family,
    *,
    hopper=False,
    zaryte=False,
    diary=False,
    armour=0,
    hp=500,
    current=None,
    traits=(),
    cap=None,
    level=99,
    attack=55,
    crossbow=True,
):
    native = pytest.importorskip("tracker.gear.native._scoring")
    weapon = EquipmentDefinition(
        id=26374 if zaryte else 9185 if crossbow else 999999,
        name="Crossbow",
        slot="weapon",
        attack_styles=("ranged",),
        ammo_for=("bolt:test",),
        attack_speed=5,
        bonuses=EquipmentBonuses(ranged=attack),
    )
    ammo = EquipmentDefinition(
        id=9242,
        name="Bolt",
        slot="ammunition",
        ammo_type="bolt:test",
        bolt_effect=family,
        bonuses=EquipmentBonuses(ranged_strength=100),
    )
    items = {weapon.id: weapon, ammo.id: ammo}
    equipment = {"weapon": weapon.id, "ammunition": ammo.id}
    if hopper:
        items[32879] = EquipmentDefinition(id=32879, name="Hopper", slot="shield")
        equipment["shield"] = 32879
    role = RoleConfig(
        id="ranged",
        style="ranged",
        stance="rapid",
        target=CombatTarget(
            hitpoints=hp,
            current_hitpoints=current,
            traits=traits,
            flat_armour=armour,
            damage_cap=cap,
            defence_level=110,
        ),
    ).model_copy(update={"bolt_diary_boost": diary, "bolt_diary_known": True})
    search = SimpleNamespace(
        request=SimpleNamespace(roles=(role,), secondary_priority="accuracy"),
        items=items,
        eligible=items,
        levels={"ranged": level},
    )
    prepared = prepare_equipment([items[i] for i in equipment.values()])
    expected = evaluate_prepared_score(prepared, role, search.levels)
    actual = native.ScoringContext(search).score(equipment, 0)
    assert actual["supported"] == expected.supported
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy
    return actual


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("hopper", [False, True])
@pytest.mark.parametrize("zaryte", [False, True])
@pytest.mark.parametrize("diary", [False, True])
@pytest.mark.parametrize("armour", [-4, 0, 3])
def test_native_ranged_effects_exact(family, hopper, zaryte, diary, armour):
    compare(family, hopper=hopper, zaryte=zaryte, diary=diary, armour=armour)


@pytest.mark.parametrize(
    "family,traits",
    [
        ("pearl", ("fiery",)),
        ("dragonstone", ("fiery",)),
        ("dragonstone", ("dragon",)),
        ("onyx", ("undead",)),
    ],
)
@pytest.mark.parametrize("hopper", [False, True])
def test_native_target_trait_effects(family, traits, hopper):
    compare(family, traits=traits, hopper=hopper)


@pytest.mark.parametrize("hopper", [False, True])
@pytest.mark.parametrize("hp,current", [(None, None), (500, 10), (10, None)])
def test_native_ruby_target_hp(hopper, hp, current):
    compare("ruby", hopper=hopper, hp=hp, current=current)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("cap", [1, 19, 20, 99, 100, 110])
def test_native_effect_caps(family, cap):
    compare(family, cap=cap, hopper=True)


@pytest.mark.parametrize("family", FAMILIES)
def test_hopper_requires_reviewed_crossbow(family):
    compare(family, hopper=True, crossbow=False)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("attack", [-100, 0, 10000])
def test_low_level_and_extreme_accuracy(family, attack):
    compare(family, hopper=True, level=1, attack=attack)
