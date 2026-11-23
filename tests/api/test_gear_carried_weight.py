"""Signed gear weight across browser comparisons and frozen kit previews."""

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.combat import MODEL_VERSION


@pytest.fixture
def weight_scenario(client, app, session_factory):
    gear = app.state.gear_service
    items = gear.equipment_catalog().items
    # A small ordinary-combat fixture with the worn/packed weights of a reducer.
    gear._equipment = EquipmentCatalog(
        {
            item_id: items[item_id].model_copy(
                update={"worn_weight_grams": worn, "inventory_weight_grams": packed}
            )
            for item_id, worn, packed in ((4151, -3000, 600), (1333, 1000, 1000))
        },
        revision="frozen-weight-fixture",
    )
    return {
        **scenario(client, session_factory, ids=(4151, 1333)),
        "objectives": [{"kind": "carried_weight_kg"}],
    }


def test_fixed_signed_weight_comparison(client, weight_scenario):
    response = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": weight_scenario,
            "baseline_loadouts": {"single": {"weapon": 1333}},
            "proposed_loadouts": {"single": {"weapon": 4151}},
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["baseline"]["objective_values"] == {"carried_weight_kg": 1}
    assert data["proposed"]["carried_weight"] == {
        "heaviest_kg": -3,
        "roles": {"single": {"worn_kg": -3, "backpack_kg": 0, "total_kg": -3}},
    }
    assert data["deltas"]["objective_values"] == {"carried_weight_kg": -4}


def test_fixed_missing_weight_identifies_physical_item(client, app, weight_scenario):
    gear = app.state.gear_service
    items = gear.equipment_catalog().items
    gear._equipment = EquipmentCatalog(
        {**items, 1333: items[1333].model_copy(update={"inventory_weight_grams": None})},
        revision="unmeasured-weight",
    )
    response = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": weight_scenario,
            "baseline_loadouts": {"single": {"weapon": 4151}},
            "proposed_loadouts": {"single": {"weapon": 1333}},
        },
    )
    assert response.status_code == 422, response.text
    assert "1333" in response.json()["error"]["message"]


@pytest.mark.parametrize("assume_cape", [False, True])
def test_purchasable_reducer_uses_inventory_form_in_browser_results(
    client, app, session_factory, assume_cape
):
    from datetime import UTC, datetime

    from tracker.db.models import ItemPrice, Player, SkillSnapshot
    from tracker.domain.types import PriceSourceLayer, Source

    gear = app.state.gear_service
    items = gear.equipment_catalog().items
    gear._equipment = EquipmentCatalog({i: items[i] for i in (4151, 10074)}, revision="cape-kit")
    submitted = scenario(client, session_factory)
    now = datetime.now(UTC)
    with session_factory() as session:
        session.get(Player, 1).members = True
        session.add(
            SkillSnapshot(
                player_id=1, skill="hunter", level=66, source=Source.RUNELITE, observed_at=now
            )
        )
        session.add(
            ItemPrice(
                item_id=10071,
                high_price_gp=54,
                high_trade_at=now,
                fetched_at=now,
                source=PriceSourceLayer.CACHED,
                provider="test",
            )
        )
        session.commit()
    submitted.update(
        expected_snapshot_id=client.get("/ui-api/gear/context").json()["account"]["snapshot_id"],
        locks={"weapon": 4151, "cape": 10071},
        objectives=[{"kind": "carried_weight_kg"}],
        mode="future" if assume_cape else "usable",
        assumed_item_ids=[10071] if assume_cape else [],
        budget_gp=54,
    )
    equipped = {"single": {"weapon": 4151, "cape": 10074}}
    fixed = client.post(
        "/ui-api/gear/evaluations",
        json={"scenario": submitted, "baseline_loadouts": equipped, "proposed_loadouts": equipped},
    )
    assert fixed.status_code == 200, fixed.text
    side = fixed.json()["proposed"]
    assert side["status"] == "valid", side["reasons"]
    assert [row["item_id"] for row in side["purchases"]] == ([] if assume_cape else [10071])
    optimized = client.post("/ui-api/gear/optimizations", json=submitted)
    assert optimized.status_code == 200, optimized.text
    assert (
        fixed.json()["assumptions_fingerprint"]
        == optimized.json()["result"]["assumptions_fingerprint"]
    )
    selected = optimized.json()["result"]["selected_solution"]
    assert selected["purchases"] == side["purchases"]
    assert selected["carried_weight"] == side["carried_weight"]


def test_weight_timeline_replays_full_kit_from_frozen_catalog(client, app, weight_scenario):
    submitted = {
        **weight_scenario,
        "roles": [
            {"id": "main", "style": "slash", "locks": {"weapon": 4151}},
            {"id": "spec", "style": "special", "parent_role": "main", "locks": {"weapon": 1333}},
        ],
        "max_swaps": 1,
        "potions": {"mode": "fixed", "selected_ids": ["super_strength"]},
    }
    gear = app.state.gear_service
    loadouts = {
        "main": {
            "equipment": {"weapon": 4151},
            "combat_option": {"attack_type": "slash", "stance": "accurate"},
        },
        "spec": {"equipment": {"weapon": 1333}},
    }
    direct = {
        "scenario": submitted,
        "loadouts": loadouts,
        "selected_potion_ids": ["super_strength"],
        "expected_model_version": MODEL_VERSION,
        "expected_catalog_version": gear.equipment_catalog().revision,
    }
    route = "/ui-api/gear/potion-timelines"
    assert (
        client.post(route, json={**direct, "loadouts": {"main": loadouts["main"]}}).status_code
        == 422
    )
    reply = client.post(route, json=direct)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    expected = {
        "heaviest_kg": 1.6,
        "roles": {
            "main": {"worn_kg": -3, "backpack_kg": 1, "total_kg": -2},
            "spec": {"worn_kg": 1, "backpack_kg": 0.6, "total_kg": 1.6},
        },
    }
    assert data["carried_weight"] == expected
    for row in [data["baseline"], *data["samples"]]:
        assert row["objective_values"] == {"carried_weight_kg": 1.6}
        assert row["roles"]["main"]["objective_values"] == {"carried_weight_kg": -2}
    optimized = client.post("/ui-api/gear/optimizations", json=submitted)
    assert optimized.status_code == 200, optimized.text
    result = optimized.json()
    assert result["result"]["selected_solution"]["carried_weight"] == expected
    run = result["objective_run"]
    gear._equipment = EquipmentCatalog({}, revision="new-live-catalog")
    frozen = client.post(
        route, json={"run_id": run["run_id"], "solution_id": run["selected_solution_id"]}
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json() == data


def test_weight_only_preview_enforces_wilderness_cap_on_whole_kit(
    client, app, session_factory, weight_scenario
):
    from datetime import UTC, datetime

    from tracker.db.models import ItemPrice
    from tracker.domain.types import PriceSourceLayer

    now = datetime.now(UTC)
    with session_factory() as session:
        for item_id, price in ((4151, 600), (1333, 200)):
            session.add(
                ItemPrice(
                    item_id=item_id,
                    high_price_gp=price,
                    high_trade_at=now,
                    fetched_at=now,
                    source=PriceSourceLayer.CACHED,
                    provider="test",
                )
            )
        session.commit()
    body = {
        "scenario": {
            **weight_scenario,
            "roles": [
                {"id": "main", "style": "slash"},
                {
                    "id": "spec",
                    "style": "special",
                    "parent_role": "main",
                    "locks": {"weapon": 1333},
                },
            ],
            "wilderness": {"skulled": True, "max_loss_gp": 600},
            "max_swaps": 1,
        },
        "loadouts": {
            "main": {
                "equipment": {"weapon": 4151},
                "combat_option": {"attack_type": "slash", "stance": "accurate"},
            },
            "spec": {"equipment": {"weapon": 1333}},
        },
        "selected_potion_ids": [],
        "expected_model_version": MODEL_VERSION,
        "expected_catalog_version": app.state.gear_service.equipment_catalog().revision,
    }
    route = "/ui-api/gear/potion-timelines"
    reply = client.post(route, json=body)
    assert reply.status_code == 422, reply.text
    assert "risk cap" in reply.json()["error"]["message"]
    body["scenario"]["wilderness"]["max_loss_gp"] = 800
    assert client.post(route, json=body).status_code == 200
