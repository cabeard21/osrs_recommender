"""Opt-in completed-solution refinement against independent finite enumeration."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from tools.benchmark_gear_desktop import without_observations
from tools.gear_retention_oracle import _case, exhaustive, tiny_cases, validate_solution
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.optimizer import _solution_key, optimize


def run(case, **kwargs):
    return optimize(
        case.snapshot, case.request, case.catalog, case.content, case.prices, case.at, **kwargs
    )


def stable(result):
    diagnostic = result["search"].get("local_refinement", {})
    return {
        **result,
        "search": {
            **result["search"],
            "local_refinement": {k: v for k, v in diagnostic.items() if k != "duration_seconds"},
        },
    }


def assert_legal_no_worse(case, baseline, result):
    assert result["search"]["explored_nodes"] == baseline["search"]["explored_nodes"]
    assert result["search"]["candidate_pool_sizes"] == baseline["search"]["candidate_pool_sizes"]
    for before, after in zip(baseline["curve"], result["curve"], strict=True):
        if before["solution"] is not None:
            assert after["solution"] is not None
            assert _solution_key(after["solution"]) <= _solution_key(before["solution"])
        if after["solution"] is not None:
            assert after["solution"]["maximum_actions"] <= after["swap_limit"]
            assert validate_solution(case, after["solution"])["valid"]
    if baseline["unrestricted"] is not None:
        assert _solution_key(result["unrestricted"]) <= _solution_key(baseline["unrestricted"])
    if result["unrestricted"] is not None:
        assert validate_solution(case, result["unrestricted"])["valid"]


@pytest.mark.parametrize("case", tiny_cases(), ids=lambda c: c.name)
def test_complete_validation_and_independent_exhaustive_reference(case, monkeypatch):
    # Keep the deliberately pruned baseline that refinement is meant to recover.
    monkeypatch.setattr("tracker.gear.optimizer.CANDIDATES_PER_SLOT", 12)
    monkeypatch.setattr("tracker.gear.optimizer.BEAM_WIDTH", 128)
    baseline = run(case)
    assert without_observations(baseline) == without_observations(run(case, local_refinement=False))
    result = run(case, local_refinement=True)
    assert_legal_no_worse(case, baseline, result)
    diagnostic = result["search"]["local_refinement"]
    assert diagnostic["baseline"] == {
        "curve_solutions": [p["solution"] for p in baseline["curve"]],
        "unrestricted": baseline["unrestricted"],
    }
    assert diagnostic["assignment_attempts"] <= diagnostic["work_budget"] <= 10000
    reference = exhaustive(case)
    for after, expected in zip(result["curve"], reference["curve"], strict=True):
        if after["solution"] is None:
            assert expected["score"] is None
        else:
            assert after["solution"]["score"] == pytest.approx(expected["score"])
    if case.name in {"breakpoint", "double_breakpoint"}:
        selected = result["selected_solution"]
        assert selected["loadouts"]["slash"]["performance"]["max_hit"] == 9
        assert selected["score"] > baseline["selected_solution"]["score"]


@pytest.mark.parametrize("budget", [99, 100, 101])
def test_joint_purchase_union_with_tight_budget(budget):
    original = next(c for c in tiny_cases() if c.name == "budget_union")
    case = replace(original, request=original.request.model_copy(update={"budget_gp": budget}))
    baseline = run(case)
    result = run(case, local_refinement=True)
    assert_legal_no_worse(case, baseline, result)
    solution = result["selected_solution"]
    assert solution["purchase_cost_gp"] <= budget
    assert len(solution["purchases"]) == len({p["item_id"] for p in solution["purchases"]})
    assert solution["score"] == pytest.approx(exhaustive(case)["curve"][-1]["score"])


@pytest.mark.parametrize("reserved", [26, 27, 28])
@pytest.mark.parametrize("edge", [("a", "b"), ("b", "a")])
def test_directed_handedness_and_transient_inventory(reserved, edge):
    original = next(c for c in tiny_cases() if c.name == "hands")
    case = replace(
        original,
        request=original.request.model_copy(
            update={"transitions": (edge,), "reserved_supply_slots": reserved, "max_swaps": 2}
        ),
    )
    baseline = run(case)
    result = run(case, local_refinement=True)
    assert_legal_no_worse(case, baseline, result)
    expected = exhaustive(case)["curve"][-1]
    if expected["score"] is None:
        assert result["selected_solution"] is None
    else:
        assert result["selected_solution"]["score"] == pytest.approx(expected["score"])
        assert result["selected_solution"]["max_gear_inventory_slots"] <= 28 - reserved


@pytest.mark.parametrize("change", ["excluded", "unknown_requirements", "unmet", "unsupported"])
def test_unsupported_or_ineligible_omitted_candidates_remain_blocked(change):
    from tracker.content.requirements import SkillLeaf

    case = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    if change == "excluded":
        case = replace(case, request=case.request.model_copy(update={"excluded_item_ids": (12,)}))
    else:
        updates = {
            "unknown_requirements": {"requirements_complete": False},
            "unmet": {"requires": SkillLeaf(skill="defence", level=99)},
            "unsupported": {"unsupported_effects": ("unmodeled effect",)},
        }
        items = {
            **case.catalog.items,
            12: case.catalog.items[12].model_copy(update=updates[change]),
        }
        case = replace(case, catalog=EquipmentCatalog(items))
    result = run(case, local_refinement=True)
    for row in result["curve"]:
        if row["solution"] is not None:
            assert 12 not in row["solution"]["carried_item_ids"]
            assert validate_solution(case, row["solution"])["valid"]


def test_hypothetical_eligibility_and_ownership_preserve_snapshot():
    from tracker.content.loader import Content
    from tracker.content.requirements import parse
    from tracker.content.schema import Quest, Skill

    original = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    snapshot = replace(
        original.snapshot,
        observed_items={k: v for k, v in original.snapshot.observed_items.items() if k[0] != 12},
    )
    fingerprint = snapshot.fingerprint
    head = original.catalog.items[12].model_copy(
        update={"requires": parse({"all_of": [{"skill": {"defence": 90}}, {"quest": "trial"}]})}
    )
    case = replace(
        original,
        snapshot=snapshot,
        request=original.request.model_copy(
            update={
                "mode": "future",
                "assumed_item_ids": (12,),
                "skill_overrides": {"defence": 90},
                "quest_overrides": {"trial": "complete"},
            }
        ),
        catalog=EquipmentCatalog({**original.catalog.items, 12: head}),
        content=Content(
            skills={k: Skill(id=k, name=k) for k in snapshot.skills},
            quests={"trial": Quest(id="trial", name="Trial")},
        ),
    )
    result = run(case, local_refinement=True)
    assert result["selected_solution"]["loadouts"]["slash"]["equipment"]["head"] == 12
    assert result["selected_solution"]["purchases"] == []
    assert validate_solution(case, result["selected_solution"])["valid"]
    assert snapshot.fingerprint == fingerprint
    assert snapshot.skills["defence"].level == 70 and "trial" not in snapshot.quests


def test_empty_incumbents_are_preserved_when_no_feasible_weapon_exists():
    original = next(c for c in tiny_cases() if c.name == "breakpoint")
    case = _case(
        "no_weapon",
        list(original.catalog.items.values()),
        original.request.roles,
        owned=set(original.catalog.items) - {100},
        max_swaps=0,
    )
    result = run(case, local_refinement=True)
    assert result["selected_solution"] is result["unrestricted"] is None
    assert result["search"]["local_refinement"]["assignment_attempts"] == 0


def test_cancellation_propagates_during_local_refinement(monkeypatch):
    from tracker.gear import optimizer

    original = optimizer.refine_completed
    refining = False

    def refinement(*args, **kwargs):
        nonlocal refining
        refining = True
        return original(*args, **kwargs)

    monkeypatch.setattr(optimizer, "refine_completed", refinement)
    with pytest.raises(ValueError, match="optimization_cancelled"):
        run(tiny_cases()[0], local_refinement=True, cancelled=lambda: refining)


def test_frozen_inputs_are_deterministic_and_concurrent_searches_are_isolated():
    case = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    expected = stable(run(case, local_refinement=True))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: stable(run(case, local_refinement=True)), range(4)))
    assert all(result == expected for result in results)


def test_targeted_head_experiment_remains_independent_and_composable():
    case = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    targeted = run(case, targeted_head_refinement=True)
    combined = run(case, targeted_head_refinement=True, local_refinement=True)
    assert_legal_no_worse(case, targeted, combined)
    assert (
        combined["search"]["targeted_head_refinement"]["baseline"]
        == targeted["search"]["targeted_head_refinement"]["baseline"]
    )
    assert combined["selected_solution"]["score"] == pytest.approx(
        exhaustive(case)["unrestricted"]["score"]
    )
