import pytest

from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig
from tracker.gear.scoring import prepare_equipment

LEVELS = {"attack": 90, "strength": 90, "ranged": 90, "magic": 90, "slayer": 55}


@pytest.mark.parametrize(
    "item_id,style,numerator,denominator",
    [
        (8921, "crush", 7, 6),
        (11865, "crush", 7, 6),
        (11865, "ranged", 23, 20),
        (11865, "magic", 23, 20),
        (11864, "magic", 1, 1),
    ],
)
def test_task_mask_bonus(make_content, item_id, style, numerator, denominator):
    catalog = load_catalog(make_content())
    head = catalog.items[item_id]
    weapon = [catalog.items[861], catalog.items[892]] if style == "ranged" else []
    off = RoleConfig(id="role", style=style, spell="fire_wave")
    on = off.model_copy(update={"on_slayer_task": True})
    baseline = evaluate_loadout([head, *weapon], off, LEVELS)
    result = evaluate_loadout([head, *weapon], on, LEVELS)
    assert baseline.supported and result.supported
    assert result.max_hit == baseline.max_hit * numerator // denominator
    assert result.attack_roll == baseline.attack_roll * numerator // denominator
    assert bool(result.slayer_effects) == (numerator != 1)
    score = evaluate_prepared_score(prepare_equipment([head, *weapon]), on, LEVELS)
    assert score.dps == result.dps


@pytest.mark.parametrize(
    "staff_id,on_task,expected",
    [(4170, False, 19), (4170, True, 19), (21255, False, 19), (21255, True, 28)],
)
def test_magic_dart(make_content, staff_id, on_task, expected):
    staff = load_catalog(make_content()).items[staff_id]
    role = RoleConfig(id="mage", style="magic", spell="magic_dart").model_copy(
        update={"on_slayer_task": on_task}
    )
    result = evaluate_loadout([staff], role, LEVELS)
    assert result.supported
    assert result.max_hit == expected
    assert result.attack_interval == 3
    assert evaluate_prepared_score(prepare_equipment([staff]), role, LEVELS).dps == result.dps
    assert not evaluate_loadout([], role, LEVELS).supported
    assert not evaluate_loadout([staff], role, {**LEVELS, "slayer": 54}).supported


def test_slayer_review_all_forms(make_content):
    catalog = load_catalog(make_content())
    rows = [
        i
        for i in catalog.items.values()
        if "slayer helmet" in i.name.lower() or i.name.startswith("Black mask")
    ]
    assert len(rows) > 100
    assert all(
        i.requirements_complete and not i.unsupported_effects and i.slayer_bonus for i in rows
    )
    for item in rows:
        assert EquipmentDefinition.model_validate_json(item.model_dump_json()) == item


@pytest.mark.parametrize("level", [59, 60, 74, 75, 90, 98, 99])
def test_magic_mask_order_and_dart_stacking(make_content, level):
    catalog = load_catalog(make_content())
    head, tome = catalog.items[11865], catalog.items[25574]
    target = CombatTarget(weakness_element="water", weakness_percent=35)
    role = RoleConfig(id="mage", style="magic", spell="water_wave", target=target).model_copy(
        update={"on_slayer_task": True}
    )
    result = evaluate_loadout([head, tome], role, {**LEVELS, "magic": max(75, level)})
    base_attack = (max(75, level) + 11) * (head.bonuses.magic + tome.bonuses.magic + 64)
    assert result.attack_roll == (base_attack * 23 // 20) * 120 // 100 + base_attack * 35 // 100
    staff = catalog.items[21255]
    dart_role = role.model_copy(update={"spell": "magic_dart", "target": CombatTarget()})
    dart = evaluate_loadout([head, staff], dart_role, {**LEVELS, "magic": level})
    assert dart.max_hit == (13 + level // 6) * 23 // 20
    assert len(dart.slayer_effects) == 2


def test_cached_and_prepared_paths_keep_task_state(make_content):
    from tracker.gear.prepared_combat import prepared_combat
    from tracker.gear.ranged_numerics import ranged_experiment
    from tracker.gear.ranged_score_finalization import ranged_score_finalization

    catalog = load_catalog(make_content())
    equipment = [catalog.items[i] for i in (11865, 861, 892)]
    prepared = prepare_equipment(equipment)
    off = RoleConfig(id="ranged", style="ranged", stance="rapid")
    on = off.model_copy(update={"on_slayer_task": True})
    reference = [evaluate_loadout(equipment, role, LEVELS) for role in (off, on)]
    with prepared_combat(), ranged_experiment(20), ranged_score_finalization():
        scores = [evaluate_prepared_score(prepared, role, LEVELS) for role in (off, on, off, on)]
    assert [s.dps for s in scores] == [p.dps for p in reference] * 2
    assert scores[0].dps != scores[1].dps


def test_review_retains_unrelated_blockers_and_rejects_changed_identity():
    from tracker.gear.slayer import apply_review

    row = {
        "id": 11865,
        "name": "Slayer helmet (i)",
        "slot": "head",
        "unsupported_effects": ["Offensive effects have not been validated.", "Other"],
    }
    assert apply_review(row)["unsupported_effects"] == ["Other"]
    assert len(row["unsupported_effects"]) == 2
    with pytest.raises(ValueError, match="physical form changed"):
        apply_review({**row, "slot": "neck"})


@pytest.mark.parametrize("staff_id", [4170, 21255])
def test_slayer_staff_autocast_subset(make_content, staff_id):
    staff = load_catalog(make_content()).items[staff_id]
    assert "magic_dart" in staff.spell_compatibility
    assert "water_wave" in staff.spell_compatibility
    assert "fire_surge" in staff.spell_compatibility
    for spell in ("fire_strike", "fire_bolt", "fire_blast", "ice_barrage", "iban_blast"):
        assert spell not in staff.spell_compatibility
        role = RoleConfig(id="mage", style="magic", spell=spell)
        assert not evaluate_loadout([staff], role, LEVELS).supported


def test_slayer_helpers_and_requirements(make_content):
    from tracker.gear.slayer import apply_review, mask_factor

    unrelated = {"id": 1}
    assert apply_review(unrelated) is unrelated
    assert mask_factor("melee", "ranged", True) == (1, 1)
    assert mask_factor("all", "special", True) == (1, 1)
    catalog = load_catalog(make_content())
    assert catalog.items[11865].requires.to_yaml() == {"skill": {"defence": 10}}
    assert catalog.items[21255].requires.to_yaml() == {
        "all_of": [{"skill": {"magic": 75}}, {"skill": {"slayer": 55}}]
    }
    assert not catalog.items[21255].tradeable
    assert catalog.items[4170].tradeable
    assert catalog.items[8921].tradeable
