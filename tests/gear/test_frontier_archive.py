"""Incremental archives preserve exact complete-solution Pareto semantics."""

from copy import deepcopy
from random import Random

import pytest

from tracker.gear.frontier import _insert_pareto, pareto
from tracker.gear.optimizer import _solution_key


def point(dps, secondary, identity, *, cost=0, potion_cost=0, doses=0):
    return {
        "score": dps,
        "secondary_value": secondary,
        "max_gear_inventory_slots": 0,
        "purchase_cost_gp": cost,
        "transitions": [],
        "loadouts": {identity: {"equipment": {}, "performance": {"dps": dps}}},
        "potions": {
            "cost_per_application_gp": potion_cost,
            "selected_ids": [str(i) for i in range(doses)],
        },
    }


@pytest.mark.parametrize("seed", range(12))
def test_incremental_archive_matches_full_stable_sort_after_every_insert(seed):
    random = Random(seed)
    rows = [
        point(
            random.randrange(6),
            random.randrange(-4, 5),
            str(random.randrange(4)),
            cost=random.randrange(3),
            potion_cost=random.choice([None, 0, 1, 2]),
            doses=random.randrange(3),
        )
        for _ in range(150)
    ]
    original = deepcopy(rows)
    archive = ()
    expected = []
    for row in rows:
        previous = archive
        before = list(previous)
        archive = _insert_pareto(archive, row, _solution_key(row))
        expected = pareto([*expected, row])
        assert [entry[1] for entry in archive] == expected
        assert list(previous) == before
    assert rows == original


def test_equal_keys_retain_the_existing_solution_object():
    first = point(10, 3, "a")
    second = deepcopy(first)
    archive = _insert_pareto((), first, _solution_key(first))
    assert _insert_pareto(archive, second, _solution_key(second)) is archive
    assert archive[0][1] is first


def test_dominated_insert_reuses_archive_and_dominating_insert_removes_successors():
    rows = [point(10, 1, "a"), point(9, 3, "b"), point(8, 5, "c")]
    archive = tuple((_solution_key(row), row) for row in rows)
    dominated = point(7, 4, "d")
    assert _insert_pareto(archive, dominated, _solution_key(dominated)) is archive
    winner = point(11, 5, "e")
    assert _insert_pareto(archive, winner, _solution_key(winner)) == (
        (_solution_key(winner), winner),
    )


@pytest.mark.parametrize("role_count", [1, 2])
@pytest.mark.parametrize("priority", ["balanced_defence", "magic_ranged_defence", "accuracy"])
def test_complete_search_matches_full_sort_archive_oracle(monkeypatch, role_count, priority):
    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear import frontier
    from tracker.gear.optimizer import RoleConfig

    # Compare all diagnostics as well as archives with an observational clock
    # fixed independently of the archive implementation's running time.
    monkeypatch.setattr(frontier, "perf_counter", lambda: 0.0)
    items = [
        weapon(1, "slash"),
        weapon(2, "crush"),
        armour(20, melee_strength=10),
        armour(30, defence_stab=100, defence_magic=40, defence_ranged=60),
        armour(40, melee_strength=5, defence_stab=50, defence_magic=90),
    ]
    roles = tuple(RoleConfig(id=str(i), style="slash") for i in range(role_count))
    options = {"max_swaps": 3, "secondary_priority": priority, "max_dps_loss_pct": 100}
    actual = run(items, roles, **options)

    def full_sort(archive, row, key):
        rows = pareto([*[entry[1] for entry in archive], row])
        return tuple((_solution_key(value), value) for value in rows)

    monkeypatch.setattr(frontier, "_insert_pareto", full_sort)
    expected = run(items, roles, **options)
    assert actual == expected
