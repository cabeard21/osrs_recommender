"""Whole-kit measurement is independent of combat and active-time weighting."""

from types import SimpleNamespace

import pytest

from tracker.gear.carried_weight import (
    UnknownGearWeight,
    heaviest_carried_weight_kg,
    measure_carried_weight,
)
from tracker.gear.objectives import ObjectiveDescriptor, annotate_solution
from tracker.gear.optimizer import _objective_winner_key


def item(worn, packed, inventory_id=None):
    return SimpleNamespace(
        worn_weight_grams=worn, inventory_weight_grams=packed, inventory_form_id=inventory_id
    )


def test_worn_and_packed_weights_share_one_physical_item_across_roles():
    items = {1: item(1500, 1500), 2: item(-3000, 600, 20), 20: item(-3000, 600, 20)}
    gear = {
        "combat": {"weapon": 1, "head": 2},
        "swap": {"weapon": 1, "head": 20},
        "utility": {"weapon": 1},
    }
    expected = {
        "heaviest_kg": 2.1,
        "roles": {
            "combat": {"worn_kg": -1.5, "backpack_kg": 0.0, "total_kg": -1.5},
            "swap": {"worn_kg": -1.5, "backpack_kg": 0.0, "total_kg": -1.5},
            "utility": {"worn_kg": 1.5, "backpack_kg": 0.6, "total_kg": 2.1},
        },
    }
    assert measure_carried_weight(gear, items) == expected
    assert heaviest_carried_weight_kg(gear, items) == expected["heaviest_kg"]


def test_negative_total_is_minimized_in_both_archive_and_branch_baselines():
    goal = ObjectiveDescriptor(kind="carried_weight_kg")
    roles = [SimpleNamespace(id="combat", weight=1, style="slash")]
    items = {1: item(-3000, 600)}

    def solution(equipment):
        return annotate_solution(
            {
                "score": 1.0,
                "loadouts": {"combat": {"equipment": equipment, "performance": {}}},
                "max_gear_inventory_slots": 0,
                "purchase_cost_gp": 0,
                "transitions": [],
            },
            (goal,),
            roles,
            items=items,
        )

    light, bare = solution({"head": 1}), solution({})
    assert light["objective_values"] == {"carried_weight_kg": -3.0}
    assert light["carried_weight"]["roles"]["combat"]["backpack_kg"] == 0
    assert light["objective_definitions"] == [
        {
            "id": goal.id,
            "kind": goal.kind,
            "label": "Carried gear weight",
            "unit": "kg",
            "direction": "minimize",
        }
    ]
    assert _objective_winner_key(light) < _objective_winner_key(bare)


def test_missing_measurement_identifies_item():
    with pytest.raises(UnknownGearWeight, match="123"):
        measure_carried_weight({"main": {"head": 123}}, {123: item(None, 0)})


def test_missing_item_weight_is_disclosed_and_does_not_affect_dps_only_search():
    from tests.gear.test_optimizer import run, weapon
    from tracker.gear.optimizer import RoleConfig

    unknown = weapon(123, "slash", strength=50)
    known = weapon(456, "slash", worn_weight_grams=500, inventory_weight_grams=500)
    role = RoleConfig(id="main", style="slash")
    normal = run([unknown, known], (role,), objectives=[], max_swaps=0)
    assert normal["selected_solution"]["loadouts"]["main"]["equipment"]["weapon"] == 123
    assert "carried_weight" not in normal["selected_solution"]
    for lock in ({}, {"weapon": 123}):
        result = run(
            [unknown, known],
            (role,),
            locks=lock,
            max_swaps=0,
            objectives=[{"kind": "carried_weight_kg"}],
        )
        assert any("weight unavailable" in line and "123" in line for line in result["limitations"])
        if lock:
            assert result["selected_solution"] is None
        else:
            assert result["selected_solution"]["carried_weight"]["heaviest_kg"] == 0.5
