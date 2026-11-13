"""Compact BFS retains the original traversal, action sequence and capacities."""

from itertools import product
from random import Random
from types import SimpleNamespace

import pytest

from tracker.gear.transitions import plan_transition


def test_reduced_exhaustive_transition_reports_match_original():
    from tracker.gear.compact_transitions import compact_transition

    items = {i: SimpleNamespace(two_handed=i == 3) for i in range(1, 6)}
    states = [
        {
            slot: item
            for slot, item in zip(("weapon", "shield", "head"), row, strict=True)
            if item is not None
        }
        for row in product((None, 1, 3), (None, 2), (None, 4))
    ]
    states.append({"weapon": 1, "head": 1})
    for source, destination, capacity in product(states, states, (0, 1, 2, 3, 4, 28)):
        for carried in (None, frozenset((1, 2, 3, 4, 5)), frozenset((1, 4))):
            kwargs = {"carried": carried, "capacity": capacity}
            assert compact_transition(source, destination, items, **kwargs) == plan_transition(
                source, destination, items, **kwargs
            )


def test_p3_dispatch_and_generic_slot_fallback(monkeypatch):
    import tracker.gear.compact_transitions as compact
    from tests.gear.test_auto_disciplines import context
    from tracker.gear.execution_profile import execution_context

    calls = []
    original = compact.compact_transition

    def measured(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(compact, "compact_transition", measured)
    items = {1: SimpleNamespace(two_handed=False)}
    with execution_context("combined", context()[1], factored_evaluation=True, compact_states=True):
        assert plan_transition({}, {"weapon": 1}, items)["action_count"] == 1
        assert len(calls) == 1
        assert plan_transition({}, {"fixture_slot": 1}, items)["action_count"] == 1
        assert len(calls) == 1
        assert plan_transition({"head": None}, {}, items)["action_count"] == 1
        assert len(calls) == 1
        unusual = plan_transition({"head": 1}, {}, items, carried={None, 1})
        assert unusual["max_gear_inventory_slots"] == 2
        assert len(calls) == 1


@pytest.mark.parametrize("capacity", [0, 1, 2, 28])
def test_dispatch_preserves_two_hand_directional_paths(capacity):
    from tests.gear.test_auto_disciplines import context
    from tracker.gear.execution_profile import execution_context

    items = {i: SimpleNamespace(two_handed=i == 3) for i in (1, 2, 3)}
    for source, destination in (
        ({"weapon": 1, "shield": 2}, {"weapon": 3}),
        ({"weapon": 3}, {"shield": 2}),
    ):
        expected = plan_transition(source, destination, items, capacity=capacity)
        with execution_context(
            "combined", context()[1], factored_evaluation=True, compact_states=True
        ):
            assert plan_transition(source, destination, items, capacity=capacity) == expected


def test_queued_states_omit_invariant_non_hand_slots(monkeypatch):
    import tracker.gear.compact_transitions as module

    widths = []
    original = module._Node

    def measured(state, *args):
        widths.append(len(state))
        return original(state, *args)

    monkeypatch.setattr(module, "_Node", measured)
    items = {i: SimpleNamespace(two_handed=False) for i in range(1, 14)}
    source = dict(zip(module.SLOTS, range(1, 12), strict=True))
    destination = {**source, "head": 12}
    assert module.compact_transition(source, destination, items) == plan_transition(
        source, destination, items
    )
    assert widths and set(widths) == {1}


def test_randomized_full_slot_shared_equipment_matches_baseline():
    from tracker.gear.compact_transitions import SLOTS, compact_transition

    rng = Random(8544)
    items = {i: SimpleNamespace(two_handed=i in (3, 13)) for i in range(1, 23)}
    for _ in range(300):
        source = {slot: rng.randrange(1, 23) for slot in SLOTS if rng.random() < 0.8}
        destination = dict(source)
        for slot in rng.sample(SLOTS, rng.randrange(4)):
            if rng.random() < 0.3:
                destination.pop(slot, None)
            else:
                destination[slot] = rng.randrange(1, 23)
        # Explicitly include extra inventory and occasionally duplicate physical
        # IDs between unchanged and changed coordinates.
        carried = frozenset((*source.values(), *destination.values(), 21, 22))
        for capacity in (0, 2, 5, 28):
            kwargs = {"carried": carried, "capacity": capacity}
            assert compact_transition(source, destination, items, **kwargs) == plan_transition(
                source, destination, items, **kwargs
            )


@pytest.mark.parametrize(
    "source,destination",
    [
        ({"cape": 1, "head": 1}, {"cape": 1, "head": 2}),
        ({"neck": 1, "ring": 2}, {"neck": 4, "ring": 5}),
        ({"weapon": 3, "head": 1}, {"weapon": 3, "head": 2}),
        ({"weapon": 1, "shield": 2}, {"weapon": 3, "shield": 2}),
        ({"weapon": 3}, {"weapon": 3, "shield": 2}),
        ({"cape": 1, "weapon": 3}, {"cape": 1, "weapon": 3}),
    ],
)
def test_constant_factoring_preserves_hand_coupling_duplicates_and_slot_names(source, destination):
    from tracker.gear.compact_transitions import compact_transition

    items = {i: SimpleNamespace(two_handed=i == 3) for i in range(1, 6)}
    for carried in (None, frozenset((2, 4, 5))):
        for capacity in (0, 1, 2, 28):
            kwargs = {"carried": carried, "capacity": capacity}
            assert compact_transition(source, destination, items, **kwargs) == plan_transition(
                source, destination, items, **kwargs
            )


def test_prepared_problem_shares_only_irrelevant_constant_equipment():
    from tracker.gear.compact_transitions import prepare_transition, solve_transition

    items = {i: SimpleNamespace(two_handed=i == 3) for i in range(1, 7)}
    first = prepare_transition({"weapon": 1, "head": 4}, {"weapon": 3, "head": 4})
    other = prepare_transition({"weapon": 1, "head": 5}, {"weapon": 3, "head": 5})
    assert first == other and hash(first) == hash(other)
    assert solve_transition(first, items) == plan_transition(
        {"weapon": 1, "head": 4}, {"weapon": 3, "head": 4}, items
    )
    assert first != prepare_transition(
        {"weapon": 1, "head": 4}, {"weapon": 3, "head": 4}, capacity=1
    )
    assert first != prepare_transition(
        {"weapon": 1, "head": 4}, {"weapon": 3, "head": 4}, carried={1, 3, 4, 6}
    )
    coupled = prepare_transition({"weapon": 1, "shield": 2}, {"weapon": 3, "shield": 2})
    assert coupled != first
    assert solve_transition(coupled, items) is None
    other_catalog = {**items, 3: SimpleNamespace(two_handed=False)}
    assert solve_transition(coupled, other_catalog) == plan_transition(
        {"weapon": 1, "shield": 2}, {"weapon": 3, "shield": 2}, other_catalog
    )
    assert solve_transition(coupled, other_catalog) is not None
    shared = prepare_transition({"cape": 1, "head": 1}, {"cape": 1, "head": 2})
    distinct = prepare_transition({"cape": 3, "head": 1}, {"cape": 3, "head": 2})
    assert shared != distinct
    assert shared.carried == frozenset((2,))
    assert distinct.carried == frozenset((1, 2))
    assert first != prepare_transition({"weapon": 3, "head": 4}, {"weapon": 1, "head": 4})
    with pytest.raises(AttributeError):
        first.capacity = 0
