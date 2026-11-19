"""Loose spell runes constrain Wilderness gear and concrete attack choices."""

from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tests.gear.test_wilderness_ammunition import equipment_case
from tracker.gear.objective_store import close_result_archives
from tracker.gear.objectives import ObjectiveDescriptor
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig
from tracker.gear.service import GearService
from tracker.integrations.prices.client import PriceDTO, PriceSource


def magic_case():
    snapshot, catalog, prices = equipment_case()
    staff = weapon(
        30070, "magic", spell_compatibility=("water_wave", "water_strike"), tradeable=True
    )
    quotes = {
        i: PriceDTO(
            item_id=i,
            high_price_gp=gp,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source=PriceSource.LIVE,
            provider="test",
        )
        for i, gp in {555: 5, 556: 5, 558: 10, 565: 200}.items()
    }
    return (
        snapshot,
        SimpleNamespace(items={30070: staff}, version=catalog.version),
        {**prices, **quotes},
    )


@pytest.mark.parametrize("native", [False, True])
def test_unaffordable_spell_falls_back_to_the_allowed_cheaper_spell(make_content, native):
    if native:
        pytest.importorskip("tracker.gear.native._stages")
    snapshot, catalog, prices = magic_case()
    # For these prices 10 Water Strikes cost 200 GP, while 10 Water Waves cost 2,600.
    request = OptimizationRequest(
        roles=(
            RoleConfig(
                id="magic",
                style="magic",
                spell="water_wave",
                locks={"weapon": 30070},
                combat_options=CombatOptionFilters(
                    attack_types=("magic",),
                    stances=("accurate",),
                    spells=("water_wave", "water_strike"),
                ),
            ),
        ),
        objectives=(ObjectiveDescriptor(kind="accuracy"),),
        max_swaps=0,
        wilderness={"skulled": True, "protect_item": True, "max_loss_gp": 200, "spell_casts": 10},
    )
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
        solution = result["selected_solution"]
        assert solution["loadouts"]["magic"]["combat_option"]["spell"] == "water_strike"
        risk = solution["wilderness_risk"]
        assert risk["loss_gp"] == 200
        assert risk["without_protect_item_gp"] == 10_000_200
        assert {
            q["resource_id"]: q["quantity"] for q in risk["quantities"] if q["kind"] == "rune"
        } == {
            555: 10,
            556: 10,
            558: 10,
        }
        for group in result["objective_frontiers"]:
            for point in group["points"]:
                assert point["solution"]["wilderness_risk"]["loss_gp"] <= 200
        if native:
            assert service.native_diagnostics["native_requests"] > 0
            assert service.native_diagnostics["fallback_requests"] == 0
    finally:
        close_result_archives(result)
