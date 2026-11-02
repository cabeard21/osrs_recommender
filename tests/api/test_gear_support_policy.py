"""Browser policy is explicit and shared by catalog, search and exact evaluation."""

import pytest

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


@pytest.mark.parametrize(
    "ring,support_status",
    [
        (30895, "community_assumed"),
        (6731, "community_assumed"),
        (6735, "community_assumed"),
        (6733, "verified"),
        (6737, "verified"),
    ],
)
def test_owned_tradeable_ring_is_usable_without_requirement_data(
    client, session_factory, ring, support_status
):
    weapon = 4151
    body = scenario(client, session_factory, ids=(ring, weapon))
    detail = client.get(f"/ui-api/gear/items/{ring}?support_policy=community_best_effort").json()
    assert detail["wear"]["status"] == "satisfied"
    assert detail["support_status"] == support_status
    body.update(support_policy="community_best_effort", locks={"weapon": weapon, "ring": ring})
    optimized = client.post("/ui-api/gear/optimizations", json=body)
    assert optimized.status_code == 200, optimized.text
    selected = optimized.json()["result"]["selected_solution"]
    assert selected is not None
    assert selected["loadouts"]["single"]["equipment"]["ring"] == ring
    loadout = {"single": {"weapon": weapon, "ring": ring}}
    exact = client.post(
        "/ui-api/gear/evaluations",
        json={"scenario": body, "baseline_loadouts": loadout, "proposed_loadouts": loadout},
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["proposed"]["status"] == "valid"
