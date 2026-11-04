"""Browser frontier contract and identity."""

import pytest

from tests.api.test_gear_optimizations import scenario


def test_frontier_contract(client, session_factory):
    body = {**scenario(client, session_factory), "secondary_priority": "balanced_defence"}
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["frontier_policy"]["policy"] == "tradeoff-frontier-v2"
    assert data["frontier_policy"]["metric_lane_equipment_fraction"] == 0.25
    assert data["result"]["secondary_frontiers"]
    group = data["result"]["secondary_frontiers"][-1]
    assert "baseline_dps" in group
    changed = client.post("/ui-api/gear/optimizations", json={**body, "max_dps_loss_pct": 5})
    assert changed.status_code == 200, changed.text
    assert changed.json()["scenario_fingerprint"] != data["scenario_fingerprint"]


@pytest.mark.parametrize("value", [-1, 101, True, "10", None])
def test_frontier_range_validation(client, session_factory, value):
    response = client.post(
        "/ui-api/gear/optimizations",
        json={**scenario(client, session_factory), "max_dps_loss_pct": value},
    )
    assert response.status_code == 422


def test_frontier_real_tradeoff_and_selection_provenance(client, app, session_factory):
    from tests.api.test_gear_auto_disciplines import auto_role
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.models import EquipmentBonuses, EquipmentDefinition

    original = app.state.gear_service.equipment_catalog()
    helmets = [
        EquipmentDefinition(
            id=900011,
            name="Damage",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(melee_strength=20),
        ),
        EquipmentDefinition(
            id=900012,
            name="Defence",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(
                defence_stab=100,
                defence_slash=100,
                defence_crush=100,
                defence_ranged=100,
                defence_magic=100,
            ),
        ),
    ]
    app.state.gear_service._equipment = EquipmentCatalog(
        {4151: original.items[4151], **{i.id: i for i in helmets}}, revision="frontier-fixture"
    )
    body = {
        **scenario(client, session_factory, ids=(4151, 900011, 900012)),
        "locks": {"weapon": 4151},
        "secondary_priority": "balanced_defence",
        "max_dps_loss_pct": 100,
    }
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    group = next(
        g
        for g in data["result"]["secondary_frontiers"]
        if g["swap_limit"] == body.get("max_swaps", 8)
    )
    assert len(group["points"]) >= 2
    assert any(p["dps_loss"] > 0 and p["secondary_gain"] > 0 for p in group["points"])
    item_ids = {i["item_id"] for i in data["items"]}
    for point in group["points"]:
        solution = point["solution"]
        assert solution["score"] <= group["baseline_dps"]
        assert point["dps_loss_pct"] == pytest.approx(
            100 * (group["baseline_dps"] - solution["score"]) / group["baseline_dps"]
        )
        assert set(solution["carried_item_ids"]) <= item_ids
        assert solution["loadouts"]["single"]["equipment"]["weapon"] == 4151

    auto_response = client.post(
        "/ui-api/gear/optimizations",
        json={**body, "roles": [auto_role(["melee"])], "max_dps_loss_pct": 10},
    )
    assert auto_response.status_code == 200, auto_response.text
    auto_result = auto_response.json()["result"]
    branch = auto_result["discipline_results"][0]
    for frontier in [*auto_result["secondary_frontiers"], *branch["secondary_frontiers"]]:
        assert frontier["points"]
        assert all(p["dps_loss_pct"] <= 10 for p in frontier["points"])
