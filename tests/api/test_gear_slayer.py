"""Task context and reviewed effects survive browser and worker boundaries."""

from tests.api.test_gear_optimizations import scenario
from tracker.gear.parallel_payload import context_payload, decode_context


def test_task_optimization_and_fixed_evaluation_agree(client, session_factory):
    body = scenario(client, session_factory, ids=(1333, 11865))
    body["roles"] = [
        {
            "id": "single",
            "style": "slash",
            "on_slayer_task": True,
            "locks": {"weapon": 1333, "head": 11865},
        }
    ]
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    loadout = result["result"]["selected_solution"]["loadouts"]["single"]
    assert loadout["performance"]["slayer_effects"][0]["item_id"] == 11865
    assert result["scenario"]["roles"][0]["on_slayer_task"] is True
    evaluated = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": loadout["equipment"]},
            "proposed_loadouts": {"single": loadout["equipment"]},
        },
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["proposed"]["performance"] == loadout["performance"]
    off = {**body, "roles": [{**body["roles"][0], "on_slayer_task": False}]}
    off_result = client.post("/ui-api/gear/optimizations", json=off).json()
    assert off_result["scenario_fingerprint"] != result["scenario_fingerprint"]
    off_performance = off_result["result"]["selected_solution"]["loadouts"]["single"]["performance"]
    assert off_performance["dps"] < loadout["performance"]["dps"]
    assert not off_performance["slayer_effects"]


def test_slayer_worker_metadata_roundtrip(app):
    service = app.state.gear_service
    catalog = service.equipment_catalog()
    payload, identity = context_payload(service.content, catalog)
    _, restored = decode_context(payload, identity)
    for item_id in (8921, 11865, 4170, 21255):
        assert restored.items[item_id] == catalog.items[item_id]
    assert restored.items[11865].slayer_bonus == "all"
    assert restored.items[21255].slayer_staff_enchanted
