from datetime import UTC, datetime

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.db.models import ItemPrice
from tracker.domain.types import PriceSourceLayer
from tracker.gear.optimizer import SLOTS


@pytest.mark.parametrize(
    "item_id,market_id,style,stance,gp_per_hour",
    [
        (22545, 22542, "crush", "accurate", 15_000),
        (22550, 22547, "ranged", "rapid", 20_000),
        (27788, 27785, "magic", "accurate", 14_400),
    ],
)
def test_wilderness_toggle_applies_to_optimization_and_fixed_evaluation(
    client, session_factory, item_id, market_id, style, stance, gp_per_hour
):
    body = scenario(client, session_factory, ids=(item_id,))
    body.update(
        locks={"weapon": item_id},
        roles=[{"id": "npc", "style": style, "stance": stance, "spell": "wind_strike"}],
    )
    now = datetime.now(UTC)
    with session_factory() as session:
        for resource_id, price in ((21820, 10), (market_id, 3_000_000), (556, 1), (558, 1)):
            session.merge(
                ItemPrice(
                    item_id=resource_id,
                    high_price_gp=price,
                    high_trade_at=now,
                    fetched_at=now,
                    provider="test-revenant",
                    source=PriceSourceLayer.CACHED,
                )
            )
        session.commit()
    equipment = {"npc": {"weapon": item_id}}
    performances = []
    for inside in (False, True):
        request = body | ({"wilderness": {"max_loss_gp": 1_000_000}} if inside else {})
        reply = client.post("/ui-api/gear/optimizations", json=request)
        assert reply.status_code == 200, reply.text
        result = reply.json()["result"]
        assert result["assumptions"]["revenant_weapon_model_version"] == "revenant-weapons-v1"
        loadout = result["selected_solution"]["loadouts"]["npc"]
        assert loadout["performance"]["wilderness_weapon_passive"] is inside
        assert loadout["running_cost"]["gp_per_hour"] == pytest.approx(gp_per_hour)
        exact = client.post(
            "/ui-api/gear/evaluations",
            json={
                "scenario": request,
                "baseline_loadouts": equipment,
                "proposed_loadouts": equipment,
            },
        )
        assert exact.status_code == 200, exact.text
        assert exact.json()["proposed"]["performance"] == loadout["performance"]
        assert exact.json()["assumptions_fingerprint"] == result["assumptions_fingerprint"]
        performances.append(loadout["performance"])
    outside, inside = performances
    assert inside["attack_roll"] == outside["attack_roll"] * 3 // 2
    assert inside["max_hit"] == outside["max_hit"] * 3 // 2


def test_two_ready_maces_have_one_purchase_row_for_two_copies(client, session_factory):
    body = scenario(client, session_factory, ids=())
    body.update(
        mode="usable",
        roles=[
            {"id": "charged", "style": "crush", "locks": {"weapon": 22545}},
            {"id": "empty", "style": "crush", "locks": {"weapon": 22542}},
        ],
        locks={s: None for s in SLOTS if s != "weapon"},
        budget_gp=100_000,
        max_swaps=1,
    )
    now = datetime.now(UTC)
    with session_factory() as session:
        session.merge(
            ItemPrice(
                item_id=22542,
                high_price_gp=50_000,
                high_trade_at=now,
                fetched_at=now,
                provider="test-revenant",
                source=PriceSourceLayer.CACHED,
            )
        )
        session.commit()
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    selected = reply.json()["result"]["selected_solution"]
    assert selected is not None
    assert selected["purchase_cost_gp"] == 100_000
    assert selected["purchases"] == [
        {"item_id": 22542, "cost_gp": 100_000, "quantity": 2, "conditional": False}
    ]
    below = client.post("/ui-api/gear/optimizations", json=body | {"budget_gp": 99_999})
    assert below.status_code == 200, below.text
    assert below.json()["result"]["selected_solution"] is None
