"""NPC browser routes work without account state and preserve variants."""

import pytest

from tests.api.test_gear_optimizations import scenario


def test_npc_search_detail_and_validation(client):
    result = client.get("/ui-api/gear/targets", params={"q": "Dagannoth Rex"}).json()
    assert result["total"] >= 1
    item = result["items"][0]
    detail = client.get("/ui-api/gear/targets/" + item["key"])
    assert detail.status_code == 200
    assert detail.json()["target"]["defence_level"] == 255
    assert detail.json()["catalog_revision"] == result["catalog_revision"]
    assert client.get("/ui-api/gear/targets/missing").status_code == 404
    assert client.get("/ui-api/gear/targets", params={"limit": 101}).status_code == 422
    assert client.get("/ui-api/gear/targets", params={"offset": -1}).status_code == 422
    assert (
        client.get("/ui-api/gear/targets", params={"q": "no-such-creature-xyzz"}).json()["total"]
        == 0
    )
    context = client.get("/ui-api/gear/context").json()
    assert context["capabilities"]["npc_catalog"]["available"] is True


@pytest.mark.parametrize("endpoint", ["optimizations", "evaluations"])
@pytest.mark.parametrize("invalid", ["stale", "unsupported", "mechanics"])
def test_catalog_validation_on_both_calculations(client, session_factory, endpoint, invalid):
    from tracker.gear.npcs import npc_catalog

    catalog = npc_catalog()
    body = scenario(client, session_factory)
    query = "Akkha" if invalid == "unsupported" else "Zulrah"
    entry = catalog.detail(catalog.search(query)["items"][0]["key"])
    body["roles"][0]["target_selection"] = {
        "key": entry["key"],
        "catalog_revision": "old" if invalid == "stale" else catalog.revision,
    }
    if invalid == "mechanics":
        body["roles"][0]["target"] = {**entry["target"], "damage_cap": None}
    payload = (
        body
        if endpoint == "optimizations"
        else {
            "scenario": body,
            "baseline_loadouts": {"single": {}},
            "proposed_loadouts": {"single": {}},
        }
    )
    reply = client.post("/ui-api/gear/" + endpoint, json=payload)
    assert reply.status_code == (409 if invalid == "stale" else 422), reply.text


def test_catalog_stat_override_roundtrip(client, session_factory):
    from tracker.gear.npcs import npc_catalog

    catalog = npc_catalog()
    body = scenario(client, session_factory)
    entry = catalog.detail(catalog.search("Dagannoth Rex")["items"][0]["key"])
    body["roles"][0]["target_selection"] = {
        "key": entry["key"],
        "catalog_revision": catalog.revision,
    }
    body["roles"][0]["target"] = {**entry["target"], "defence_level": 100}
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    assert reply.json()["scenario"]["roles"][0]["target"]["defence_level"] == 100
    assert reply.json()["scenario"]["roles"][0]["target_selection"]["key"] == entry["key"]


def test_reported_lizardman_selection_runs_thorough_balanced_defence(client, session_factory):
    from tracker.gear.npcs import npc_catalog

    catalog = npc_catalog()
    entry = catalog.detail("c4b35626ceb46d21a4dc6ee8")
    body = scenario(client, session_factory)
    body.update(
        support_policy="community_best_effort",
        secondary_priority="balanced_defence",
        max_dps_loss_pct=10,
        optimization_mode="thorough",
    )
    body["roles"][0].update(
        target=entry["target"],
        target_selection={"key": entry["key"], "catalog_revision": catalog.revision},
    )
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    submitted = reply.json()["scenario"]["roles"][0]
    assert submitted["target"]["name"] == "Lizardman (Level 53)"
    assert submitted["target"]["unsupported_mechanics"] == []
    assert submitted["target_selection"]["key"] == entry["key"]


def test_reported_lizardman_scenario_can_optimize(client, session_factory):
    from tracker.gear.npcs import npc_catalog

    catalog = npc_catalog()
    entry = catalog.detail("c4b35626ceb46d21a4dc6ee8")
    body = scenario(client, session_factory)
    body.update(
        support_policy="community_best_effort",
        secondary_priority="balanced_defence",
        max_dps_loss_pct=10,
        optimization_mode="thorough",
    )
    body["roles"][0].update(
        style="slash",
        stance="accurate",
        target=entry["target"],
        target_selection={"key": entry["key"], "catalog_revision": catalog.revision},
    )
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    target = reply.json()["scenario"]["roles"][0]["target"]
    assert target["name"] == "Lizardman (Level 53)"
    assert target["defence_level"] == 43
    assert target["bonuses"]["stab"] == -20
