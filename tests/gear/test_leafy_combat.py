import pytest

from tracker.gear.combat import _armoured_mean, evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig
from tracker.gear.scoring import prepare_equipment

LEVELS = {"attack": 90, "strength": 90, "ranged": 90, "magic": 90, "slayer": 70}


def weapon(i, style="slash", **kw):
    return EquipmentDefinition(id=i, name=str(i), slot="weapon", attack_styles=(style,), **kw)


@pytest.mark.parametrize("i,valid", [(11902, True), (20727, True), (4158, True), (4151, False)])
def test_leafy_melee(i, valid):
    role = RoleConfig(id="r", style="slash", target=CombatTarget(traits=("leafy",)))
    result = evaluate_loadout([weapon(i)], role, LEVELS)
    assert result.supported == valid


def test_leafy_ranged_requires_fired_broad_ammo():
    role = RoleConfig(id="r", style="ranged", target=CombatTarget(traits=("leafy",)))
    ammo = EquipmentDefinition(id=4160, name="broad", slot="ammunition", ammo_type="arrow:4160")
    bow = weapon(861, "ranged", ammo_for=("arrow:4160",))
    assert evaluate_loadout([bow, ammo], role, LEVELS).supported
    assert not evaluate_loadout([bow], role, LEVELS).supported
    assert not evaluate_loadout([weapon(25849, "ranged"), ammo], role, LEVELS).supported


def test_leafy_rejects_other_magic():
    role = RoleConfig(id="r", style="magic", target=CombatTarget(traits=("leafy",)))
    assert not evaluate_loadout([], role, LEVELS).supported


@pytest.mark.parametrize("maximum", range(7))
@pytest.mark.parametrize("armour", [-2, 0, 2, 4])
def test_seeking_exact_distribution(maximum, armour):
    expected = sum(max(0, max(d, 3) - armour) for d in range(maximum + 1)) / (maximum + 1)
    assert _armoured_mean(maximum, armour, 3) == expected


def test_leaf_battleaxe_and_seeking_reports_and_cached_parity(make_content):
    from tracker.gear.catalog import load_catalog
    from tracker.gear.prepared_combat import prepared_combat
    from tracker.gear.ranged_numerics import ranged_experiment
    from tracker.gear.ranged_score_finalization import ranged_score_finalization

    c = load_catalog(make_content())
    role = RoleConfig(
        id="r", style="slash", target=CombatTarget(traits=("leafy",)), on_slayer_task=True
    )
    equipment = [c.items[i] for i in (20727, 11865)]
    result = evaluate_loadout(equipment, role, LEVELS)
    baseline = evaluate_loadout(
        equipment, role.model_copy(update={"target": CombatTarget()}), LEVELS
    )
    assert result.supported and result.max_hit == baseline.max_hit * 47 // 40
    assert result.leafy_bonus.item_id == 20727
    role = role.model_copy(update={"style": "ranged"})
    for ammo in (4160, 33601, 4160):
        equipment = [c.items[i] for i in (861, ammo, 11865)]
        result = evaluate_loadout(equipment, role, LEVELS)
        assert result.supported
        with prepared_combat(), ranged_experiment(20), ranged_score_finalization():
            assert (
                evaluate_prepared_score(prepare_equipment(equipment), role, LEVELS).dps
                == result.dps
            )
        assert bool(result.seeking_arrow_bonus) == (ammo == 33601)
