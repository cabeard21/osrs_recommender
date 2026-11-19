"""Complete Wilderness result parity through the desktop service seam."""

from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW
from tests.gear.test_wilderness_optimization import request_for, scenario
from tools.benchmark_gear_desktop import result_digest
from tracker.gear.objective_store import close_result_archives
from tracker.gear.objectives import ObjectiveDescriptor
from tracker.gear.optimizer import RoleConfig
from tracker.gear.service import GearService


@pytest.mark.parametrize("multiple", [False, True], ids=["single", "multi"])
@pytest.mark.parametrize("limits", ["legacy", "both", "purchase", "risk"])
def test_wilderness_objective_archives_match_native_without_fallback(
    make_content, multiple, limits
):
    pytest.importorskip("tracker.gear.native._stages")
    snapshot, catalog, prices = scenario()
    scimitar = catalog.items[4587]
    prayer_weapon = scimitar.model_copy(
        update={"bonuses": scimitar.bonuses.model_copy(update={"prayer": 12})}
    )
    catalog = SimpleNamespace(items={**catalog.items, 4587: prayer_weapon}, version=catalog.version)
    roles = (
        (RoleConfig(id="fixed", style="slash", locks={"weapon": 4151}),) if multiple else ()
    ) + (RoleConfig(id="flexible", style="slash"),)
    purchases = {
        "legacy": 60_000,
        "purchase": 1_000_000 if multiple else 60_000,
        "risk": 1_060_000,
        "both": 1_060_000,
    }[limits]
    risk_limit = None if limits == "legacy" else 59_999 if limits == "risk" and multiple else 60_000
    request = request_for(
        skulled=True,
        protect_item=limits != "risk" or multiple,
        budget=purchases,
        risk_limit=risk_limit,
        roles=roles,
    ).model_copy(
        update={
            "objectives": (
                ObjectiveDescriptor(kind="melee_strength_bonus"),
                ObjectiveDescriptor(kind="prayer_bonus"),
            ),
            "max_dps_loss_pct": 100,
        }
    )
    outcomes = []
    for native in (False, True):
        service = GearService(
            make_content(),
            optimization_profile="combined",
            fixed_reporting=True,
            factored_evaluation=True,
            compact_states=True,
            native_search=native,
        )
        service._equipment = catalog
        result = service.optimize(snapshot, request, price_records=prices, now=NOW)
        try:
            groups = [
                {**group, "points": list(group["points"])}
                for group in result["objective_frontiers"]
            ]
        finally:
            close_result_archives(result)
        unrestricted = next(group for group in groups if group["swap_limit"] is None)
        assert len(unrestricted["points"]) == (2 if limits in {"legacy", "both"} else 1)
        for group in groups:
            for point in group["points"]:
                solution = point["solution"]
                assert solution["wilderness_risk"]["loss_gp"] <= request.wilderness_risk_limit
                if request.purchase_budget is not None:
                    assert solution["purchase_cost_gp"] <= request.purchase_budget
        if multiple and limits in {"legacy", "both"}:
            assert {
                p["solution"]["wilderness_risk"]["loss_gp"] for p in unrestricted["points"]
            } == {
                0,
                60_000,
            }
        if native:
            diagnostics = service.native_diagnostics
            assert diagnostics["native_requests"] >= 1
            assert diagnostics["fallback_requests"] == 0
            assert any(event["event"] == "stage" for event in diagnostics["events"])
        outcomes.append(result_digest({**result, "objective_frontiers": groups}))
    assert outcomes[0] == outcomes[1]
