from datetime import UTC, datetime

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.db.models import ItemPrice
from tracker.domain.types import PriceSourceLayer


def ammo_body(client, session_factory):
    submitted = scenario(client, session_factory, ids=(861, 882, 892, 10499, 22109))
    submitted["roles"] = [{"id": "single", "style": "ranged", "stance": "rapid"}]
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
    assert any(p["reasons"] for p in data["points"])


def test_locks_and_exclusions(client, session_factory):
    body = ammo_body(client, session_factory)
    body["scenario"]["locks"] = {"cape": 10499, "ammunition": 882}
    data = client.post("/ui-api/gear/ammo-comparisons", json=body).json()
    assert all(p["dps"] is None for p in data["points"] if not p["current"])


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
