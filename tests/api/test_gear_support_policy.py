"""Browser policy is explicit and shared by catalog, search and exact evaluation."""

from tests.api.test_gear_optimizations import scenario


def test_community_browser_policy_and_exact_results(client, app, session_factory):
    catalog = app.state.gear_service.equipment_catalog()
    from tracker.gear.support import project_catalog

    community = project_catalog(catalog, "community_best_effort")
    item_id = next(
        i
        for i in community.community_assumptions
        if community.items[i].slot == "weapon"
        and "slash" in community.items[i].attack_styles
        and ("slash", "accurate") in community.items[i].attack_profiles
    )
    body = scenario(client, session_factory, ids=(item_id,))
    strict = client.get(f"/ui-api/gear/items/{item_id}").json()
    best = client.get(f"/ui-api/gear/items/{item_id}?support_policy=community_best_effort").json()
    assert strict["wear"]["status"] == "unknown"
    assert best["wear"]["status"] == "satisfied"
    assert not best["wear"]["requirements_complete"]
    assert best["support_status"] == best["effect_status"] == "community_assumed"
    assert best["support_assumptions"]
    body.update(support_policy="community_best_effort", locks={"weapon": item_id})
    optimized = client.post("/ui-api/gear/optimizations", json=body)
    assert optimized.status_code == 200, optimized.text
    result = optimized.json()["result"]
    assert result["support_policy"] == "community_best_effort"
    assert result["support_provenance"]
    assert result["selected_solution"]["loadouts"]["single"]["equipment"]["weapon"] == item_id
    exact = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": {"weapon": item_id}},
            "proposed_loadouts": {"single": {"weapon": item_id}},
        },
    )
    assert exact.status_code == 200, exact.text
    evaluated = exact.json()
    assert evaluated["baseline"]["status"] == evaluated["proposed"]["status"] == "valid"
    assert (
        evaluated["proposed"]["performance"]
        == result["selected_solution"]["loadouts"]["single"]["performance"]
    )
    assert evaluated["support_provenance"] == result["support_provenance"]
    assert evaluated["assumptions_fingerprint"] == result["assumptions_fingerprint"]
    body["support_policy"] = "verified_only"
    strict_result = client.post("/ui-api/gear/optimizations", json=body)
    assert strict_result.status_code == 200, strict_result.text
    assert strict_result.json()["result"]["selected_solution"] is None


def test_invalid_support_policy_rejected(client, session_factory):
    body = scenario(client, session_factory)
    body["support_policy"] = "invented"
    assert client.post("/ui-api/gear/optimizations", json=body).status_code == 422
    assert client.get("/ui-api/gear/items?support_policy=invented").status_code == 422
