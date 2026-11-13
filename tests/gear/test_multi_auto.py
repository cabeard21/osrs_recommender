"""Joint automatic disciplines preserve complete concrete-search tradeoffs."""

from itertools import product

import pytest

from tests.gear.test_auto_disciplines import OPTIONS, context, without_timings
from tracker.gear.auto import branch_requests
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _solution_key, optimize
from tracker.gear.potions import PotionPolicy


def inputs(count=2, first_auto=True):
    args = list(context("magic"))
    auto = args[1].roles[0]
    roles = tuple(auto.model_copy(update={"id": f"role-{i}"}) for i in range(count))
    if not first_auto:
        roles = (roles[0].model_copy(update={"allowed_disciplines": None}), *roles[1:])
    args[1] = OptimizationRequest(
        roles=roles,
        mode="owned",
        max_swaps=1,
        secondary_priority="prayer_bonus",
        max_dps_loss_pct=100,
    )
    return args


def test_assignments_preserve_roles_and_canonical_order():
    args = inputs(4)
    branches = list(branch_requests(args[1]))
    assert len(branches) == 81
    expected = list(product(("melee", "ranged", "magic"), repeat=4))
    for (key, request), disciplines in zip(branches, expected, strict=True):
        assert key == "/".join(f"role-{i}={d}" for i, d in enumerate(disciplines))
        assert [r.id for r in request.roles] == [r.id for r in args[1].roles]
        assert all(r.allowed_disciplines is None for r in request.roles)
        assert [r.target for r in request.roles] == [r.target for r in args[1].roles]


@pytest.mark.parametrize("first_auto", [False, True])
@pytest.mark.parametrize("potions", [False, True])
def test_joint_auto_matches_concrete_oracle_at_every_cap(first_auto, potions):
    args = inputs(first_auto=first_auto)
    if potions:
        args[1] = args[1].model_copy(
            update={
                "potions": PotionPolicy(mode="optimize", allowed_ids=("super_strength", "magic"))
            }
        )
    result = optimize(*args)
    branches = [
        optimize(args[0], request, *args[2:], _complete_frontiers=True, _running_frontier=True)
        for _, request in branch_requests(args[1])
    ]
    for cap, point in enumerate(result["curve"]):
        expected = min(
            (r["curve"][cap]["solution"] for r in branches if r["curve"][cap]["solution"]),
            key=_solution_key,
        )
        assert point["solution"] == expected
    assert result.get("discipline_results", []) == []
    assert result.get("discipline_comparison", []) == []
    assert result["search"]["discipline_assignment_selection"]["branch_count"] == len(branches)
    for point in result["curve"]:
        if point["solution"]:
            assert len(point["solution"]["loadouts"]) == 2
            assert point["solution"]["maximum_actions"] <= point["swap_limit"]
    if not first_auto and not potions:
        assert result["curve"][0]["solution"]["loadouts"]["role-1"]["discipline"] == "melee"
        assert result["curve"][1]["solution"]["loadouts"]["role-1"]["discipline"] == "magic"
    assert all(
        group["baseline_dps"]
        == max(
            (g["baseline_dps"] or 0)
            for r in branches
            for g in r["secondary_frontiers"]
            if g["swap_limit"] == group["swap_limit"]
        )
        for group in result["secondary_frontiers"]
        if group["points"]
    )


def test_joint_auto_cancellation_and_incomplete_workers():
    from tracker.gear.auto import optimize_auto

    args = inputs()
    with pytest.raises(ValueError, match="optimization_cancelled"):
        optimize(*args, cancelled=lambda: True)
    with pytest.raises(ValueError, match="incomplete discipline results"):
        optimize_auto(*args, branch_runner=lambda *a, **kw: [])


def test_auto_utility_rejected_and_parent_preserved():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RoleConfig(
            id="utility", style="special", allowed_disciplines=("melee",), combat_options=OPTIONS
        )
    args = inputs()
    utility = RoleConfig(id="utility", style="special", parent_role="role-0", locks={"weapon": 1})
    args[1] = args[1].model_copy(update={"roles": (*args[1].roles, utility)})
    for _, branch in branch_requests(args[1]):
        assert branch.roles[-1] == utility


@pytest.mark.parametrize("potions", [False, True])
def test_joint_auto_pool_matches_serial(potions):
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.parallel import AutoProcessPool
    from tracker.gear.service import GearService

    args = inputs(first_auto=False)
    if potions:
        args[1] = args[1].model_copy(
            update={
                "potions": PotionPolicy(mode="optimize", allowed_ids=("super_strength", "magic"))
            }
        )
    args[2] = EquipmentCatalog(args[2].items)
    pool = AutoProcessPool(2)
    try:
        pool.start(args[3], args[2])
        service = GearService(args[3], auto_pool=pool)
        service._equipment = args[2]
        parallel = service.optimize(
            args[0], args[1], price_records=args[4], now=args[5], progress_identity="multi-auto"
        )
        assert without_timings(parallel) == without_timings(optimize(*args))
        progress = service.optimization_progress("multi-auto")
        assert progress["phase"] == "complete"
        assert progress["completed"] == progress["total"]
        assert progress["total"] >= 3
    finally:
        pool.close()


def test_auto_zulrah_placeholder_and_unavailable_assignment():
    from tracker.gear.npcs import npc_catalog, resolve_request, resolve_target

    args = inputs()
    catalog = npc_catalog()
    zulrah = next(e for e in catalog.entries.values() if e["npc_id"] == 2042)
    role = RoleConfig.model_validate(
        {
            **args[1].roles[0].model_dump(),
            "target_selection": {"key": zulrah["key"], "catalog_revision": catalog.revision},
            "target": zulrah["target"],
        }
    )
    args[1] = args[1].model_copy(update={"roles": (role, args[1].roles[1])})
    args[1] = resolve_request(args[1])
    result = optimize(*args)
    assert result["selected_solution"]["loadouts"][role.id]["discipline"] != "melee"
    unavailable = {**role.model_dump(), "allowed_disciplines": ("melee",)}
    args[1] = args[1].model_copy(
        update={"roles": (RoleConfig.model_validate(unavailable), args[1].roles[1])}
    )
    empty = optimize(*args)
    assert empty["selected_solution"] is None
    assert any("immune" in reason for reason in empty["limitations"])
    with pytest.raises(ValueError, match="immune"):
        resolve_target(role.model_copy(update={"allowed_disciplines": None}))


def test_merge_preserves_losing_assignment_tradeoffs_and_cap_specific_winners():
    from copy import deepcopy

    from tracker.gear.discipline_assignments import merge_assignment_results

    args = inputs()
    concrete = next(branch_requests(args[1]))[1]
    base = optimize(args[0], concrete, *args[2:], _complete_frontiers=True)

    def solution(score, secondary, cost, discipline):
        original = deepcopy(base["selected_solution"])
        return {
            **original,
            "score": score,
            "secondary_value": secondary,
            "loadouts": {
                key: {**loadout, "discipline": discipline}
                for key, loadout in original["loadouts"].items()
            },
            "running_cost": {"status": "known", "gp_per_damage": cost},
        }

    best = solution(100, 0, 5, "magic")
    low_cap = solution(80, 0, 5, "magic")
    tradeoff = solution(90, 20, 1, "melee")

    def branch(unrestricted, caps):
        return {
            **base,
            "unrestricted": unrestricted,
            "selected_solution": caps[-1],
            "curve": [{"solution": row} for row in caps],
            "secondary_frontiers": [
                {"swap_limit": cap, "points": [{"solution": row}]}
                for cap, row in ((0, caps[0]), (1, caps[1]), (None, unrestricted))
            ],
            "running_cost_frontiers": [
                {"swap_limit": cap, "baseline_solution": row, "points": [{"solution": row}]}
                for cap, row in ((0, caps[0]), (1, caps[1]), (None, unrestricted))
            ],
        }

    branches = [
        ("role-0=magic/role-1=magic", branch(best, [low_cap, best])),
        ("role-0=melee/role-1=melee", branch(tradeoff, [tradeoff, tradeoff])),
    ]
    request = args[1].model_copy(update={"max_dps_loss_pct": 15})
    result = merge_assignment_results(request, branches)
    assert [p["solution"]["score"] for p in result["curve"]] == [90, 100]
    for field in ("secondary_frontiers", "running_cost_frontiers"):
        group = next(g for g in result[field] if g["swap_limit"] == 1)
        assert [p["solution"]["score"] for p in group["points"]] == [100, 90]
        assert [p["dps_loss_pct"] for p in group["points"]] == [0, 10]
    filtered = merge_assignment_results(
        request.model_copy(update={"max_dps_loss_pct": 5}), branches
    )
    for field in ("secondary_frontiers", "running_cost_frontiers"):
        group = next(g for g in filtered[field] if g["swap_limit"] == 1)
        assert [p["solution"]["score"] for p in group["points"]] == [100]
    complete = merge_assignment_results(
        request.model_copy(update={"max_dps_loss_pct": 5}), branches, complete_frontiers=True
    )
    assert len(complete["running_cost_frontiers"][1]["points"]) == 2


def test_all_melee_assignment_contributes_free_running_cost_frontier():
    args = inputs()
    # Powered magic wins DPS, while all-melee needs no charge resources.
    result = optimize(*args)
    points = result["running_cost_frontiers"][-1]["points"]
    assert any(
        all(loadout["discipline"] == "melee" for loadout in p["solution"]["loadouts"].values())
        and p["solution"]["running_cost"]["gp_per_damage"] == 0
        for p in points
    )


def test_late_potion_worker_cancellation_is_not_published():
    args = inputs()
    args[1] = args[1].model_copy(update={"potions": PotionPolicy(mode="optimize")})
    stopped = [False]

    def runner(snapshot, request, catalog, content, prices, now, *, branches, **options):
        rows = [optimize(snapshot, branch, catalog, content, prices, now) for branch in branches]
        stopped[0] = True
        return rows

    with pytest.raises(ValueError, match="optimization_cancelled"):
        optimize(*args, cancelled=lambda: stopped[0], potion_branch_runner=runner)


def test_single_auto_exact_zulrah_does_not_allow_melee():
    from tracker.gear.evaluation import evaluate_configurations
    from tracker.gear.npcs import npc_catalog, resolve_request

    args = inputs()
    catalog = npc_catalog()
    zulrah = next(e for e in catalog.entries.values() if e["npc_id"] == 2042)
    role = RoleConfig.model_validate(
        {
            **args[1].roles[0].model_dump(),
            "target_selection": {"key": zulrah["key"], "catalog_revision": catalog.revision},
            "target": zulrah["target"],
        }
    )
    args[1] = resolve_request(args[1].model_copy(update={"roles": (role,)}))
    result = evaluate_configurations(*args[:2], {"weapon": 1}, {"weapon": 2}, *args[2:])
    assert result["baseline"]["status"] == "invalid"
    assert result["proposed"]["status"] == "valid"
    assert result["proposed"]["discipline"] == "ranged"
    pinned = evaluate_configurations(
        *args[:2],
        {"weapon": 1},
        {"weapon": 1},
        *args[2:],
        proposed_combat_option={
            "attack_type": "slash",
            "stance": "accurate",
            "spell": None,
            "powered_attack": None,
        },
    )
    assert pinned["proposed"]["status"] == "invalid"


def test_shared_budget_changes_individually_best_discipline():
    from dataclasses import replace
    from types import SimpleNamespace

    from tests.gear.test_optimizer import weapon
    from tracker.integrations.prices.client import PriceDTO, PriceSource

    args = inputs()
    args[0] = replace(args[0], observed_items={})
    items = [
        weapon(1, "slash", 30, tradeable=True, attack_profiles=(("slash", "accurate"),)),
        weapon(2, "ranged", 240, tradeable=True, attack_profiles=(("ranged", "rapid"),)),
    ]
    args[2] = SimpleNamespace(items={item.id: item for item in items}, version="test")
    args[4] = {
        item.id: PriceDTO(
            item_id=item.id,
            high_price_gp=100,
            high_trade_at=args[-1],
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=args[-1],
            source=PriceSource.LIVE,
            provider="test",
        )
        for item in items
    }
    auto = RoleConfig(
        id="auto", style="slash", combat_options=OPTIONS, allowed_disciplines=("melee", "ranged")
    )
    fixed = RoleConfig(id="fixed", style="slash", locks={"weapon": 1})
    args[1] = OptimizationRequest(roles=(auto,), budget_gp=100, max_swaps=1)
    assert optimize(*args)["selected_solution"]["loadouts"]["auto"]["discipline"] == "ranged"
    args[1] = OptimizationRequest(roles=(fixed, auto), budget_gp=100, max_swaps=1)
    result = optimize(*args)["selected_solution"]
    assert result["loadouts"]["auto"]["discipline"] == "melee"
    assert result["loadouts"]["auto"]["equipment"]["weapon"] == 1
    assert result["purchase_cost_gp"] == 100
    assert len(result["purchases"]) == 1
