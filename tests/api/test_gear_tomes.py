"""Tome effects survive the public optimization and fixed-evaluation boundaries."""

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.gear.parallel_payload import context_payload, decode_context


@pytest.mark.parametrize("pages,minimum", [("burnt", 1), ("searing", 2)])
def test_tome_optimization_and_fixed_evaluation_agree(client, session_factory, pages, minimum):
    body = scenario(client, session_factory, ids=(1381, 20716))
    body["fire_tome_pages"] = pages
    body["roles"] = [
        {
            "id": "single",
            "style": "magic",
            "spell": "fire_surge",
            "locks": {"weapon": 1381, "shield": 20716},
        }
    ]
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    loadout = result["result"]["selected_solution"]["loadouts"]["single"]
    assert loadout["equipment"]["shield"] == 20714
    assert loadout["performance"]["max_hit"] == 26
    assert loadout["performance"]["tome_bonus"]["minimum_hit"] == minimum
    assert result["scenario"]["fire_tome_pages"] == pages
    assert any(item["item_id"] == 20716 for item in result["items"])
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
    assert evaluated.json()["scenario"]["fire_tome_pages"] == pages


def test_tome_worker_metadata_roundtrip(app):
    service = app.state.gear_service
    catalog = service.equipment_catalog()
    payload, identity = context_payload(service.content, catalog)
    _, restored = decode_context(payload, identity)
    for item_id in (20714, 25574, 30064):
        assert restored.items[item_id] == catalog.items[item_id]
        assert restored.items[item_id].tome_effect is not None


def test_invalid_fire_page_mode_rejected(client, session_factory):
    body = scenario(client, session_factory)
    body["fire_tome_pages"] = "unlimited"
    assert client.post("/ui-api/gear/optimizations", json=body).status_code == 422


def test_observed_baseline_resolves_searing_mode(client, session_factory):
    body = scenario(client, session_factory, ids=(1381, 20714))
    body["fire_tome_pages"] = "searing"
    body["roles"] = [{"id": "single", "style": "magic", "spell": "fire_surge"}]
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    baseline = reply.json()["baseline"]
    assert baseline["status"] == "available"
    assert baseline["performance"]["tome_bonus"]["fire_pages"] == "searing"
    assert baseline["performance"]["tome_bonus"]["minimum_hit"] == 2
