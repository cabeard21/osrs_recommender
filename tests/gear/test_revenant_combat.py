"""Wilderness weapon roll order, projectile defence and native combat parity."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig
from tracker.gear.prepared_combat import prepared_combat
from tracker.gear.ranged_numerics import ranged_experiment
from tracker.gear.ranged_score_finalization import ranged_score_finalization
from tracker.gear.scoring import prepare_equipment

LEVELS = dict.fromkeys(("attack", "strength", "defence", "ranged", "magic"), 99)
MASK = EquipmentDefinition(id=11865, name="Slayer helmet (i)", slot="head", slayer_bonus="all")


def role_for(style, wilderness, *, task=False, powered=None):
    from tracker.gear.evaluation import resolve_scenario_combat_context

    role = RoleConfig(
        id="npc",
        style=style,
        stance="rapid" if style == "ranged" else "accurate",
        spell="fire_wave",
        on_slayer_task=task,
        target=CombatTarget(
            ranged_light=150, ranged_standard=40, weakness_element="fire", weakness_percent=50
        ),
    ).model_copy(update={"powered_attack": powered})
    return resolve_scenario_combat_context(
        role, SimpleNamespace(wilderness={} if wilderness else None, fire_tome_pages="burnt")
    )


@pytest.mark.parametrize("weapon_id", [22545, 27660, 22550, 27655, 22555, 27665, 27788, 27679])
@pytest.mark.parametrize("task", [False, True])
@pytest.mark.parametrize("wilderness", [False, True])
def test_revenant_combat(weapon_id, task, wilderness):
    bow = weapon_id in {22550, 27655}
    mace = weapon_id in {22545, 27660}
    powered = weapon_id in {22555, 27665}
    style = "crush" if mace else "ranged" if bow else "magic"
    role = role_for(style, wilderness, task=task, powered="test" if powered else None)
    weapon = EquipmentDefinition(
        id=weapon_id,
        name="Test weapon",
        slot="weapon",
        attack_styles=(style,),
        bonuses=EquipmentBonuses(
            crush=53, melee_strength=66, ranged=70, ranged_strength=60, magic=15
        ),
        powered_attack="test" if powered else None,
        powered_attack_stances=("accurate",) if powered else (),
        powered_attack_base_max_hit=25 if powered else None,
    )
    gear = [weapon, MASK]
    if bow:
        gear.append(
            EquipmentDefinition(
                id=11212,
                name="Equipped arrow",
                slot="ammunition",
                bonuses=EquipmentBonuses(ranged_strength=60, ranged=20),
            )
        )
    # Unmodified rolls before Slayer or Wilderness. For magic the elemental
    # weakness adds a separately floored fraction of those original rolls.
    attack = 110 * (53 + 64) if mace else 107 * (70 + 64) if bow else 110 * (15 + 64)
    maximum = 22 if mace else 21 if bow else 25 if powered else 20
    base_attack = attack
    if task:
        attack = attack * (7 if mace else 23) // (6 if mace else 20)
        maximum = (
            maximum * 33 // 20
            if bow and wilderness
            else maximum * (7 if mace else 23) // (6 if mace else 20)
        )
    if wilderness:
        attack = attack * 3 // 2
        if not (bow and task):
            maximum = maximum * 3 // 2
    if style == "magic" and not powered:
        attack += base_attack // 2
        maximum += 10
    result = evaluate_loadout(gear, role, LEVELS)
    assert result.supported
    assert result.wilderness_weapon_passive is wilderness
    assert (result.attack_roll, result.max_hit) == (attack, maximum)
    if bow:
        assert result.defence_roll == 10 * (40 + 64)
    with prepared_combat(), ranged_experiment(), ranged_score_finalization():
        score = evaluate_prepared_score(prepare_equipment(gear), role, LEVELS)
        assert (score.accuracy, score.dps) == (result.accuracy, result.dps)
    native = pytest.importorskip("tracker.gear.native._scoring")
    items = {item.id: item for item in gear}
    equipment = {item.slot: item.id for item in gear}
    search = SimpleNamespace(
        request=SimpleNamespace(roles=(role,), secondary_priority="default"),
        levels=LEVELS,
        items=items,
        eligible=items,
    )
    scored = native.ScoringContext(search).score(equipment, 0)
    assert scored["supported"]
    assert (scored["accuracy"], scored["dps"]) == (result.accuracy, result.dps)


@pytest.mark.parametrize(
    "weapon_id,style",
    [(22542, "crush"), (27657, "stab"), (27785, "magic"), (27676, "magic"), (27788, "crush")],
)
def test_uncharged_and_unmatched_styles_do_not_receive_passive(weapon_id, style):
    weapon = EquipmentDefinition(id=weapon_id, slot="weapon", name="Weapon", attack_styles=(style,))
    outside = evaluate_loadout([weapon], role_for(style, False), LEVELS)
    inside = evaluate_loadout([weapon], role_for(style, True), LEVELS)
    assert inside.supported and inside.wilderness_weapon_passive is False
    assert outside.dps == inside.dps
    if weapon_id != 27788:
        assert all("ether balance is unknown" not in note for note in inside.limitations)


def test_role_cannot_supply_scenario_wilderness():
    with pytest.raises(ValidationError):
        RoleConfig.model_validate({"id": "npc", "style": "crush", "_in_wilderness": True})


def test_wilderness_toggle_separates_cached_ranged_results():
    weapon = EquipmentDefinition(
        id=22550,
        slot="weapon",
        name="Craw's bow",
        attack_styles=("ranged",),
    )
    roles = [role_for("ranged", wilderness) for wilderness in (False, True, False)]
    with ranged_experiment(capacity=2) as cache, ranged_score_finalization():
        scores = [
            evaluate_prepared_score(prepare_equipment([weapon]), role, LEVELS) for role in roles
        ]
        assert scores[0] == scores[2]
        assert scores[0].dps < scores[1].dps
        assert (cache.cache_info().hits, cache.cache_info().misses) == (1, 2)
