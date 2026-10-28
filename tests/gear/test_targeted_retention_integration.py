"""Opt-in integration uses exact complete loadouts and preserves baseline answers."""

from dataclasses import replace

import pytest

from tools.gear_retention_oracle import exhaustive, tiny_cases, validate_solution
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.optimizer import _solution_key, optimize


def run(case, **kwargs):
    return optimize(
        case.snapshot, case.request, case.catalog, case.content, case.prices, case.at, **kwargs
    )


@pytest.mark.parametrize("case", tiny_cases(), ids=lambda c: c.name)
def test_opt_in_exhaustive_and_baseline_preservation(case):
    baseline = run(case)
    assert baseline == run(case, targeted_head_refinement=False)
    result = run(case, targeted_head_refinement=True)
    report = result["search"]["targeted_head_refinement"]
    assert result["search"]["explored_nodes"] == baseline["search"]["explored_nodes"]
    assert {
        k: v for k, v in result["search"].items() if k != "targeted_head_refinement"
    } == baseline["search"]
    oracle = exhaustive(case)
    for before, after, expected in zip(
        baseline["curve"], result["curve"], oracle["curve"], strict=True
    ):
        if before["solution"] is not None:
            assert _solution_key(after["solution"]) <= _solution_key(before["solution"])
        if after["solution"] is not None:
            assert validate_solution(case, after["solution"])["valid"]
            assert after["solution"]["score"] == pytest.approx(expected["score"])
    if case.name in {"breakpoint", "double_breakpoint"}:
        assert report["triggered"]
        assert report["eligible_omitted_item_ids"] == [12]
        assert report["baseline"]["curve_solutions"] == [p["solution"] for p in baseline["curve"]]
        assert report["baseline"]["unrestricted"] == baseline["unrestricted"]
        assert result["selected_solution"]["loadouts"]["slash"]["performance"]["max_hit"] == 9
        assert result["unrestricted"]["score"] == pytest.approx(oracle["unrestricted"]["score"])
        assert report["assignment_attempts"] <= 2000
        assert not report["work_budget_exhausted"]
        item_ids = {row["item_id"] for row in result["items"]}
        assert 12 in item_ids
        assert result["alternatives"]
    else:
        assert not report["triggered"]
        assert report["assignment_attempts"] == 0
        comparable = {**result, "search": baseline["search"]}
        assert comparable == baseline


@pytest.mark.parametrize("lock", [{"head": None}, {"head": 1}, {"cape": None}])
def test_locked_slots_remain_exact(lock):
    case = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    case = replace(case, request=case.request.model_copy(update={"locks": lock}))
    result = run(case, targeted_head_refinement=True)
    for slot, item_id in lock.items():
        assert result["selected_solution"]["loadouts"]["slash"]["equipment"].get(slot) == item_id
    assert validate_solution(case, result["selected_solution"])["valid"]
    assert result["selected_solution"]["score"] == pytest.approx(
        exhaustive(case)["unrestricted"]["score"]
    )


@pytest.mark.parametrize("change", ["excluded", "unknown_requirements", "unmet", "unsupported"])
def test_unavailable_or_unsupported_omitted_head_is_never_accepted(change):
    from tracker.content.requirements import SkillLeaf

    case = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    items = dict(case.catalog.items)
    if change == "excluded":
        case = replace(case, request=case.request.model_copy(update={"excluded_item_ids": (12,)}))
    else:
        changes = {
            "unknown_requirements": {"requirements_complete": False},
            "unmet": {"requires": SkillLeaf(skill="defence", level=99)},
            "unsupported": {"unsupported_effects": ("unmodeled effect",)},
        }
        items[12] = items[12].model_copy(update=changes[change])
        case = replace(case, catalog=EquipmentCatalog(items))
    result = run(case, targeted_head_refinement=True)
    assert result["selected_solution"]["loadouts"]["slash"]["equipment"].get("head") != 12
    assert validate_solution(case, result["selected_solution"])["valid"]


def test_integration_cancellation_during_refinement(monkeypatch):
    from tracker.gear import optimizer

    case = tiny_cases()[0]
    original = optimizer._Search.solution
    refining = False

    def solution(search, assignments, limit):
        nonlocal refining
        if assignments["slash"].get("head") == 12:
            refining = True
        return original(search, assignments, limit)

    monkeypatch.setattr(optimizer._Search, "solution", solution)
    with pytest.raises(ValueError, match="optimization_cancelled"):
        run(case, targeted_head_refinement=True, cancelled=lambda: refining)


@pytest.mark.parametrize("budget", [99, 100, 101])
def test_exact_pair_purchase_budget_and_physical_union(budget):
    from tools.gear_retention_oracle import _case

    original = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    items = [
        item.model_copy(update={"tradeable": True}) if i in (12, 32) else item
        for i, item in original.catalog.items.items()
    ]
    case = _case(
        "paid_pair",
        items,
        original.request.roles,
        owned=set(original.catalog.items) - {12, 32},
        costs={12: 40, 32: 60},
        budget_gp=budget,
        max_swaps=0,
    )
    baseline = run(case)
    result = run(case, targeted_head_refinement=True)
    solution = result["selected_solution"]
    reference = exhaustive(case)["unrestricted"]
    assert solution["score"] == pytest.approx(reference["score"])
    assert _solution_key(solution) <= _solution_key(baseline["selected_solution"])
    assert validate_solution(case, solution)["valid"]
    if budget >= 100:
        assert solution["purchase_cost_gp"] == 100
        assert solution["purchases"] == [
            {"item_id": 12, "cost_gp": 40, "conditional": False},
            {"item_id": 32, "cost_gp": 60, "conditional": False},
        ]
        assert solution["carried_item_ids"] == [12, 32, 100]
    else:
        assert solution["loadouts"]["slash"]["performance"]["max_hit"] == 8


def test_future_projection_preserves_assumptions_and_account():
    from tracker.content.loader import Content
    from tracker.content.requirements import parse
    from tracker.content.schema import Quest, Skill

    original = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    snapshot = replace(
        original.snapshot,
        observed_items={k: v for k, v in original.snapshot.observed_items.items() if k[0] != 12},
    )
    before = snapshot.fingerprint
    head = original.catalog.items[12].model_copy(
        update={"requires": parse({"all_of": [{"skill": {"defence": 90}}, {"quest": "trial"}]})}
    )
    content = Content(
        skills={k: Skill(id=k, name=k) for k in snapshot.skills},
        quests={"trial": Quest(id="trial", name="Trial")},
    )
    request = original.request.model_copy(
        update={
            "mode": "future",
            "assumed_item_ids": (12,),
            "skill_overrides": {"defence": 90},
            "quest_overrides": {"trial": "complete"},
        }
    )
    case = replace(
        original,
        snapshot=snapshot,
        request=request,
        content=content,
        catalog=EquipmentCatalog({**original.catalog.items, 12: head}),
    )
    result = run(case, targeted_head_refinement=True)
    assert result["search"]["targeted_head_refinement"]["triggered"]
    assert result["selected_solution"]["score"] == pytest.approx(
        exhaustive(case)["unrestricted"]["score"]
    )
    assert result["selected_solution"]["loadouts"]["slash"]["equipment"]["head"] == 12
    assert result["selected_solution"]["purchases"] == []
    assert validate_solution(case, result["selected_solution"])["valid"]
    assert result["assumptions"]["assumed_item_ids"] == (12,)
    assert snapshot.fingerprint == before
    assert snapshot.skills["defence"].level == 70
    assert "trial" not in snapshot.quests


@pytest.mark.parametrize("mode,tradeable", [("owned", True), ("usable", True), ("usable", False)])
def test_unowned_head_requires_supported_acquisition(mode, tradeable):
    case = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    snapshot = replace(
        case.snapshot,
        observed_items={k: v for k, v in case.snapshot.observed_items.items() if k[0] != 12},
    )
    head = case.catalog.items[12].model_copy(update={"tradeable": tradeable})
    case = replace(
        case,
        snapshot=snapshot,
        request=case.request.model_copy(update={"mode": mode}),
        catalog=EquipmentCatalog({**case.catalog.items, 12: head}),
    )
    result = run(case, targeted_head_refinement=True)
    assert not result["search"]["targeted_head_refinement"]["triggered"]
    assert result["selected_solution"]["loadouts"]["slash"]["equipment"].get("head") != 12
    assert validate_solution(case, result["selected_solution"])["valid"]


@pytest.mark.parametrize("style", ["stab", "slash", "crush"])
def test_all_supported_ordinary_melee_styles_recover_breakpoint(style):
    case = next(c for c in tiny_cases() if c.name == "double_breakpoint")
    role = case.request.roles[0].model_copy(update={"style": style})
    weapon = case.catalog.items[100].model_copy(update={"attack_styles": (style,)})
    case = replace(
        case,
        request=case.request.model_copy(update={"roles": (role,)}),
        catalog=EquipmentCatalog({**case.catalog.items, 100: weapon}),
    )
    result = run(case, targeted_head_refinement=True)
    assert result["search"]["targeted_head_refinement"]["triggered"]
    assert result["selected_solution"]["loadouts"]["slash"]["performance"]["max_hit"] == 9
    assert result["selected_solution"]["score"] == pytest.approx(
        exhaustive(case)["unrestricted"]["score"]
    )
