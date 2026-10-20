from types import SimpleNamespace

from tracker.gear.transitions import inventory_slots, plan_transition


def catalog():
    return {
        1: SimpleNamespace(id=1, slot="weapon", two_handed=False, stackable=False),
        2: SimpleNamespace(id=2, slot="shield", two_handed=False, stackable=False),
        3: SimpleNamespace(id=3, slot="weapon", two_handed=True, stackable=False),
    }


def test_hand_changes_are_directional_actions():
    items = catalog()
    forward = plan_transition({"weapon": 1, "shield": 2}, {"weapon": 3}, items)
    reverse = plan_transition({"weapon": 3}, {"weapon": 1, "shield": 2}, items)
    assert forward["action_count"] == 1
    assert forward["changed_slots"] == 2
    assert reverse["action_count"] == 2
    assert forward["actions"][0]["automatically_removed"] == [1, 2]


def test_inventory_capacity_validated_in_intermediate_states():
    items = catalog()
    assert inventory_slots({"weapon": 3}, {1, 2, 3}, items) == 2
    assert (
        plan_transition(
            {"weapon": 1, "shield": 2}, {"weapon": 3}, items, carried={1, 2, 3}, capacity=1
        )
        is None
    )


def test_explicit_unequip_and_reverse_shield():
    items = catalog()
    result = plan_transition({"weapon": 3}, {"shield": 2}, items)
    assert result["action_count"] == 1
    assert result["actions"][0]["automatically_removed"] == [3]
    assert plan_transition({"weapon": 1}, {}, items)["action_count"] == 1


def test_identical_setup_requires_zero_actions():
    assert plan_transition({"weapon": 1}, {"weapon": 1}, catalog())["action_count"] == 0
