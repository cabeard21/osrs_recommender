"""Cached transition plans preserve validation, inventory context, and isolation."""

from copy import deepcopy
from dataclasses import replace

import pytest

from tools.gear_retention_oracle import tiny_cases
from tracker.gear import optimizer
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.facts import equipment_fact


@pytest.fixture
def case():
    return next(case for case in tiny_cases() if case.name == "hands")


def search_for(case):
    facts = {
        i: equipment_fact(case.snapshot, item, case.content, case.prices, case.at)
        for i, item in case.catalog.items.items()
    }
    return optimizer._Search(case.snapshot, case.request, case.catalog.items, facts, None)


@pytest.fixture
def transition_calls(monkeypatch):
    original = optimizer.plan_transition
    calls = []

    def observe(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(optimizer, "plan_transition", observe)
    return calls


def test_joint_validation_reuses_plans_without_sharing_mutable_results(case, transition_calls):
    search = search_for(case)
    equipment = {"a": {"weapon": 100}, "b": {"weapon": 101, "shield": 30}}
    first = search.solution(equipment, 3)
    assert first is not None
    expected = deepcopy(first)
    assert len(transition_calls) == 2

    # A different swap limit must still be enforced when the plans are cached.
    assert search.solution(equipment, 0) is None
    reordered = {"a": {"weapon": 100}, "b": {"shield": 30, "weapon": 101}}
    assert search.solution(reordered, None) == expected
    assert len(transition_calls) == 2
    assert [row["action_count"] for row in first["transitions"]] == [2, 1]

    first["transitions"][0]["actions"][0]["automatically_removed"].append(999)
    first["transitions"][0]["actions"].clear()
    assert search.solution(equipment, 3) == expected
    assert len(transition_calls) == 2


def test_cached_failures_distinguish_carried_inventory_and_capacity(case, transition_calls):
    search = search_for(case)
    equipment = (("weapon", 100),)
    assert search._transition(equipment, equipment, frozenset({100, 101}), 0) is None
    assert search._transition(equipment, equipment, frozenset({100, 101}), 0) is None
    assert len(transition_calls) == 1

    empty_inventory = search._transition(equipment, equipment, frozenset({100}), 0)
    assert empty_inventory["max_gear_inventory_slots"] == 0
    spare_capacity = search._transition(equipment, equipment, frozenset({100, 101}), 1)
    assert spare_capacity["max_gear_inventory_slots"] == 1
    assert len(transition_calls) == 3


def test_transition_cache_is_local_to_catalog_and_search(case, transition_calls):
    two_handed = search_for(case)
    one_handed_case = replace(
        case,
        catalog=EquipmentCatalog(
            {
                **case.catalog.items,
                100: case.catalog.items[100].model_copy(update={"two_handed": False}),
            }
        ),
    )
    one_handed = search_for(one_handed_case)
    source = (("shield", 30), ("weapon", 101))
    destination = (("weapon", 100),)
    carried = frozenset({100, 101, 30})
    assert two_handed._transition(source, destination, carried, 2)["action_count"] == 1
    assert one_handed._transition(source, destination, carried, 2)["action_count"] == 2
    assert len(transition_calls) == 2
