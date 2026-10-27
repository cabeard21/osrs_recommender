"""Exact evaluation shares the search's physical legality and combat formulas."""

import pytest

from tracker.gear.combat import evaluate_loadout
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig


def test_exact_evaluation_matches_existing_validated_combat_function():
    weapon = EquipmentDefinition(
        id=1,
        name="Sword",
        slot="weapon",
        attack_styles=("slash",),
        bonuses=EquipmentBonuses(slash=30, melee_strength=45),
    )
    role = RoleConfig(id="single", style="slash")
    levels = {"attack": 70, "strength": 75}
    actual = evaluate_equipment({"weapon": 1}, {1: weapon}, role, levels)
    assert actual == evaluate_loadout({"weapon": weapon}, role, levels)
    assert actual.supported


@pytest.mark.parametrize(
    "equipment,reason",
    [
        ({"weapon": 999}, "Unknown physical item"),
        ({"head": 1}, "does not occupy head"),
        ({"weapon": 1, "shield": 2}, "Two-handed"),
    ],
)
def test_exact_evaluation_rejects_invalid_physical_loadouts(equipment, reason):
    items = {
        1: EquipmentDefinition(id=1, name="Bow", slot="weapon", two_handed=True),
        2: EquipmentDefinition(id=2, name="Shield", slot="shield"),
    }
    result = evaluate_equipment(
        equipment, items, RoleConfig(id="single", style="slash"), {"attack": 99, "strength": 99}
    )
    assert not result.supported
    assert result.dps is result.max_hit is result.accuracy is result.attack_interval is None
    assert any(reason in limitation for limitation in result.limitations)
