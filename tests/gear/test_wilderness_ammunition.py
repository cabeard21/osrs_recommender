"""Keep unneeded ammunition out of automatic Wilderness recommendations."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tests.gear.test_wilderness_optimization import request_for, scenario
from tracker.domain.types import SkillState, Source
from tracker.gear.evaluation import evaluate_configurations
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.objective_store import close_result_archives
from tracker.gear.objectives import ObjectiveDescriptor
from tracker.gear.optimizer import RoleConfig, optimize
from tracker.gear.service import GearService


def equipment_case():
    snapshot, catalog, prices = scenario(owned=(4151, 882, 861, 22804, 30070))
    snapshot = replace(
        snapshot,
        skills={
            **snapshot.skills,
            **{skill: SkillState(70, None, Source.MANUAL, NOW) for skill in ("magic", "ranged")},
        },
    )
    items = {
        **catalog.items,
        882: EquipmentDefinition(
            id=882,
            name="Bronze arrow",
            slot="ammunition",
            ammo_type="arrow:882",
            bonuses=EquipmentBonuses(ranged_strength=7),
            requirements_complete=True,
            stackable=True,
            tradeable=True,
        ),
        861: weapon(861, "ranged", ammo_for=("arrow:882",), tradeable=True),
        22804: weapon(22804, "ranged", 30, stackable=True, tradeable=True),
        30070: weapon(30070, "magic", spell_compatibility=("water_wave",), tradeable=True),
    }
    quotes = {
        **prices,
        882: replace(prices[4151], item_id=882, high_price_gp=5),
        861: replace(prices[4151], item_id=861, high_price_gp=5_000),
        22804: replace(prices[4151], item_id=22804, high_price_gp=500),
        30070: replace(prices[4151], item_id=30070, high_price_gp=10_000_000),
    }
    return snapshot, SimpleNamespace(items=items, version=catalog.version), quotes


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    "weapon_id,style", [(4151, "slash"), (22804, "ranged"), (861, "ranged"), (30070, "magic")]
)
def test_wilderness_only_recommends_arrows_for_a_compatible_attack(
    make_content, native, weapon_id, style
):
    if native:
        pytest.importorskip("tracker.gear.native._stages")
    snapshot, catalog, prices = equipment_case()
    request = request_for(
        skulled=True,
        protect_item=True,
        budget=0,
        risk_limit=100,
        roles=(
            RoleConfig(id="chosen", style=style, spell="water_wave", locks={"weapon": weapon_id}),
        ),
    ).model_copy(update={"objectives": (ObjectiveDescriptor(kind="accuracy"),)})
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
        selected = result["selected_solution"]
        rows = [selected] + [
            point["solution"]
            for group in result["objective_frontiers"]
            for point in group["points"]
        ]
        for row in rows:
            assert row["loadouts"]["chosen"]["equipment"].get("ammunition") == (
                882 if weapon_id == 861 else None
            )
            assert any(
                quantity["resource_id"] == 882 for quantity in row["wilderness_risk"]["quantities"]
            ) == (weapon_id == 861)
        if native:
            assert service.native_diagnostics["native_requests"] > 0
            assert service.native_diagnostics["fallback_requests"] == 0
    finally:
        close_result_archives(result)


def test_wilderness_fixed_idle_arrows_cost_one_unit_without_a_quantity_recommendation(make_content):
    snapshot, catalog, prices = equipment_case()
    request = request_for(skulled=True, protect_item=True, budget=0, risk_limit=100)
    result = evaluate_configurations(
        snapshot,
        request,
        {"weapon": 4151},
        {"weapon": 4151, "ammunition": 882},
        catalog,
        make_content(),
        prices,
        NOW,
    )
    assert result["proposed"]["status"] == "valid"
    assert result["proposed"]["performance"]["dps"] == result["baseline"]["performance"]["dps"]
    risk = result["proposed"]["wilderness_risk"]
    assert risk["loss_gp"] == 5
    assert risk["quantities"] == []


def test_wilderness_switches_can_keep_ammunition_equipped_for_another_attack(make_content):
    snapshot, catalog, prices = equipment_case()
    request = request_for(
        skulled=True,
        protect_item=True,
        risk_limit=1_000_200,
        roles=(
            RoleConfig(id="melee", style="slash", locks={"weapon": 4151}),
            RoleConfig(id="bow", style="ranged", locks={"weapon": 861}),
        ),
    ).model_copy(update={"max_swaps": 1, "reserved_supply_slots": 27})
    winner = optimize(snapshot, request, catalog, make_content(), prices, NOW)["selected_solution"]
    assert winner["maximum_actions"] == 1
    assert all(row["equipment"]["ammunition"] == 882 for row in winner["loadouts"].values())
    assert winner["wilderness_risk"]["quantities"][0]["quantity"] > 1


@pytest.mark.parametrize("use_lock", [False, True], ids=["strength objective", "explicit lock"])
def test_wilderness_preserves_idle_ammunition_requested_as_gear(make_content, use_lock):
    snapshot, catalog, prices = equipment_case()
    locks = {"weapon": 4151, **({"ammunition": 882} if use_lock else {})}
    request = request_for(
        skulled=True,
        protect_item=True,
        risk_limit=100,
        roles=(RoleConfig(id="melee", style="slash", locks=locks),),
    ).model_copy(update={"secondary_priority": "default" if use_lock else "ranged_strength_bonus"})
    winner = optimize(snapshot, request, catalog, make_content(), prices, NOW)["selected_solution"]
    assert winner["loadouts"]["melee"]["equipment"]["ammunition"] == 882
    assert winner["wilderness_risk"]["loss_gp"] == 5
    assert winner["wilderness_risk"]["quantities"] == []
