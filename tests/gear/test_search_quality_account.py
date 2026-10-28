"""Redacted October 27 account regressions, independent of live DB/catalog edits.

The finite fixture preserves every access-eligible physical row across these four
requests. Removing unavailable rows leaves the original retained candidate pools
unchanged. Item definitions, requirement facts and cached prices are frozen.
"""

from copy import deepcopy

import pytest

from tools.gear_search_quality_fixture import fixture_data, load_case
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import _Search, _solution_key, optimize


def run(case, **kwargs):
    return optimize(
        case.snapshot, case.request, case.catalog, case.content, case.prices, case.at, **kwargs
    )


def search_for(case):
    facts = {
        i: equipment_fact(case.snapshot, item, case.content, case.prices, case.at)
        for i, item in case.catalog.items.items()
    }
    return _Search(case.snapshot, case.request, case.catalog.items, facts, None)


@pytest.mark.parametrize("name", ["owned_slash", "melee_1m", "melee_5m", "joint_four"])
def test_frozen_account_reproduces_original_baseline(name):
    case = load_case(name)
    result = run(case)
    expected = fixture_data()["expected"][name]
    assert result["selected_solution"]["score"] == pytest.approx(
        expected["score"], rel=0, abs=1e-12
    )
    assert {k: v["equipment"] for k, v in result["selected_solution"]["loadouts"].items()} == {
        k: v["equipment"] for k, v in expected["loadouts"].items()
    }


@pytest.mark.parametrize("name", ["owned_slash", "melee_1m", "melee_5m"])
def test_retained_strength_amulet_witness_passes_full_validation(name):
    case = load_case(name)
    search = search_for(case)
    assert {1725, 6585} <= set(search.pools["neck"])
    owned_equipment = fixture_data()["expected"]["owned_slash"]["loadouts"]["melee"]["equipment"]
    proposal = {"melee": {**owned_equipment, "neck": 1725}}
    exact = search.solution(proposal, case.request.max_swaps)
    assert exact is not None
    assert exact["score"] == pytest.approx(2.728201379517169, rel=0, abs=1e-12)
    assert exact["purchase_cost_gp"] == 0
    assert exact["loadouts"]["melee"]["performance"]["max_hit"] == 18
    assert (
        fixture_data()["expected"]["owned_slash"]["loadouts"]["melee"]["performance"]["max_hit"]
        == 17
    )


@pytest.mark.parametrize("name", ["melee_1m", "melee_5m"])
def test_retained_combat_bracelet_witness(name):
    case = load_case(name)
    search = search_for(case)
    assert {11126, 21736} <= set(search.pools["hands"])
    equipment = fixture_data()["expected"][name]["loadouts"]["melee"]["equipment"]
    exact = search.solution({"melee": {**equipment, "hands": 11126}}, case.request.max_swaps)
    assert exact is not None
    assert exact["score"] == pytest.approx(2.6708655667374095, rel=0, abs=1e-12)
    assert exact["purchase_cost_gp"] == 0


def test_joint_helm_witness_preserves_complete_joint_legality():
    case = load_case("joint_four")
    search = search_for(case)
    assert {3751, 3753} <= set(search.pools["head"])
    before = fixture_data()["expected"]["joint_four"]
    assignments = {k: dict(v["equipment"]) for k, v in before["loadouts"].items()}
    assignments["melee"] = {**assignments["melee"], "head": 3751}
    exact = search.solution(assignments, 4)
    assert exact is not None
    assert exact["score"] == pytest.approx(2.772721328442114, rel=0, abs=1e-12)
    assert exact["loadouts"]["ranged"] == before["loadouts"]["ranged"]
    assert exact["purchase_cost_gp"] == 0
    assert exact["maximum_actions"] <= 4
    assert exact["remaining_inventory_slots"] >= 0
    assert {(t["from_role"], t["to_role"]) for t in exact["transitions"]} == {
        ("melee", "ranged"),
        ("ranged", "melee"),
    }


@pytest.mark.parametrize("name", ["owned_slash", "melee_1m", "melee_5m", "joint_four"])
def test_opt_in_recovers_validated_account_improvement(name):
    case = load_case(name)
    baseline = run(case)
    result = run(case, local_refinement=True)
    expected = 2.772721328442114 if name == "joint_four" else 2.728201379517169
    assert result["selected_solution"]["score"] >= expected - 1e-12
    assert _solution_key(result["selected_solution"]) <= _solution_key(
        baseline["selected_solution"]
    )
    assert (
        search_for(case).solution(
            {k: v["equipment"] for k, v in result["selected_solution"]["loadouts"].items()},
            case.request.max_swaps,
        )
        is not None
    )
    assert result["search"]["explored_nodes"] == baseline["search"]["explored_nodes"]
    repeated = run(case, local_refinement=True)
    comparable = deepcopy(result)
    for response in (comparable, repeated):
        response["search"]["local_refinement"].pop("duration_seconds")
    assert comparable == repeated
