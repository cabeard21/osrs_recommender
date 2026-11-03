"""Portable real-account regressions retained by bounded Thorough search."""

import pytest

from tools.benchmark_gear_search_quality import benchmark_case
from tools.gear_retention_oracle import validate_solution
from tools.gear_search_quality_fixture import load_case
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import _Search, _solution_key, optimize


@pytest.fixture(autouse=True)
def original_baseline_limits(monkeypatch):
    # These witnesses describe omissions under the original bounded search.
    monkeypatch.setattr("tracker.gear.optimizer.CANDIDATES_PER_SLOT", 12)
    monkeypatch.setattr("tracker.gear.optimizer.BEAM_WIDTH", 128)
    monkeypatch.setattr("tracker.gear.optimizer.MAX_EXPANSIONS", 1_000_000)


def run(case, thorough=False):
    return optimize(
        case.snapshot,
        case.request,
        case.catalog,
        case.content,
        case.prices,
        case.at,
        local_refinement=thorough,
    )


def assert_complete_no_worse(case, before, after):
    assert after["search"]["explored_nodes"] == before["search"]["explored_nodes"]
    assert after["search"]["candidate_pool_sizes"] == before["search"]["candidate_pool_sizes"]
    diagnostic = after["search"]["local_refinement"]
    assert diagnostic["baseline"]["curve_solutions"] == [p["solution"] for p in before["curve"]]
    assert diagnostic["baseline"]["unrestricted"] == before["unrestricted"]
    assert diagnostic["assignment_attempts"] <= diagnostic["work_budget"] == 10000
    for old, new in zip(before["curve"], after["curve"], strict=True):
        if old["solution"]:
            assert new["solution"]
            assert _solution_key(new["solution"]) <= _solution_key(old["solution"])
        if new["solution"]:
            assert new["solution"]["maximum_actions"] <= new["swap_limit"]
            assert validate_solution(case, new["solution"])["valid"]
    assert _solution_key(after["unrestricted"]) <= _solution_key(before["unrestricted"])
    assert validate_solution(case, after["unrestricted"])["valid"]


def test_expanded_catalog_slash_head_witness_and_recovery():
    case = load_case("owned_slash", fixture_name="gear_expanded_slash_account.json")
    before = run(case)
    selected = before["selected_solution"]
    assert selected["score"] == pytest.approx(2.6708655667374095)
    assert selected["loadouts"]["melee"]["equipment"]["head"] == 3753
    facts = {
        i: equipment_fact(case.snapshot, item, case.content, case.prices, case.at)
        for i, item in case.catalog.items.items()
    }
    search = _Search(case.snapshot, case.request, case.catalog.items, facts, None)
    witness = search.solution(
        {"melee": {**selected["loadouts"]["melee"]["equipment"], "head": 3751}},
        case.request.max_swaps,
    )
    assert witness is not None
    assert witness["score"] == pytest.approx(2.7955325803150433)
    assert witness["purchase_cost_gp"] == 0
    assert witness["loadouts"]["melee"]["performance"]["max_hit"] == 18
    assert validate_solution(case, witness)["valid"]
    after = run(case, True)
    assert_complete_no_worse(case, before, after)
    assert after["selected_solution"]["score"] >= witness["score"]
    assert "targeted_head_refinement" not in after["search"]


@pytest.mark.parametrize("name", ["owned_slash", "melee_1m", "melee_5m", "joint_four"])
def test_historical_recovery_preserves_complete_curve(name, frozen_account_result):
    case = load_case(name)
    before = frozen_account_result(name)
    after = frozen_account_result(name, thorough=True)
    assert_complete_no_worse(case, before, after)
    assert after["selected_solution"]["score"] > before["selected_solution"]["score"]


@pytest.mark.parametrize("name", ["owned_slash", "joint_four", "account_three", "account_four"])
def test_one_through_four_roles_keep_every_role_and_complete_constraints(
    name, frozen_account_result
):
    case = benchmark_case(name)
    before = frozen_account_result(name)
    after = frozen_account_result(name, thorough=True)
    expected_roles = {r.id for r in case.request.roles}
    assert (
        len(expected_roles)
        == ["owned_slash", "joint_four", "account_three", "account_four"].index(name) + 1
    )
    facts = {
        i: equipment_fact(case.snapshot, item, case.content, case.prices, case.at)
        for i, item in case.catalog.items.items()
    }
    validator = _Search(case.snapshot, case.request, case.catalog.items, facts, None)
    # Replay the same frozen resource-cost context used by optimize(); loadout
    # metadata participates in the deterministic final tie key.
    validator.running_prices = case.prices
    validator.running_at = case.at
    for old, new in zip(before["curve"], after["curve"], strict=True):
        if old["solution"]:
            assert new["solution"]
            assert _solution_key(new["solution"]) <= _solution_key(old["solution"])
        if new["solution"]:
            solution = new["solution"]
            assert set(solution["loadouts"]) == expected_roles
            checked = validator.solution(
                {role: row["equipment"] for role, row in solution["loadouts"].items()},
                new["swap_limit"],
            )
            assert checked is not None
            assert _solution_key(checked) == _solution_key(solution)
            assert {(t["from_role"], t["to_role"]) for t in solution["transitions"]} == {
                (a, b)
                for r in case.request.roles[1:]
                for a, b in ((case.request.roles[0].id, r.id), (r.id, case.request.roles[0].id))
            }
