from datetime import UTC, datetime

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.domain.types import SkillState, Source
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _Search


def fact(price, *, owned=False, exempt=False):
    return {
        "wear": {"status": "satisfied"},
        "ownership": {"status": "owned" if owned else "unknown"},
        "acquisition": "tradeable",
        "budget_exempt": exempt,
        "price": {"amount_gp": price},
    }


def search_for(facts, *, budget=0, assumed=(), locks=None, prepared=False, roles=None):
    items = {
        i: EquipmentDefinition(id=i, name=str(i), slot="weapon", attack_styles=("slash",))
        for i in facts
    }
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            skill: SkillState(70, None, Source.MANUAL, datetime.now(UTC))
            for skill in ("attack", "strength")
        },
    )
    request = OptimizationRequest(
        roles=roles or (RoleConfig(id="melee", style="slash", locks=locks or {}),),
        budget_gp=budget,
        assumed_item_ids=assumed,
        mode="future" if assumed else "usable",
    )
    return _Search(snapshot, request, items, facts, None, items if prepared else None)


@pytest.mark.parametrize("prepared", [False, True])
def test_unaffordable_items_are_removed_before_combat_marginal_scoring(monkeypatch, prepared):
    facts = {1: fact(0), 2: fact(1), 3: fact(1000000)}
    original = _Search.performance
    scored = []

    def count(search, equipment, role):
        scored.extend(equipment.values())
        return original(search, equipment, role)

    monkeypatch.setattr(_Search, "performance", count)
    search = search_for(facts, prepared=prepared)
    assert set(scored) == {1}
    assert set(search.eligible) == {1}
    assert set(search.items) == set(search.facts) == {1, 2, 3}
    assert search.facts is facts


@pytest.mark.parametrize("prepared", [False, True])
def test_pruning_preserves_free_owned_assumed_exempt_and_exact_budget_items(prepared):
    facts = {
        1: fact(0),
        2: fact(999999, owned=True),
        3: fact(999999),
        4: fact(999999, exempt=True),
        5: fact(10),
        6: fact(11),
        7: fact(None, exempt=True),
    }
    search = search_for(facts, budget=10, assumed=(3,), prepared=prepared)
    assert set(search.eligible) == {1, 2, 3, 4, 5, 7}
    assert search.cost({2, 3, 4, 7}) == 0


def test_pruned_over_budget_lock_remains_infeasible():
    search = search_for({1: fact(0), 2: fact(1)}, locks={"weapon": 2})
    assert search.loadouts(search.request.roles) == []


def test_shared_item_is_affordable_when_purchased_once_for_multiple_roles():
    roles = (
        RoleConfig(id="one", style="slash"),
        RoleConfig(id="two", style="slash"),
    )
    search = search_for({1: fact(10), 2: fact(11)}, budget=10, roles=roles)
    assert set(search.eligible) == {1}
    solution = search.solution({"one": {"weapon": 1}, "two": {"weapon": 1}}, 0)
    assert solution is not None
    assert solution["purchase_cost_gp"] == 10
    assert len(solution["purchases"]) == 1
