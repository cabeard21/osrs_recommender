"""Fixed configurations are evaluated together without invoking candidate search."""

from datetime import UTC, datetime

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.db.models import ItemPrice, Player
from tracker.domain.types import PriceSourceLayer


def evaluation_body(client, session_factory, **scenario_changes):
    submitted = {**scenario(client, session_factory), **scenario_changes}
    now = datetime.now(UTC)
    with session_factory() as session:
        session.merge(
            ItemPrice(
                item_id=1333,
                high_price_gp=500,
                high_trade_at=now,
                fetched_at=now,
                source=PriceSourceLayer.CACHED,
                provider="test-exact-evaluation",
            )
        )
        session.commit()
    return {
        "scenario": submitted,
        "baseline_loadouts": {"single": {"weapon": 4151}},
        "proposed_loadouts": {"single": {"weapon": 4151}},
    }


def test_potion_evaluation_requires_and_preserves_exact_setup(client, session_factory):
    body = evaluation_body(
        client,
        session_factory,
        potions={
            "mode": "optimize",
            "allowed_ids": ["super_strength"],
        },
    )
    assert client.post("/ui-api/gear/evaluations", json=body).status_code == 422


def test_optimized_potion_setup_roundtrips_to_exact_evaluation(client, session_factory):
    body = evaluation_body(
        client,
        session_factory,
        potions={
            "mode": "optimize",
            "allowed_ids": ["super_strength"],
        },
    )
    optimized = client.post("/ui-api/gear/optimizations", json=body["scenario"])
    assert optimized.status_code == 200, optimized.text
    result = optimized.json()
    selected = result["result"]["selected_solution"]
    assert selected["potions"]["selected_ids"] == ["super_strength"]
    equipment = selected["loadouts"]["single"]["equipment"]
    body["selected_potion_ids"] = selected["potions"]["selected_ids"]
    body["baseline_loadouts"] = body["proposed_loadouts"] = {"single": equipment}
    evaluated = client.post("/ui-api/gear/evaluations", json=body)
    assert evaluated.status_code == 200, evaluated.text
    fixed = evaluated.json()
    assert fixed["scenario_fingerprint"] == result["scenario_fingerprint"]
    assert fixed["proposed"]["performance"] == selected["loadouts"]["single"]["performance"]
    body["selected_potion_ids"] = ["super_strength"]
    reply = client.post("/ui-api/gear/evaluations", json=body)
    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result["scenario"]["potions"]["mode"] == "optimize"
    assert result["baseline"]["potions"]["selected_ids"] == ["super_strength"]
    assert result["baseline"]["potions"]["boosted_levels"]["strength"] == 118
    body["selected_potion_ids"] = ["ranging"]
    assert client.post("/ui-api/gear/evaluations", json=body).status_code == 422


def test_evaluation_parity_and_complete_provenance(client, app, session_factory, monkeypatch):
    body = evaluation_body(client, session_factory)
    optimized = client.post("/ui-api/gear/optimizations", json=body["scenario"]).json()
    monkeypatch.setattr(
        app.state.gear_service, "optimize", lambda *a, **k: pytest.fail("candidate search invoked")
    )
    reply = client.post("/ui-api/gear/evaluations", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["baseline"]["status"] == data["proposed"]["status"] == "valid"
    assert (
        data["baseline"]["performance"]
        == optimized["result"]["selected_solution"]["loadouts"]["single"]["performance"]
    )
    assert data["baseline"] == data["proposed"]
    assert data["deltas"]["dps"] == data["deltas"]["purchase_cost_gp"] == 0
    assert data["deltas"]["equipment_changes"] == []
    for key in (
        "scenario_fingerprint",
        "price_revision",
        "catalog_version",
        "model_version",
        "assumptions_fingerprint",
        "evaluated_at",
    ):
        assert data[key]
    assert data["snapshot_id"] == body["scenario"]["expected_snapshot_id"]
    assert data["items"][0]["item_id"] == 4151
    assert reply.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "proposed",
    [
        {"single": {"head": 4151}},
        {"single": {"weapon": 99999999}},
        {"single": {"imaginary": 4151}},
        {"single": {"weapon": True}},
        {"other": {"weapon": 4151}},
        {"single": {"weapon": 4151}, "other": {}},
    ],
)
def test_malformed_equipment_rejected_with_fields(client, session_factory, proposed):
    body = evaluation_body(client, session_factory)
    body["proposed_loadouts"] = proposed
    reply = client.post("/ui-api/gear/evaluations", json=body)
    assert reply.status_code == 422, reply.text
    assert reply.json()["error"]["fields"]


@pytest.mark.parametrize(
    "scenario_changes,proposed,reason",
    [
        ({}, {"weapon": 1333}, "owned"),
        ({"locks": {"weapon": 4151}}, {"weapon": 1333}, "lock"),
        ({"excluded_item_ids": [1333]}, {"weapon": 1333}, "excluded"),
        ({"mode": "usable", "budget_gp": 0}, {"weapon": 1333}, "budget"),
        (
            {"mode": "future", "assumed_item_ids": [861, 12954]},
            {"weapon": 861, "shield": 12954},
            "Two-handed",
        ),
        ({"mode": "future", "assumed_item_ids": [4587]}, {"weapon": 4587}, "requirements"),
    ],
)
def test_infeasible_trial_has_reasons_not_numbers(
    client, session_factory, scenario_changes, proposed, reason
):
    body = evaluation_body(client, session_factory, **scenario_changes)
    body["proposed_loadouts"]["single"] = proposed
    reply = client.post("/ui-api/gear/evaluations", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["proposed"]["status"] == "invalid"
    assert data["proposed"]["performance"] is None
    assert data["deltas"] is None
    assert any(reason in row["message"] for row in data["proposed"]["reasons"])


def test_stale_origin_busy_and_failure_boundaries(client, app, session_factory, monkeypatch):
    body = evaluation_body(client, session_factory)
    reply = client.post(
        "/ui-api/gear/evaluations", json=body, headers={"Origin": "https://example.invalid"}
    )
    assert reply.status_code == 403
    stale = {**body, "scenario": {**body["scenario"], "expected_snapshot_id": "old"}}
    assert client.post("/ui-api/gear/evaluations", json=stale).status_code == 409
    lock = app.state.gear_service._optimization_lock
    assert lock.acquire(blocking=False)
    try:
        assert client.post("/ui-api/gear/evaluations", json=body).status_code == 503
    finally:
        lock.release()

    def failure(*args, **kwargs):
        raise RuntimeError("private diagnostic")

    monkeypatch.setattr(app.state.gear_service, "evaluate", failure)
    reply = client.post("/ui-api/gear/evaluations", json=body)
    assert reply.status_code == 500
    assert "private diagnostic" not in reply.text


def test_account_changed_during_evaluation_is_not_published(
    client, app, session_factory, monkeypatch
):
    body = evaluation_body(client, session_factory)
    original = app.state.gear_service.evaluate

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        with session_factory() as session:
            session.get(Player, 1).last_sync_at = datetime.now(UTC)
            session.commit()
        return result

    monkeypatch.setattr(app.state.gear_service, "evaluate", changed)
    reply = client.post("/ui-api/gear/evaluations", json=body)
    assert reply.status_code == 409
    assert reply.json()["error"]["code"] == "snapshot_changed"


@pytest.mark.parametrize("reverse", [False, True])
def test_purchase_differences_use_same_frozen_prices(client, session_factory, reverse):
    body = evaluation_body(client, session_factory, mode="usable", budget_gp=500)
    body["proposed_loadouts"]["single"] = {"weapon": 1333}
    if reverse:
        body["baseline_loadouts"], body["proposed_loadouts"] = (
            body["proposed_loadouts"],
            body["baseline_loadouts"],
        )
    response = client.post("/ui-api/gear/evaluations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["deltas"]["purchase_cost_gp"] == (-500 if reverse else 500)
    purchases = data["baseline" if reverse else "proposed"]["purchases"]
    assert purchases == [{"item_id": 1333, "cost_gp": 500, "conditional": False}]
    assert data["deltas"]["removed_purchase_ids" if reverse else "added_purchase_ids"] == [1333]
    assert data["deltas"]["equipment_changes"] == [
        {
            "slot": "weapon",
            "baseline_item_id": 1333 if reverse else 4151,
            "proposed_item_id": 4151 if reverse else 1333,
        }
    ]
    quote = next(item["price"] for item in data["items"] if item["item_id"] == 1333)
    assert quote["amount_gp"] == 500
    assert quote["provider"] == "test-exact-evaluation"


@pytest.mark.parametrize("disconnect", [False, True])
def test_evaluation_disconnect_and_task_cancellation_signal_worker(
    client, app, session_factory, monkeypatch, disconnect
):
    import asyncio
    from threading import Event
    from types import SimpleNamespace

    from fastapi import HTTPException

    from tracker.accounts.service import AccountService
    from tracker.api import gear_evaluations as api

    body = api.EquipmentEvaluationRequest.model_validate(evaluation_body(client, session_factory))
    snapshot = AccountService(session_factory).get_snapshot(1)
    entered, stopped = Event(), Event()

    def blocking_evaluation(*args, cancelled, **kwargs):
        entered.set()
        while not cancelled():
            stopped.wait(0.005)
        stopped.set()
        raise ValueError("evaluation_cancelled")

    monkeypatch.setattr(app.state.gear_service, "evaluate", blocking_evaluation)
    monkeypatch.setattr(api, "resources", lambda _: (snapshot, app.state.gear_service, {}))

    async def is_disconnected():
        return disconnect and entered.is_set()

    request = SimpleNamespace(
        headers={}, base_url="http://testserver/", is_disconnected=is_disconnected
    )

    async def exercise():
        task = asyncio.create_task(api.evaluations(request, body))
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        if disconnect:
            with pytest.raises(HTTPException) as caught:
                await task
            assert caught.value.status_code == 499
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert await asyncio.to_thread(stopped.wait, 2)

    asyncio.run(exercise())


def test_no_account_evaluation_is_unavailable(client):
    body = {
        "scenario": {
            "roles": [{"id": "single", "style": "crush"}],
            "expected_snapshot_id": "missing",
        },
        "baseline_loadouts": {"single": {}},
        "proposed_loadouts": {"single": {}},
    }
    response = client.post("/ui-api/gear/evaluations", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_unavailable"
