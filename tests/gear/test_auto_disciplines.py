from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from tests.gear.test_optimizer import run, weapon
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.evaluation import evaluate_configurations
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize

OPTIONS = CombatOptionFilters(
    attack_types=("stab", "slash", "crush", "light", "standard", "heavy", "magic"),
    stances=("accurate", "aggressive", "rapid", "defensive", "controlled", "longrange"),
    spells=(),
)


def test_auto_one_discipline_matches_manual():
    items = [weapon(1, "slash", 50, attack_profiles=(("slash", "accurate"),))]
    fixed = RoleConfig(id="a", style="slash", combat_options=OPTIONS)
    auto = RoleConfig(id="a", style="magic", allowed_disciplines=("melee",), combat_options=OPTIONS)
    manual = run(items, (fixed,), max_swaps=0)
    result = run(items, (auto,), max_swaps=0)
    assert result["selected_solution"] == manual["selected_solution"]
    assert result["selected_solution"]["loadouts"]["a"]["discipline"] == "melee"
    assert result["discipline_comparison"][0]["score"] == manual["selected_solution"]["score"]


@pytest.mark.parametrize("allowed", [(), ("melee", "melee")])
def test_auto_invalid_allowlist(allowed):
    with pytest.raises(ValidationError):
        RoleConfig(id="a", style="slash", allowed_disciplines=allowed, combat_options=OPTIONS)


def test_auto_requires_filters_and_single_role():
    with pytest.raises(ValidationError):
        RoleConfig(id="a", style="slash", allowed_disciplines=("melee",))
    auto = RoleConfig(id="a", style="slash", allowed_disciplines=("melee",), combat_options=OPTIONS)
    with pytest.raises(ValidationError):
        OptimizationRequest(roles=(auto, RoleConfig(id="b", style="ranged")))


def context(winner="melee"):
    now = datetime(2026, 11, 1, tzinfo=UTC)
    items = [
        weapon(
            1, "slash", 180 if winner == "melee" else 0, attack_profiles=(("slash", "accurate"),)
        ),
        weapon(
            2, "ranged", 240 if winner == "ranged" else 0, attack_profiles=(("ranged", "rapid"),)
        ),
        EquipmentDefinition(
            id=3,
            name="Powered",
            slot="weapon",
            requirements_complete=True,
            powered_attack="fixture",
            powered_attack_base_max_hit=65 if winner == "magic" else 1,
            powered_attack_stances=("accurate",),
        ),
    ]
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            k: SkillState(70, None, Source.MANUAL, now)
            for k in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", now)
            for i in items
        },
    )
    options = OPTIONS.model_copy(update={"spells": ("powered:3",)})
    role = RoleConfig(
        id="a",
        style="slash",
        allowed_disciplines=("melee", "ranged", "magic"),
        combat_options=options,
    )
    request = OptimizationRequest(roles=(role,), mode="owned", max_swaps=0)
    catalog = SimpleNamespace(items={i.id: i for i in items}, version="test")
    return snapshot, request, catalog, Content(), {}, now


@pytest.mark.parametrize("winner", ["melee", "ranged", "magic"])
def test_each_discipline_can_win_and_matches_manual(winner):
    args = context(winner)
    result = optimize(*args)
    assert result["selected_solution"]["loadouts"]["a"]["discipline"] == winner
    from tracker.gear.auto import branch_requests

    manual = [optimize(args[0], request, *args[2:]) for _, request in branch_requests(args[1])]
    assert result["selected_solution"]["score"] == max(
        r["selected_solution"]["score"] for r in manual
    )
    assert len(result["discipline_comparison"]) == 3
    assert result["search"]["explored_nodes"] == sum(r["search"]["explored_nodes"] for r in manual)


def test_auto_exact_evaluation_resolves_and_validates_pinned_option():
    args = context("magic")
    solution = optimize(*args)["selected_solution"]["loadouts"]["a"]
    equipment = solution["equipment"]
    result = evaluate_configurations(*args[:2], equipment, equipment, *args[2:])
    assert result["baseline"]["status"] == "valid"
    assert result["baseline"]["performance"] == solution["performance"]
    pinned = evaluate_configurations(
        *args[:2],
        equipment,
        equipment,
        *args[2:],
        baseline_combat_option=solution["combat_option"],
        proposed_combat_option={"attack_type": "invalid"},
    )
    assert pinned["baseline"]["status"] == "valid"
    assert pinned["proposed"]["status"] == "invalid"


def test_empty_filters_and_incompatible_locked_weapon():
    args = list(context())
    role = (
        args[1]
        .roles[0]
        .model_copy(update={"combat_options": OPTIONS.model_copy(update={"attack_types": ()})})
    )
    args[1] = args[1].model_copy(update={"roles": (role,)})
    result = optimize(*args)
    assert result["selected_solution"] is None
    assert all(r["status"] == "no_feasible_solution_found" for r in result["discipline_comparison"])
    assert all(r["selected_solution"] is None for r in result["discipline_results"])
    args = list(context())
    role = (
        args[1]
        .roles[0]
        .model_copy(update={"allowed_disciplines": ("ranged",), "locks": {"weapon": 1}})
    )
    args[1] = args[1].model_copy(update={"roles": (role,)})
    assert optimize(*args)["selected_solution"] is None


def test_cancellation_and_secondary_global_baseline():
    args = list(context())
    with pytest.raises(ValueError, match="optimization_cancelled"):
        optimize(*args, cancelled=lambda: True)
    args[1] = args[1].model_copy(
        update={"secondary_priority": "prayer_bonus", "max_dps_loss_pct": 5}
    )
    result = optimize(*args, local_refinement=True)
    for group in result["secondary_frontiers"]:
        assert group["baseline_dps"] == result["selected_solution"]["score"]
        assert all(p["dps_loss_pct"] <= 5 for p in group["points"])
    assert (
        result["selected_solution"] == optimize(*args, local_refinement=True)["selected_solution"]
    )


def test_auto_retains_ranged_weapon_with_required_ammunition():
    args = list(context("ranged"))
    items = dict(args[2].items)
    items[2] = items[2].model_copy(update={"ammo_for": ("arrow",)})
    items[4] = EquipmentDefinition(
        id=4, name="Arrows", slot="ammunition", ammo_type="arrow", requirements_complete=True
    )
    args[2] = SimpleNamespace(items=items, version="test")
    from dataclasses import replace

    args[0] = replace(
        args[0],
        observed_items={
            **args[0].observed_items,
            (4, Container.BANK): ObservedItemFact(4, Container.BANK, 1, "test", args[-1]),
        },
    )
    result = optimize(*args)
    assert result["selected_solution"]["loadouts"]["a"]["discipline"] == "ranged"
    assert result["selected_solution"]["loadouts"]["a"]["equipment"]["ammunition"] == 4


def test_auto_exact_evaluation_can_choose_different_disciplines_for_each_side():
    args = context("magic")
    result = evaluate_configurations(*args[:2], {"weapon": 1}, {"weapon": 3}, *args[2:])
    assert result["baseline"]["discipline"] == "melee"
    assert result["proposed"]["discipline"] == "magic"
    assert result["deltas"]["dps"] > 0


@pytest.mark.parametrize("priority", ["default", "prayer_bonus"])
def test_auto_retains_each_discipline_result(priority):
    from tracker.gear.auto import branch_requests

    args = list(context("magic"))
    args[1] = args[1].model_copy(update={"secondary_priority": priority, "max_dps_loss_pct": 5})
    result = optimize(*args)
    assert [r["discipline"] for r in result["discipline_results"]] == ["melee", "ranged", "magic"]
    for branch, (discipline, request) in zip(
        result["discipline_results"], branch_requests(args[1]), strict=True
    ):
        manual = optimize(args[0], request, *args[2:])
        assert branch["selected_solution"] == manual["selected_solution"]
        assert branch["alternatives"] == manual["alternatives"]
        # Auto also explores resource-cost alternatives in non-magic branches.
        assert {k: v for k, v in branch["search"].items() if k != "running_cost_frontier"} == {
            k: v for k, v in manual["search"].items() if k != "running_cost_frontier"
        }
        for group in branch["secondary_frontiers"]:
            assert len(group["points"]) <= 64
            assert group["baseline_dps"] == branch["selected_solution"]["score"]
            assert all(p["dps_loss_pct"] <= 5 for p in group["points"])
            assert all(p["id"].startswith(f"discipline-{discipline}-") for p in group["points"])


@pytest.mark.parametrize("visible_count", [51, 100])
def test_auto_samples_branch_frontiers_after_combining(monkeypatch, visible_count):
    import tracker.gear.optimizer as module

    original = module.optimize

    def expanded(*args, **kwargs):
        result = original(*args, **kwargs)
        return {
            **result,
            "secondary_frontiers": [
                {
                    **group,
                    "points": [
                        {
                            **group["points"][0],
                            "id": f"point-{group['swap_limit']}-{i}",
                            "dps_loss_pct": 10 if i < visible_count else 11,
                        }
                        for i in range(200)
                    ]
                    if group["points"]
                    else [],
                }
                for group in result["secondary_frontiers"]
            ],
        }

    monkeypatch.setattr(module, "optimize", expanded)
    args = list(context())
    args[1] = args[1].model_copy(update={"secondary_priority": "prayer_bonus"})
    result = original(*args)
    groups = [g for r in result["discipline_results"] for g in r["secondary_frontiers"]]
    assert groups
    for group in groups:
        assert group["sampled"] == (visible_count > 64)
        assert len(group["points"]) == min(64, visible_count)
        assert group["points"][0]["id"].endswith("-0")
        assert group["points"][-1]["id"].endswith(f"-{visible_count - 1}")
        assert all(p["dps_loss_pct"] <= 10 for p in group["points"])
    assert all(len(g["points"]) <= 64 for g in result["secondary_frontiers"])


@pytest.mark.parametrize("loss_limit", [0, 10, 100])
@pytest.mark.parametrize("priority", ["balanced_defence", "magic_ranged_defence"])
def test_auto_defence_frontiers_obey_loss_limit(loss_limit, priority):
    from tests.gear.test_secondary_priorities import armour

    items = [
        weapon(1, "slash"),
        armour(20, melee_strength=100),
        armour(30, defence_stab=100, defence_magic=40, defence_ranged=60),
    ]
    role = RoleConfig(id="a", style="slash", allowed_disciplines=("melee",), combat_options=OPTIONS)
    result = run(
        items,
        (role,),
        max_swaps=0,
        secondary_priority=priority,
        max_dps_loss_pct=loss_limit,
    )
    groups = result["discipline_results"][0]["secondary_frontiers"]
    assert groups
    for group in groups:
        assert group["points"]
        assert all(p["dps_loss_pct"] <= loss_limit for p in group["points"])
        if loss_limit == 100:
            assert any(p["dps_loss_pct"] > 10 for p in group["points"])
