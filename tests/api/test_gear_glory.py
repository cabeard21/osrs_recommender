"""Browser optimization retains the owned charged glory in published results."""

import pytest

from tests.api.test_gear_optimizations import scenario


@pytest.mark.parametrize("policy", ("verified_only", "community_best_effort"))
def test_owned_charged_glory_is_equipped_without_purchase(client, session_factory, policy):
    body = {
        **scenario(client, session_factory, ids=(1333, 1706)),
        "support_policy": policy,
        "mode": "usable",
        "secondary_priority": "crush_defence_roll",
    }
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    selected = data["result"]["selected_solution"]
    assert selected["loadouts"]["single"]["equipment"]["neck"] == 1706
    assert selected["purchases"] == []
    assert selected["purchase_cost_gp"] == 0
    fact = next(item for item in data["items"] if item["item_id"] == 1706)
    assert fact["ownership"]["status"] == "owned"
    assert fact["wear"]["status"] == "satisfied"
    assert (
        client.get("/ui-api/gear/context").json()["account"]["snapshot_id"]
        == body["expected_snapshot_id"]
    )
