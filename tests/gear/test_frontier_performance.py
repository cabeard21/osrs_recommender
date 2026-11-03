"""Repeated work is avoided without changing frontier selections or option isolation."""

from collections.abc import Mapping

import pytest

from tests.gear.test_optimizer import NOW, run, weapon
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.facts import equipment_fact
from tracker.gear.frontier import _combat_variants, diverse
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, _Search


@pytest.mark.parametrize("limit", [2, 8, 12, 100])
def test_diverse_ranks_each_input_once(limit):
    rows = [{"id": i, "dps": 100 - i % 13, "secondary": i % 9} for i in range(30)]
    calls = []

    def rank(row):
        calls.append(row["id"])
        return (-row["dps"], -row["secondary"])

    result = diverse(iter(rows), rank, limit)
    assert sorted(calls) == list(range(30))
    expected = {
        2: [26, 25],
        8: [26, 25, 23, 8, 7, 6, 17, 16],
        12: [26, 25, 23, 8, 7, 6, 17, 16, 24, 10, 22, 20],
    }
    if limit in expected:
        assert [row["id"] for row in result] == expected[limit]
    else:
        assert result == sorted(rows, key=lambda row: (-row["dps"], -row["secondary"]))


class LookupOnly(Mapping):
    """Caches support lookup but must never be copied by enumerating their entries."""

    def __init__(self, data):
        self.data = data

    def __getitem__(self, key):
        return self.data[key]

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        raise AssertionError("Variant creation enumerated the shared cache")


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([{"v": 1}, {"v": 1}, {"v": 2}, {"v": 3}], [{"v": 3}, {"v": 2}, {"v": 1}]),
        ([{"v": i} for i in range(6)], [{"v": 5}, {"v": 4}, {"v": 3}]),
    ],
)
def test_diverse_preserves_equal_dps_bands_and_duplicate_row_equality(rows, expected):
    assert diverse(rows, lambda row: (-10, -row["v"]), 3) == expected


def test_diverse_preserves_input_order_for_equal_ranks():
    rows = [{"id": i} for i in range(5)]
    assert diverse(rows, lambda _: (-10, -1), 3) == rows[:3]


def test_combat_variants_use_isolated_overrides_without_enumerating_shared_caches():
    item = weapon(1, "ranged", attack_profiles=(("ranged", "accurate"), ("ranged", "rapid")))
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={"ranged": SkillState(70, None, Source.MANUAL, NOW)},
        observed_items={(1, Container.BANK): ObservedItemFact(1, Container.BANK, 1, "test", NOW)},
    )
    roles = tuple(
        RoleConfig(
            id=key,
            style="ranged",
            combat_options=CombatOptionFilters(
                attack_types=("light",), stances=("accurate", "rapid"), spells=()
            ),
        )
        for key in ("a", "b")
    )
    search = _Search(
        snapshot,
        OptimizationRequest(roles=roles, mode="owned", secondary_priority="accuracy"),
        {1: item},
        {1: equipment_fact(snapshot, item, Content(), {}, NOW)},
        None,
    )
    seed = search.solution({role.id: {"weapon": 1} for role in roles}, None)
    before_performance = dict(search.performance_cache)
    before_options = dict(search.option_cache)
    search.performance_cache = LookupOnly(search.performance_cache)
    search.option_cache = LookupOnly(search.option_cache)
    results = list(_combat_variants(search, seed, lambda: True))
    assert results
    assert any(
        all(row["combat_option"]["stance"] == "accurate" for row in result["loadouts"].values())
        for result in results
    )
    assert all(row["combat_option"]["stance"] == "rapid" for row in seed["loadouts"].values())
    assert search.performance_cache.data == before_performance
    assert search.option_cache.data == before_options


def test_single_frontier_enumerates_equipment_once(monkeypatch):
    original = _Search.loadouts
    calls = []

    def measured(search, roles):
        if getattr(search, "frontier_search", False):
            calls.append(tuple(role.id for role in roles))
        return original(search, roles)

    monkeypatch.setattr(_Search, "loadouts", measured)
    result = run(
        [weapon(1, "slash"), weapon(2, "slash", 40)],
        (RoleConfig(id="a", style="slash"),),
        secondary_priority="accuracy",
        max_swaps=2,
    )
    assert result["selected_solution"]
    assert calls == [("a",)]
