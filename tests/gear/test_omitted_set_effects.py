from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.scoring import prepare_equipment


def test_omitted_effects_disclose_without_changing_base_stat_score():
    omission = "Obsidian set bonus is omitted; ordinary base stats only."
    weapon = EquipmentDefinition(
        id=1,
        name="Fixture weapon",
        slot="weapon",
        bonuses=EquipmentBonuses(stab=47, melee_strength=49),
        attack_styles=("stab",),
    )
    armour = EquipmentDefinition(
        id=2,
        name="Fixture armour",
        slot="body",
        bonuses=EquipmentBonuses(melee_strength=3),
        omitted_set_effects=(omission, omission),
    )
    levels = {"attack": 60, "strength": 60}
    equipment = [weapon, armour]
    result = evaluate_loadout(equipment, "stab", levels)
    baseline = evaluate_loadout(
        [weapon, armour.model_copy(update={"omitted_set_effects": ()})], "stab", levels
    )
    score = evaluate_prepared_score(prepare_equipment(equipment), "stab", levels)
    assert result.supported and score.supported
    assert result.limitations.count(omission) == 1
    assert result.dps == baseline.dps == score.dps
    assert result.attack_roll == baseline.attack_roll
    assert result.max_hit == baseline.max_hit
    assert EquipmentDefinition.model_validate(armour.model_dump()) == armour


def test_omissions_do_not_clear_other_unsupported_effects():
    item = EquipmentDefinition(
        id=1,
        name="Fixture armour",
        slot="body",
        omitted_set_effects=("Set bonus omitted.",),
        unsupported_effects=("Unreviewed passive.",),
    )
    result = evaluate_loadout([item], "crush", {"attack": 60, "strength": 60})
    assert not result.supported
    assert result.dps is None
    assert "Unreviewed passive." in result.limitations
    assert "Set bonus omitted." in result.limitations


def test_item_inspector_discloses_omission_without_blocking_wear(make_content):
    from datetime import UTC, datetime

    from tracker.accounts.snapshot import AccountSnapshot
    from tracker.gear.facts import equipment_fact

    omission = "Set bonus omitted; base stats only."
    item = EquipmentDefinition(
        id=1,
        name="Fixture cape",
        slot="cape",
        requirements_complete=True,
        omitted_set_effects=(omission,),
    )
    fact = equipment_fact(AccountSnapshot(1, "test"), item, make_content(), {}, datetime.now(UTC))
    assert fact["wear"]["status"] == "satisfied"
    assert fact["support_status"] == "verified"
    assert fact["limitations"] == [omission]
