"""A four-weapon catalog with an independently enumerable Wilderness frontier."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tests.gear.test_wilderness_optimization import scenario
from tracker.gear.objective_store import close_result_archives
from tracker.gear.optimizer import OptimizationRequest, optimize


@pytest.mark.parametrize(
    ("cap", "expected"), [(None, {4151, 4587}), (60_000, {4587}), (59_999, set())]
)
@pytest.mark.parametrize("with_running_cost", [False, True])
def test_loss_frontier_and_baseline_exclude_unknown_and_dominated_weapons(
    make_content, cap, expected, with_running_cost
):
    snapshot, catalog, prices = scenario(owned=(4151, 4587, 1323, 1333))
    catalog = SimpleNamespace(
        version=catalog.version,
        items={
            **catalog.items,
            1323: weapon(1323, "slash", 12, tradeable=True),
            1333: weapon(1333, "slash", 200, tradeable=True),
        },
    )
    prices[1323] = replace(prices[4151], item_id=1323)
    objectives = [{"kind": "wilderness_loss_gp"}]
    if with_running_cost:
        objectives.append({"kind": "gp_per_damage"})
    request = OptimizationRequest.model_validate(
        {
            "roles": [{"id": "melee", "style": "slash"}],
            "mode": "owned",
            "wilderness": {"skulled": True, "max_loss_gp": cap},
            "objectives": objectives,
            "max_dps_loss_pct": 100,
        }
    )
    result = optimize(snapshot, request, catalog, make_content(), prices, NOW)
    try:
        group = next(g for g in result["objective_frontiers"] if g["swap_limit"] is None)
        solutions = [p["solution"] for p in group["points"]]
        assert {s["loadouts"]["melee"]["equipment"]["weapon"] for s in solutions} == expected
        for solution in solutions:
            assert (
                solution["objective_values"]["wilderness_loss_gp"]
                == solution["wilderness_risk"]["loss_gp"]
            )
        winner = result["selected_solution"]
        if expected:
            assert winner["loadouts"]["melee"]["equipment"]["weapon"] == (
                4151 if 4151 in expected else 4587
            )
            assert group["baseline_dps"] == winner["score"]
        else:
            assert winner is None
    finally:
        close_result_archives(result)
