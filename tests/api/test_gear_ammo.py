from datetime import UTC, datetime

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.db.models import ItemPrice
from tracker.domain.types import PriceSourceLayer


def ammo_body(client, session_factory):
    submitted = scenario(client, session_factory, ids=(861, 882, 892, 10499, 22109))
    submitted["roles"] = [{"id": "single", "style": "ranged", "stance": "rapid"}]
    # Recovery assertions below intentionally include the weakest current arrow.
    submitted["max_dps_loss_pct"] = 100
    now = datetime.now(UTC)
    with session_factory() as session:
        session.merge(
            ItemPrice(
                item_id=882,
                high_price_gp=10,
                high_trade_at=now,
                fetched_at=now,
                source=PriceSourceLayer.CACHED,
                provider="test",
            )
        )
        session.commit()
    return {
        "scenario": submitted,
        "loadout": {"weapon": 861, "ammunition": 882, "cape": 10499},
        "combat_option": {"attack_type": "standard", "stance": "rapid"},
    }


def test_arrow_endpoint(client, session_factory):
    body = ammo_body(client, session_factory)
    response = client.post("/ui-api/gear/ammo-comparisons", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    current = next(p for p in data["points"] if p["current"])
    assert current["dps"] is not None, current["reasons"]
    assert current["gp_per_hour"] == pytest.approx(5600)
    assert current["recovery_rate"] == 0.72
    assert current["price"]["amount_gp"] == 10
    assert data["snapshot_id"] == body["scenario"]["expected_snapshot_id"]
    assert data["price_revision"]
    assert response.headers["cache-control"] == "no-store"
    assert all(p["dps"] is not None for p in data["points"])
    assert any("Excluded" in note for note in data["limitations"])


@pytest.mark.parametrize("cap", [0, 10])
def test_arrow_endpoint_applies_requested_loss_cap(client, session_factory, cap):
    body = ammo_body(client, session_factory)
    body["scenario"]["max_dps_loss_pct"] = cap
    reply = client.post("/ui-api/gear/ammo-comparisons", json=body)
    assert reply.status_code == 200, reply.text
    points = reply.json()["points"]
    assert points
    assert all(0 <= point["dps_loss_pct"] <= cap for point in points)
    assert all(point["dps"] is not None for point in points)
    assert any(point["dps_loss_pct"] == 0 for point in points)


def test_mixed_hide_cape_current_setup_has_known_cost(client, session_factory):
    body = ammo_body(client, session_factory)
    body["scenario"].update(
        mode="future", support_policy="community_best_effort", assumed_item_ids=[29289, 29280]
    )
    body["loadout"].update(cape=29289, body=29280)
    reply = client.post("/ui-api/gear/ammo-comparisons", json=body)
    assert reply.status_code == 200, reply.text
    current = next(point for point in reply.json()["points"] if point["current"])
    assert current["recovery_rate"] == 0
    assert current["arrows_lost_per_hour"] == pytest.approx(2000)
    assert current["gp_per_hour"] == pytest.approx(20000)


@pytest.mark.parametrize("optimization_mode", ["fast", "thorough"])
def test_comparison_matches_optimization_sources(client, session_factory, optimization_mode):
    body = ammo_body(client, session_factory)
    body["scenario"]["roles"][0]["combat_options"] = {
        "attack_types": ["standard"],
        "stances": ["rapid"],
        "spells": [],
    }
    body["scenario"].update(
        support_policy="community_best_effort",
        secondary_priority="balanced_defence",
        optimization_mode=optimization_mode,
        mode="future",
        skill_overrides={"ranged": 90},
    )
    optimized = client.post("/ui-api/gear/optimizations", json=body["scenario"])
    assert optimized.status_code == 200, optimized.text
    source = optimized.json()
    selected = source["result"]["selected_solution"]["loadouts"]["single"]
    comparison = client.post(
        "/ui-api/gear/ammo-comparisons",
        json={
            "scenario": source["scenario"],
            "loadout": selected["equipment"],
            "combat_option": selected["combat_option"],
        },
    )
    assert comparison.status_code == 200, comparison.text
    data = comparison.json()
    for field in ("snapshot_id", "catalog_version", "model_version", "assumptions_fingerprint"):
        assert data[field] == source["result"][field], field
    for field in ("price_revision", "scenario_fingerprint"):
        assert data[field] == source[field], field
    assert any(point["current"] and point["dps"] is not None for point in data["points"])


def test_locks_and_exclusions(client, session_factory):
    body = ammo_body(client, session_factory)
    body["scenario"]["locks"] = {"cape": 10499, "ammunition": 882}
    data = client.post("/ui-api/gear/ammo-comparisons", json=body).json()
    assert all(p["current"] for p in data["points"])
    assert any("lock" in note for note in data["limitations"])


def test_stale_and_nonranged(client, session_factory):
    body = ammo_body(client, session_factory)
    body["scenario"]["expected_snapshot_id"] = "old"
    assert client.post("/ui-api/gear/ammo-comparisons", json=body).status_code == 409
    body["scenario"]["expected_snapshot_id"] = client.get("/ui-api/gear/context").json()["account"][
        "snapshot_id"
    ]
    body["combat_option"]["attack_type"] = "slash"
    assert client.post("/ui-api/gear/ammo-comparisons", json=body).status_code == 422


def test_missing_account(client):
    response = client.post(
        "/ui-api/gear/ammo-comparisons",
        json={
            "scenario": {
                "roles": [{"id": "single", "style": "ranged", "stance": "rapid"}],
                "mode": "owned",
                "budget_gp": 0,
                "max_swaps": 0,
                "expected_snapshot_id": "missing",
            },
            "loadout": {"weapon": 861, "ammunition": 882},
            "combat_option": {"attack_type": "standard", "stance": "rapid"},
        },
    )
    assert response.status_code == 409


def test_non_arrow_weapon_and_unknown_id(client, session_factory):
    body = ammo_body(client, session_factory)
    body["loadout"]["weapon"] = 4151
    response = client.post("/ui-api/gear/ammo-comparisons", json=body)
    assert response.status_code == 200
    assert response.json()["limitations"]
    assert response.json()["points"] == []
    body["loadout"]["weapon"] = 999999999
    assert client.post("/ui-api/gear/ammo-comparisons", json=body).status_code == 422


@pytest.mark.parametrize(
    ("attack_type", "loadout"),
    [
        ("heavy", {"weapon": 9185, "ammunition": 9242}),
        ("light", {"weapon": 11230}),
    ],
)
def test_non_arrow_ranged_types_explain_bow_only_support(
    client, session_factory, attack_type, loadout
):
    body = ammo_body(client, session_factory)
    body["scenario"].update(
        mode="future",
        support_policy="community_best_effort",
        assumed_item_ids=list(loadout.values()),
        skill_overrides={"ranged": 90},
    )
    body["loadout"] = loadout
    body["combat_option"]["attack_type"] = attack_type
    response = client.post("/ui-api/gear/ammo-comparisons", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["points"] == []
    assert response.json()["limitations"] == [
        "Arrow comparison requires a supported bow using ordinary arrows."
    ]


@pytest.mark.parametrize("body_id", [10378, 11828, 1117, 7370])
def test_compatible_body_keeps_arrow_running_cost(client, session_factory, body_id):
    body = ammo_body(client, session_factory)
    # Explicit future ownership, while retaining the real catalogue and wear gates.
    body["scenario"]["mode"] = "future"
    body["scenario"]["support_policy"] = "community_best_effort"
    body["scenario"]["assumed_item_ids"] = [body_id]
    body["loadout"]["body"] = body_id
    reply = client.post("/ui-api/gear/ammo-comparisons", json=body)
    assert reply.status_code == 200, reply.text
    current = next(point for point in reply.json()["points"] if point["current"])
    assert current["dps"] is not None, current["reasons"]
    assert current["recovery_rate"] == 0.72
    assert current["gp_per_hour"] == pytest.approx(5600)
