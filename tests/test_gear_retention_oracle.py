"""Independent finite-catalog correctness reference for retention experiments."""

from copy import deepcopy
from dataclasses import replace

import pytest

from tools.gear_retention_oracle import (
    exhaustive,
    tiny_cases,
    transition_metrics,
    validate_solution,
)
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.optimizer import optimize


def test_breakpoint_reference_enumerates_the_omitted_head():
    case = tiny_cases()[0]
    result = exhaustive(case)
    best = result["curve"][0]
    assert best["max_hits"] == {"slash": 9}
    assert best["loadouts"]["slash"]["head"] == 12
    assert best["loadouts"]["slash"]["cape"] == 20
    assert result["assignments"] == 26


@pytest.mark.parametrize("case", tiny_cases(), ids=lambda c: c.name)
def test_oracle_is_deterministic_and_curves_are_monotonic(case):
    first = exhaustive(case)
    assert first == exhaustive(case)
    scores = [p["score"] for p in first["curve"] if p["score"] is not None]
    assert scores == sorted(scores)
    for point in first["curve"]:
        if point["score"] is not None:
            assert point["maximum_actions"] <= point["swap_limit"]
            assert point["purchase_cost_gp"] <= case.request.budget_gp
            assert point["max_gear_inventory_slots"] <= 28 - case.request.reserved_supply_slots


def test_independent_hand_transitions_and_capacity():
    case = next(c for c in tiny_cases() if c.name == "hands")
    items = case.catalog.items
    assert transition_metrics(
        {"weapon": 100}, {"weapon": 101, "shield": 30}, items, {100, 101, 30}, 2
    ) == (2, 2)
    assert transition_metrics(
        {"weapon": 101, "shield": 30}, {"weapon": 100}, items, {100, 101, 30}, 2
    ) == (1, 2)
    assert (
        transition_metrics({"weapon": 100}, {"weapon": 101, "shield": 30}, items, {100, 101, 30}, 1)
        is None
    )


def test_exact_budget_purchase_union_and_explicit_empty_lock():
    case = next(c for c in tiny_cases() if c.name == "budget_union")
    best = exhaustive(case)["curve"][-1]
    assert best["purchase_cost_gp"] == 100
    assert best["carried_item_ids"] == [10, 100, 101]
    assert best["loadouts"]["m"]["head"] == best["loadouts"]["r"]["head"] == 10
    request = case.request.model_copy(update={"locks": {"head": None}})
    empty = exhaustive(replace(case, request=request))["curve"][-1]
    assert all("head" not in e for e in empty["loadouts"].values())


def test_oracle_does_not_use_production_search(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("production search called")

    monkeypatch.setattr("tracker.gear.optimizer._Search", forbidden)
    assert exhaustive(tiny_cases()[0])["unrestricted"]["score"] > 0


@pytest.mark.parametrize("case", tiny_cases(), ids=lambda c: c.name)
def test_complete_optimizer_solutions_pass_independent_validation(case):
    answer = optimize(case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    for solution in [answer["unrestricted"], *(p["solution"] for p in answer["curve"])]:
        if solution:
            result = validate_solution(case, solution)
            assert result["valid"], result["errors"]


def test_validation_rejects_corrupt_score_cost_and_locks():
    case = next(c for c in tiny_cases() if c.name == "budget_union")
    answer = optimize(case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    solution = {
        **answer["selected_solution"],
        "score": -1,
        "purchase_cost_gp": 999,
        "purchases": [],
        "carried_item_ids": [],
    }
    result = validate_solution(case, solution)
    assert not result["valid"]
    assert set(result["errors"]) == {
        "incorrect purchase union cost",
        "incorrect purchase IDs",
        "incorrect weighted score",
        "incorrect carried union",
    }


def test_equal_stats_are_distinct_purchases_and_actions():
    case = next(c for c in tiny_cases() if c.name == "identity_equal")
    answer = exhaustive(case)
    assert answer["curve"][1]["score"] is None
    assert answer["curve"][2]["purchase_cost_gp"] == 200
    assert answer["curve"][2]["carried_item_ids"] == [10, 13, 100, 101]


def test_future_projection_and_assumed_identity_match_exact_evaluation_without_mutation():
    from tracker.content.loader import Content
    from tracker.content.requirements import parse
    from tracker.content.schema import Quest, Skill
    from tracker.gear.catalog import EquipmentCatalog

    case = tiny_cases()[0]
    original_fingerprint = case.snapshot.fingerprint
    weapon = case.catalog.items[100].model_copy(
        update={"requires": parse({"all_of": [{"skill": {"attack": 80}}, {"quest": "trial"}]})}
    )
    catalog = EquipmentCatalog({**case.catalog.items, 100: weapon})
    snapshot = replace(
        case.snapshot,
        observed_items={k: v for k, v in case.snapshot.observed_items.items() if k[0] != 12},
    )
    content = Content(
        skills={k: Skill(id=k, name=k) for k in snapshot.skills},
        quests={"trial": Quest(id="trial", name="Trial")},
    )
    request = case.request.model_copy(
        update={
            "mode": "future",
            "skill_overrides": {"attack": 80, "strength": 80},
            "quest_overrides": {"trial": "complete"},
            "assumed_item_ids": (12,),
            "locks": {"head": 12, "cape": 20},
        }
    )
    future = replace(case, snapshot=snapshot, request=request, catalog=catalog, content=content)
    reference = exhaustive(future)["unrestricted"]
    assert reference["loadouts"]["slash"] == {"weapon": 100, "head": 12, "cape": 20}
    assert reference["purchased_item_ids"] == []
    assert reference["purchase_cost_gp"] == 0
    expected = evaluate_equipment(
        reference["loadouts"]["slash"],
        catalog.items,
        request.roles[0],
        {**{k: v.level for k, v in snapshot.skills.items()}, "attack": 80, "strength": 80},
    )
    assert reference["score"] == expected.dps
    answer = optimize(snapshot, request, catalog, content, case.prices, case.at)
    checked = validate_solution(future, answer["selected_solution"])
    assert checked["valid"], checked["errors"]
    assert answer["selected_solution"]["score"] == reference["score"]
    for changes in (
        {"quest_overrides": {}},
        {"skill_overrides": {"attack": 79, "strength": 80}},
    ):
        gated = replace(future, request=request.model_copy(update=changes))
        assert exhaustive(gated)["unrestricted"] is None
    assert snapshot.skills["attack"].level == 70
    assert "trial" not in snapshot.quests
    assert all(k[0] != 12 for k in snapshot.observed_items)
    assert case.snapshot.fingerprint == original_fingerprint


@pytest.mark.parametrize("field", ["cost_gp", "conditional"])
def test_validator_rejects_corrupt_purchase_row(field):
    case = next(c for c in tiny_cases() if c.name == "budget_union")
    answer = optimize(case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    solution = deepcopy(answer["selected_solution"])
    assert solution["purchases"]
    solution["purchases"][0][field] = 999 if field == "cost_gp" else True
    result = validate_solution(case, solution)
    assert not result["valid"]
    assert "incorrect purchase facts" in result["errors"]


@pytest.mark.parametrize(
    "field",
    [
        "maximum_actions",
        "max_gear_inventory_slots",
        "gear_inventory_slots",
        "remaining_supply_slots",
        "remaining_inventory_slots",
        "reserved_supply_slots",
        "distinct_items",
    ],
)
def test_validator_rejects_corrupt_global_result_facts(field):
    case = next(c for c in tiny_cases() if c.name == "hands")
    answer = optimize(case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    solution = deepcopy(answer["selected_solution"])
    solution[field] += 1
    result = validate_solution(case, solution)
    assert not result["valid"]
    assert f"incorrect {field}" in result["errors"]


def test_two_omitted_slots_require_a_complementary_replacement():
    case = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    reference = exhaustive(case)
    baseline = optimize(
        case.snapshot, case.request, case.catalog, case.content, case.prices, case.at
    )
    assert reference["curve"][0]["max_hits"] == {"slash": 9}
    assert reference["curve"][0]["loadouts"]["slash"] == {"weapon": 100, "head": 12, "cape": 32}
    original = baseline["selected_solution"]["loadouts"]["slash"]
    assert original["performance"]["max_hit"] == 8
    levels = {k: v.level for k, v in case.snapshot.skills.items()}
    for slot, item_id in (("head", 12), ("cape", 32)):
        single = {**original["equipment"], slot: item_id}
        assert (
            evaluate_equipment(single, case.catalog.items, case.request.roles[0], levels).max_hit
            == 8
        )
