"""Session result routes enforce account ownership and bounded validated pages."""

from uuid import uuid4

from tests.api.test_gear_optimizations import scenario
from tests.gear.test_objective_store import result


def test_full_result_routes_and_invalid_queries(client, app, session_factory):
    scenario(client, session_factory)
    store = app.state.gear_service.objective_store
    published = store.publish_result(result(150), metadata={"snapshot_id": "frozen"}, player_id=1)
    run_id = published["run_id"]
    group_id = published["objective_frontiers"][0]["id"]
    base = f"/ui-api/gear/optimization-runs/{run_id}"
    metadata = client.get(base)
    assert metadata.status_code == 200, metadata.text
    assert metadata.headers["cache-control"] == "no-store"
    assert metadata.json()["snapshot_id"] == "frozen"
    page = client.get(f"{base}/frontiers/{group_id}/points", params={"limit": 100})
    assert page.status_code == 200, page.text
    assert len(page.json()["points"]) == 100
    assert page.json()["total"] == 150
    solution_id = page.json()["points"][0]["id"]
    details = client.get(f"{base}/solutions/{solution_id}")
    assert details.status_code == 200, details.text
    assert details.json()["solution"]["score"] == 150
    for query in ({"limit": 101}, {"sort": "invalid"}, {"cursor": "broken"}):
        assert client.get(f"{base}/frontiers/{group_id}/points", params=query).status_code == 422
    assert client.get(f"{base}/solutions/absent").status_code == 410
    assert client.get(f"{base}/frontiers/absent/points").status_code == 410
    assert client.get(f"/ui-api/gear/optimization-runs/{uuid4()}").status_code == 410
    store.close()
    assert client.get(base).status_code == 410


def test_result_routes_hide_other_account_runs(client, app, session_factory):
    scenario(client, session_factory)
    published = app.state.gear_service.objective_store.publish_result(
        result(2), metadata={}, player_id=999
    )
    response = client.get(f"/ui-api/gear/optimization-runs/{published['run_id']}")
    assert response.status_code == 410
