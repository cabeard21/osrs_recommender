"""Explicit browser search modes retain legacy defaults and bounded refinement."""

import pytest

from tests.api.test_gear_joint_optimizations import joint_scenario
from tests.api.test_gear_optimizations import scenario


def test_omitted_mode_and_fast_preserve_baseline(client, app, session_factory):
    body = scenario(client, session_factory)
    legacy = client.post("/ui-api/gear/optimizations", json=body)
    explicit = client.post("/ui-api/gear/optimizations", json={**body, "optimization_mode": "fast"})
    assert legacy.status_code == explicit.status_code == 200
    left, right = legacy.json(), explicit.json()
    assert left["optimization_mode"] == right["optimization_mode"] == "fast"
    assert left["scenario_fingerprint"] == right["scenario_fingerprint"]
    assert left["work_budget_policy"]["complete_assignment_limit"] == 0
    assert "local_refinement" not in left["result"]["search"]
    assert left["result"]["selected_solution"] == right["result"]["selected_solution"]


@pytest.mark.parametrize("mode", ["Fast", "THOROUGH", "", None, True, 1, {}, []])
def test_invalid_modes_are_field_errors(client, session_factory, mode):
    body = {**scenario(client, session_factory), "optimization_mode": mode}
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 422
    assert any(row["path"] == "optimization_mode" for row in response.json()["error"]["fields"])


def test_thorough_identity_diagnostics_and_original_incumbent(client, app, session_factory):
    body = scenario(client, session_factory)
    fast = client.post("/ui-api/gear/optimizations", json=body).json()
    response = client.post(
        "/ui-api/gear/optimizations", json={**body, "optimization_mode": "thorough"}
    )
    assert response.status_code == 200, response.text
    thorough = response.json()
    assert thorough["optimization_mode"] == thorough["scenario"]["optimization_mode"] == "thorough"
    assert thorough["result"]["optimization_mode"] == "thorough"
    assert thorough["work_budget_policy"] == thorough["result"]["work_budget_policy"]
    assert thorough["work_budget_policy"]["complete_assignment_limit"] == 2000
    assert thorough["work_budget_policy"]["targeted_head_refinement"] is False
    assert fast["scenario_fingerprint"] != thorough["scenario_fingerprint"]
    diagnostics = thorough["result"]["search"]["local_refinement"]
    assert diagnostics["work_budget"] == 2000
    assert diagnostics["assignment_attempts"] <= 2000
    assert diagnostics["baseline"]["curve_solutions"][0] == fast["result"]["selected_solution"]
    assert "targeted_head_refinement" not in thorough["result"]["search"]
    for field in ("snapshot_id", "catalog_version", "model_version"):
        assert thorough["result"][field] == fast["result"][field]


@pytest.mark.parametrize("mode", ["fast", "thorough"])
def test_modes_preserve_busy_guard(client, app, session_factory, mode):
    body = {**scenario(client, session_factory), "optimization_mode": mode}
    service = app.state.gear_service
    assert service._optimization_lock.acquire(blocking=False)
    try:
        response = client.post("/ui-api/gear/optimizations", json=body)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "optimizer_busy"
    finally:
        service._optimization_lock.release()


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_thorough_supports_all_role_counts_and_curve_ordering(client, app, session_factory, count):
    from tracker.gear.optimizer import _solution_key

    body = {**joint_scenario(client, app, session_factory, count), "optimization_mode": "thorough"}
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    diagnostics = result["search"]["local_refinement"]
    assert len(result["selected_solution"]["loadouts"]) == count
    for point, baseline in zip(
        result["curve"], diagnostics["baseline"]["curve_solutions"], strict=True
    ):
        if baseline is not None:
            assert point["solution"] is not None
            assert _solution_key(point["solution"]) <= _solution_key(baseline)


@pytest.mark.parametrize("disconnect", [True, False])
def test_thorough_disconnect_and_task_cancellation(
    client, app, session_factory, monkeypatch, disconnect
):
    from tests.api import test_gear_optimizations as existing

    original = existing.scenario
    monkeypatch.setattr(
        existing,
        "scenario",
        lambda *a, **k: {
            **original(*a, **k),
            "optimization_mode": "thorough",
        },
    )
    existing.test_disconnect_and_task_cancel_signal_cooperative_worker(
        client,
        app,
        session_factory,
        monkeypatch,
        disconnect,
        True,
    )


def test_thorough_trial_uses_same_scenario_identity(client, session_factory):
    body = {**scenario(client, session_factory), "optimization_mode": "thorough"}
    optimized = client.post("/ui-api/gear/optimizations", json=body).json()
    loadouts = {
        "single": optimized["result"]["selected_solution"]["loadouts"]["single"]["equipment"]
    }
    response = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": optimized["scenario"],
            "baseline_loadouts": loadouts,
            "proposed_loadouts": loadouts,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["scenario_fingerprint"] == optimized["scenario_fingerprint"]


@pytest.mark.parametrize("during_search", [False, True])
def test_thorough_rejects_changed_account(client, app, session_factory, monkeypatch, during_search):
    from tests.api import test_gear_optimizations as existing

    original = existing.scenario
    monkeypatch.setattr(
        existing,
        "scenario",
        lambda *a, **k: {**original(*a, **k), "optimization_mode": "thorough"},
    )
    check = (
        existing.test_account_changes_during_optimization_not_published
        if during_search
        else existing.test_stale_snapshot_rejected_before_service
    )
    check(client, app, session_factory, monkeypatch, True)


def test_browser_cannot_override_effective_policy(client, session_factory):
    body = {
        **scenario(client, session_factory),
        "optimization_mode": "thorough",
        "work_budget_policy": {"complete_assignment_limit": 1},
    }
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 422
