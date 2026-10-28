"""Research strategies never change the production search class permanently."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tools.assess_gear_retention import semantic_response
from tools.gear_retention_strategies import STRATEGIES, run
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear import optimizer
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig


def breakpoint_case(reverse=False):
    at = datetime(2026, 10, 19, tzinfo=UTC)
    items = [
        EquipmentDefinition(
            id=100,
            name="weapon",
            slot="weapon",
            attack_styles=("slash",),
            requirements_complete=True,
        ),
        *[
            EquipmentDefinition(
                id=i,
                name=str(i),
                slot="head",
                requirements_complete=True,
                bonuses=EquipmentBonuses(melee_strength=3 if i == 12 else 0),
            )
            for i in range(1, 13)
        ],
        EquipmentDefinition(
            id=20,
            name="cape",
            slot="cape",
            requirements_complete=True,
            bonuses=EquipmentBonuses(melee_strength=3),
        ),
    ]
    if reverse:
        items.reverse()
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            k: SkillState(70, None, Source.MANUAL, at)
            for k in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", at)
            for i in items
        },
    )
    return SimpleNamespace(
        snapshot=snapshot,
        request=OptimizationRequest(
            roles=(RoleConfig(id="slash", style="slash"),), mode="owned", max_swaps=0
        ),
        catalog=EquipmentCatalog({i.id: i for i in items}),
        content=Content(),
        prices={},
        at=at,
    )


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_breakpoint_and_determinism(strategy):
    original = optimizer._Search
    result = run(breakpoint_case(), strategy)
    assert optimizer._Search is original
    assert semantic_response(result) == semantic_response(run(breakpoint_case(True), strategy))
    hit = result["selected_solution"]["loadouts"]["slash"]["performance"]["max_hit"]
    assert hit == (8 if strategy == "baseline" else 9)
    assert result["research"]["performance_evaluations"] > 0


def test_refinement_preserves_every_incumbent():
    baseline = run(breakpoint_case(), "baseline")
    refined = run(breakpoint_case(), "refinement")
    assert refined["selected_solution"]["score"] > baseline["selected_solution"]["score"]
    assert refined["research"]["refinement_assignments"] > 0
    assert refined["search"] == baseline["search"]
    capped = run(breakpoint_case(), "refinement", refinement_limit=0)
    assert capped["curve"] == baseline["curve"]


def test_invalid_strategy_does_not_patch():
    original = optimizer._Search
    with pytest.raises(ValueError):
        run(breakpoint_case(), "invalid")
    with pytest.raises(ValueError):
        run(breakpoint_case(), "refinement", refinement_limit=-1)
    assert optimizer._Search is original


def test_targeted_uses_original_pools_and_keeps_nodes_separate():
    case = breakpoint_case()
    baseline = run(case, "baseline")
    targeted = run(case, "targeted")
    assert targeted["research"]["pools"] == baseline["research"]["pools"]
    assert targeted["search"]["explored_nodes"] == baseline["search"]["explored_nodes"]
    assert targeted["selected_solution"]["score"] > baseline["selected_solution"]["score"]
    assert targeted["research"]["refinement_duration_seconds"] >= 0
    assert targeted["research"]["refinement_assignments"] > 0


def test_exception_restores_search(monkeypatch):
    original = optimizer._Search

    def fail(*args, **kwargs):
        raise RuntimeError("expected")

    monkeypatch.setattr(optimizer, "optimize", fail)
    with pytest.raises(RuntimeError, match="expected"):
        run(breakpoint_case(), "all")
    assert optimizer._Search is original


def test_joint_refinement_and_protected_identity():
    from tools.gear_retention_oracle import tiny_cases

    for case in tiny_cases():
        baseline = run(case, "baseline")
        refined = run(case, "refinement", refinement_limit=64)
        assert len(refined["curve"]) == len(baseline["curve"])
        for before, after in zip(baseline["curve"], refined["curve"], strict=True):
            if before["solution"] is not None:
                assert after["solution"] is not None
                assert optimizer._solution_key(after["solution"]) <= optimizer._solution_key(
                    before["solution"]
                )
        assert refined["research"]["refinement_assignments"] <= 64
        if case.name == "identity_lock":
            pareto = run(case, "pareto")
            assert 10 in pareto["research"]["pools"]["head"]
            assert pareto["selected_solution"]["loadouts"]["m"]["equipment"]["head"] == 10
        if len(case.request.roles) > 1:
            assert any(r["stage"] == "joint" for r in baseline["research"]["stage_runs"])


def test_baseline_is_exact_production_response_and_node_bound(monkeypatch):
    case = breakpoint_case()
    expected = optimizer.optimize(
        case.snapshot, case.request, case.catalog, case.content, case.prices, case.at
    )
    result = run(case, "baseline")
    assert {k: v for k, v in result.items() if k != "research"} == expected
    monkeypatch.setattr(optimizer, "MAX_EXPANSIONS", 10)
    bounded = run(case, "all")
    assert bounded["search"]["termination_reason"] == "node_limit"
    assert bounded["search"]["explored_nodes"] == 10


def test_role_width_ablation_is_scoped_and_cannot_recover_missing_pool_item():
    original = optimizer.BEAM_WIDTH
    baseline = run(breakpoint_case(), "baseline", role_beam_width=10000)
    assert baseline["selected_solution"]["loadouts"]["slash"]["performance"]["max_hit"] == 8
    all_items = run(breakpoint_case(), "all", role_beam_width=1)
    assert all_items["selected_solution"]["loadouts"]["slash"]["performance"]["max_hit"] == 9
    assert optimizer.BEAM_WIDTH == original
    with pytest.raises(ValueError):
        run(breakpoint_case(), "all", role_beam_width=0)
