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


def test_npc_detail_preserves_target_size(client):
    result = client.get("/ui-api/gear/targets", params={"q": "Gemstone Crab"}).json()
    detail = client.get("/ui-api/gear/targets/" + result["items"][0]["key"]).json()
    assert detail["target"]["size"] == 5


def test_acidic_bloodveld_catalog_defences_roundtrip(client, session_factory):
    body = scenario(client, session_factory, ids=(861, 892))
    result = client.get("/ui-api/gear/targets", params={"q": "9573"}).json()
    entry = result["items"][0]
    detail = client.get("/ui-api/gear/targets/" + entry["key"]).json()
    target = detail["target"]
    assert target["name"] == "Acidic Bloodveld"
    body["roles"][0].update(
        style="ranged",
        target=target,
        target_selection={"key": entry["key"], "catalog_revision": result["catalog_revision"]},
    )
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    submitted = payload["scenario"]["roles"][0]["target"]
    assert set(submitted["bonuses"].values()) == {-100}
    assert {submitted[f"ranged_{subtype}"] for subtype in ("light", "standard", "heavy")} == {-100}
    assert payload["result"]["selected_solution"]["score"] > 0


@pytest.mark.parametrize("value", [-101, 10001, -100.0, True])
def test_custom_target_defence_bounds(client, session_factory, value):
    body = scenario(client, session_factory)
    body["roles"][0]["target"] = {"ranged_heavy": value, "bonuses": {"slash": value}}
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 422, reply.text
    assert {error["path"] for error in reply.json()["error"]["fields"]} == {
        "roles.0.target.ranged_heavy",
        "roles.0.target.bonuses.slash",
    }


@pytest.mark.parametrize("endpoint", ["optimizations", "evaluations"])
def test_sentinel_selection_reports_required_quest_on_both_routes(
    client, session_factory, endpoint
):
    body = scenario(client, session_factory)
    result = client.get("/ui-api/gear/targets", params={"q": "Vyrewatch Sentinel"}).json()
    assert result["total"] == 8
    assert all(entry["support_status"] == "supported" for entry in result["items"])
    entry = result["items"][0]
    detail = client.get("/ui-api/gear/targets/" + entry["key"]).json()
    assert detail["target"]["traits"] == ["vampyre3"]
    assert "Tier 3" in detail["limitations"][0]
    body["roles"][0].update(
        style="slash",
        target=detail["target"],
        target_selection={"key": entry["key"], "catalog_revision": result["catalog_revision"]},
    )
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
    assert reply.status_code == 422, reply.text
    assert "Sins of the Father" in reply.text


@pytest.mark.parametrize("size", [0, 1, 5, 64])
def test_custom_size_roundtrip(client, session_factory, size):
    body = scenario(client, session_factory)
    body["roles"][0]["target"] = {"size": size}
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    assert reply.json()["scenario"]["roles"][0]["target"]["size"] == size


@pytest.mark.parametrize("size", [None, True, 1.5, "2", -1, 65])
def test_invalid_custom_size(client, session_factory, size):
    body = scenario(client, session_factory)
    body["roles"][0]["target"] = {"size": size}
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 422, reply.text
    assert any(error["path"] == "roles.0.target.size" for error in reply.json()["error"]["fields"])


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


@pytest.mark.parametrize("armour", [-2, -5, 6])
def test_custom_armour_roundtrip(client, session_factory, armour):
    body = scenario(client, session_factory)
    body["roles"][0]["target"] = {"flat_armour": armour}
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    assert reply.json()["scenario"]["roles"][0]["target"]["flat_armour"] == armour


@pytest.mark.parametrize("armour", [True, 1.5, "2", 10001, -10001])
def test_invalid_custom_armour(client, session_factory, armour):
    body = scenario(client, session_factory)
    body["roles"][0]["target"] = {"flat_armour": armour}
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 422, reply.text


@pytest.mark.parametrize("endpoint", ["optimizations", "evaluations"])
@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
def test_cyclops_calculations_enforce_melee_only(client, session_factory, endpoint, style):
    body = scenario(client, session_factory)
    result = client.get("/ui-api/gear/targets", params={"q": "2137"}).json()
    entry = result["items"][0]
    assert entry["support_status"] == "supported"
    detail = client.get("/ui-api/gear/targets/" + entry["key"]).json()
    body["roles"][0].update(
        style=style,
        target=detail["target"],
        target_selection={"key": entry["key"], "catalog_revision": result["catalog_revision"]},
    )
    payload = (
        body
        if endpoint == "optimizations"
        else {
            "scenario": body,
            "baseline_loadouts": {"single": {"weapon": 4151}},
            "proposed_loadouts": {"single": {"weapon": 4151}},
        }
    )
    reply = client.post("/ui-api/gear/" + endpoint, json=payload)
    assert reply.status_code == (200 if style == "slash" else 422), reply.text
    if style != "slash":
        assert f"immune to {style}" in reply.text
    elif endpoint == "optimizations":
        assert reply.json()["result"]["selected_solution"]["score"] > 0
    else:
        assert reply.json()["baseline"]["status"] == "valid"
