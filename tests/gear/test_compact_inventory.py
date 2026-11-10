"""Inventory counts retain concrete union semantics on compact assignments."""

import pytest

from tracker.gear.compact_states import EquipmentState
from tracker.gear.transitions import inventory_slots, plan_transition


@pytest.mark.parametrize("carried", [set(), {1}, {1, 2}, {1, 2, 3}, {3, 4}])
@pytest.mark.parametrize(
    "equipment", [{}, {"weapon": 1}, {"weapon": 1, "head": 2}, {"weapon": 1, "head": 1}]
)
def test_compact_inventory_matches_set_difference(equipment, carried):
    state = EquipmentState.from_mapping(equipment)
    assert inventory_slots(state, carried, {}) == inventory_slots(equipment, carried, {})
    assert inventory_slots(state, carried, {}) == len(carried - set(equipment.values()))


def test_compact_inventory_does_not_rebuild_equipment_set(monkeypatch):
    state = EquipmentState.from_mapping({"weapon": 1, "head": 2})

    def fail(*args):
        pytest.fail("Compact inventory must use already frozen physical IDs")

    monkeypatch.setattr(EquipmentState, "values", fail)
    assert inventory_slots(state, {1, 2, 3}, {}) == 1


@pytest.mark.parametrize("capacity", [0, 1, 2, 28])
def test_compact_transition_capacity_matches_original(capacity):
    from types import SimpleNamespace

    items = {
        1: SimpleNamespace(two_handed=True),
        2: SimpleNamespace(two_handed=False),
        3: SimpleNamespace(two_handed=False),
    }
    source = {"weapon": 1}
    destination = {"weapon": 2, "shield": 3}
    kwargs = {"carried": {1, 2, 3}, "capacity": capacity}
    for left, right in ((source, destination), (destination, source)):
        expected = plan_transition(left, right, items, **kwargs)
        actual = plan_transition(
            EquipmentState.from_mapping(left), EquipmentState.from_mapping(right), items, **kwargs
        )
        assert actual == expected
