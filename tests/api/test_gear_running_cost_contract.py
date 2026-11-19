from tracker.api.gear_optimizations import RunningCost, RunningCostFrontier


def test_running_cost_unavailable_is_not_free():
    cost = RunningCost(
        status="unavailable",
        gp_per_attack=None,
        gp_per_hour=None,
        gp_per_damage=None,
        resources=[],
        reasons=["No rune quote"],
    )
    assert cost.model_dump()["gp_per_damage"] is None


def test_running_frontier_allows_unpriced_baseline():
    group = RunningCostFrontier(swap_limit=0, baseline_dps=10, points=[], sampled=False)
    assert group.model_dump()["baseline_solution"] is None


def test_mage_browser_publishes_staff_rune_savings(client, session_factory):
    from tests.api.test_gear_optimizations import scenario

    body = {
        **scenario(client, session_factory, ids=(1381,)),
        "roles": [{"id": "single", "style": "magic", "stance": "accurate", "spell": "fire_strike"}],
        "locks": {"weapon": 1381},
    }
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    result = data["result"]
    cost = result["selected_solution"]["loadouts"]["single"]["running_cost"]
    air = next(row for row in cost["resources"] if row["item_id"] == 556)
    assert air["consumed_quantity"] == 0
    assert air["supplied_quantity"] > 0
    assert air["supplied_by"] == "Staff of air"
    assert result["running_cost_frontiers"] == []


def test_ranged_browser_publishes_opt_in_objective_cost_solutions(client, session_factory):
    from tests.api.test_gear_ammo import ammo_body

    body = ammo_body(client, session_factory)["scenario"]
    body["objectives"] = [{"kind": "gp_per_damage"}]
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    result = data["result"]
    assert result["running_cost_frontiers"] == []
    assert result["objective_definitions"][0]["direction"] == "minimize"
    points = result["objective_frontiers"][0]["points"]
    assert points
    referenced = {item["item_id"] for item in data["items"]}
    for point in points:
        solution = point["solution"]
        assert solution["running_cost"]["status"] == "known"
        assert solution["running_cost"]["gp_per_damage"] >= 0
        assert set(solution["carried_item_ids"]) <= referenced
        loadout = solution["loadouts"]["single"]
        assert (
            solution["objective_values"]["gp_per_damage"]
            == solution["running_cost"]["gp_per_damage"]
        )
        assert loadout["equipment"]["weapon"] == 861


def test_unpriced_cost_objective_keeps_inspectable_dps_winner(client, session_factory):
    from tests.api.test_gear_optimizations import scenario

    body = {
        **scenario(client, session_factory, ids=(1381,)),
        "objectives": [{"kind": "gp_per_damage"}],
        "roles": [{"id": "single", "style": "magic", "stance": "accurate", "spell": "fire_strike"}],
        "locks": {"weapon": 1381},
    }
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    result = data["result"]
    selected = result["selected_solution"]
    assert selected["score"] > 0
    assert selected["running_cost"]["status"] == "unavailable"
    assert selected.get("objective_values", {}).get("gp_per_damage") is None
    group = result["objective_frontiers"][0]
    assert group["baseline_dps"] == selected["score"]
    assert group["points"] == []
    run_id = data["objective_run"]["run_id"]
    detail = client.get(
        f"/ui-api/gear/optimization-runs/{run_id}/solutions/{group['baseline_solution_id']}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["solution"]["running_cost"]["gp_per_damage"] is None
