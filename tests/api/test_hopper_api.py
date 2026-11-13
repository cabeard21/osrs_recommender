from tests.api.test_gear_optimizations import scenario


def test_hopper_optimization_and_fixed_evaluation_agree(client, session_factory):
    body = scenario(client, session_factory, ids=(9185, 9243, 32879))
    body["roles"] = [{"id": "single", "style": "ranged", "stance": "rapid"}]
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    selected = data["result"]["selected_solution"]["loadouts"]["single"]
    assert selected["equipment"]["shield"] == 32879
    assert selected["performance"]["aquanite_hopper"]["approximate"] is True
    fixed = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": selected["equipment"]},
            "proposed_loadouts": {"single": selected["equipment"]},
        },
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["proposed"]["performance"] == selected["performance"]
    assert data["result"]["assumptions"]["aquanite_hopper_model_version"]
    assert fixed.json()["assumptions_fingerprint"]
