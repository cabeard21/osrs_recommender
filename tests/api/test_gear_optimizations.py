"""Real browser optimization, frozen-context publication and cancellation contracts."""

import asyncio
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest

from tests.api.test_gear_ui import seed
from tracker.accounts.service import AccountService
from tracker.db.models import ItemPrice, Player, SkillSnapshot
from tracker.domain.types import PriceSourceLayer, Source

NOW = datetime(2026, 10, 23, tzinfo=UTC)


def scenario(client, session_factory, *, scans=True, ids=(4151,)):
    player_id = seed(session_factory, ids=ids, scans=scans)
    with session_factory() as session:
        for skill in ("attack", "strength", "defence", "magic", "ranged"):
            session.add(
                SkillSnapshot(
                    player_id=player_id,
                    skill=skill,
                    level=99,
                    source=Source.RUNELITE,
                    observed_at=NOW,
                )
            )
        session.commit()
    fingerprint = client.get("/ui-api/gear/context").json()["account"]["snapshot_id"]
    return {
        "roles": [{"id": "single", "style": "slash", "stance": "accurate"}],
        "mode": "owned",
        "budget_gp": 0,
        "max_swaps": 0,
        "expected_snapshot_id": fingerprint,
    }


def test_real_delegation_numeric_parity_baseline_and_determinism(client, app, session_factory):
    body = scenario(client, session_factory)
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    snapshot = AccountService(session_factory).get_snapshot(1)
    direct = app.state.gear_service.optimize(snapshot, body)
    assert data["result"]["selected_solution"] == direct["selected_solution"]
    assert data["baseline"]["status"] == "available"
    assert (
        data["baseline"]["performance"]
        == direct["selected_solution"]["loadouts"]["single"]["performance"]
    )
    assert data["items"][0]["item_id"] == 4151
    assert data["items"][0]["price"]["layer"] == "static_hint"
    assert data["scenario"]["expected_snapshot_id"] == snapshot.fingerprint
    again = client.post("/ui-api/gear/optimizations", json=body).json()
    assert again["result"]["selected_solution"] == data["result"]["selected_solution"]
    assert again["scenario_fingerprint"] == data["scenario_fingerprint"]
    assert reply.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "changes",
    [
        {"budget_gp": -1},
        {"budget_gp": 1.2},
        {"budget_gp": True},
        {"locks": {"weapon": 99999999}},
        {"assumed_item_ids": [99999999], "mode": "future"},
        {"roles": [{"id": "single", "style": "special"}]},
        {"roles": [{"id": "single", "style": "slash", "stance": "rapid"}]},
        {"roles": [{"id": "single", "style": "magic", "spell": "invented"}]},
        {"roles": [{"id": "single", "style": "slash", "target": {"defence_level": -1}}]},
        {
            "roles": [
                {"id": "single", "style": "slash", "target": {"unsupported_mechanics": ["prayers"]}}
            ]
        },
        {"skill_overrides": {"invented": 99}, "mode": "future"},
        {"skill_overrides": {"attack": True}, "mode": "future"},
        {"quest_overrides": {"invented": "complete"}, "mode": "future"},
        {
            "roles": [{"id": "single", "style": "slash", "locks": {"weapon": 4587}}],
            "locks": {"weapon": 4151},
        },
        {"locks": {"weapon": 861, "shield": 12954}},
    ],
)
def test_validation_field_errors_and_sync_auth_unchanged(client, session_factory, changes):
    body = {**scenario(client, session_factory), **changes}
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 422, reply.text
    assert reply.json()["error"]["fields"]
    assert client.post("/api/sync", json={}).status_code == 401


@pytest.mark.parametrize("multi", [False, True])
def test_stale_snapshot_rejected_before_service(client, app, session_factory, monkeypatch, multi):
    body = scenario(client, session_factory)
    if multi:
        body["roles"].append({"id": "second", "style": "slash"})
    body["expected_snapshot_id"] = "stale"
    monkeypatch.setattr(
        app.state.gear_service, "optimize", lambda *a, **k: pytest.fail("ran search")
    )
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 409
    assert reply.json()["error"]["code"] == "snapshot_changed"


@pytest.mark.parametrize("multi", [False, True])
def test_account_changes_during_optimization_not_published(
    client, app, session_factory, monkeypatch, multi
):
    body = scenario(client, session_factory)
    if multi:
        body["roles"].append({"id": "second", "style": "slash"})
    original = app.state.gear_service.optimize

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        with session_factory() as session:
            player = session.get(Player, 1)
            player.last_sync_at = NOW
            session.commit()
        return result

    monkeypatch.setattr(app.state.gear_service, "optimize", changed)
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 409
    assert reply.json()["error"]["code"] == "snapshot_changed"


@pytest.mark.parametrize("multi", [False, True])
def test_busy_service_and_failure_are_structured(client, app, session_factory, monkeypatch, multi):
    body = scenario(client, session_factory)
    if multi:
        body["roles"].append({"id": "second", "style": "slash"})

    def busy(*a, **k):
        raise ValueError("optimizer_busy: another equipment search is running")

    monkeypatch.setattr(app.state.gear_service, "optimize", busy)
    assert (
        client.post("/ui-api/gear/optimizations", json=body).json()["error"]["code"]
        == "optimizer_busy"
    )

    def failure(*a, **k):
        raise RuntimeError("private diagnostic")

    monkeypatch.setattr(app.state.gear_service, "optimize", failure)
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 500
    assert "private diagnostic" not in reply.text


def test_no_solution_and_incomplete_baseline(client, session_factory):
    body = scenario(client, session_factory, scans=False, ids=())
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    assert reply.json()["result"]["selected_solution"] is None
    assert reply.json()["baseline"]["status"] == "unavailable"
    assert reply.json()["baseline"]["performance"] is None
    assert reply.json()["baseline"]["reasons"]


def test_hypothetical_does_not_mutate_account_and_budget_enforced(client, session_factory):
    body = scenario(client, session_factory, ids=())
    body.update(mode="future", skill_overrides={"attack": 70}, assumed_item_ids=[4151])
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["selected_solution"]["purchase_cost_gp"] == 0
    assert (
        client.get("/ui-api/gear/context").json()["account"]["snapshot_id"]
        == body["expected_snapshot_id"]
    )
    body.update(mode="usable", skill_overrides={}, assumed_item_ids=[], locks={"weapon": 4151})
    assert (
        client.post("/ui-api/gear/optimizations", json=body).json()["result"]["selected_solution"]
        is None
    )
    body["budget_gp"] = 100000000
    selected = client.post("/ui-api/gear/optimizations", json=body).json()["result"][
        "selected_solution"
    ]
    assert selected["purchase_cost_gp"] > 0
    assert selected["purchases"][0]["item_id"] == 4151


@pytest.mark.parametrize(
    "changes",
    [
        {"roles": None},
        {"roles": 7},
        {"roles": "slash"},
        {"roles": [{"id": "single", "style": "slash", "target": {"bonuses": {"stab": None}}}]},
        {"roles": [{"id": "single", "style": "slash", "target": {"bonuses": {"stab": -65}}}]},
        {"roles": [{"id": "single", "style": "slash", "target": {"defence_level": True}}]},
    ],
)
def test_malformed_shapes_are_validation_errors(client, session_factory, changes):
    body = {**scenario(client, session_factory), **changes}
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["fields"][0]["path"] is not None


def test_same_origin_post_boundary_and_existing_auth(client, session_factory):
    body = scenario(client, session_factory)
    for headers in (
        {"Origin": "https://unrelated.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "null"},
    ):
        response = client.post("/ui-api/gear/optimizations", json=body, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "origin_rejected"
    assert (
        client.post(
            "/ui-api/gear/optimizations", json=body, headers={"Origin": "http://testserver"}
        ).status_code
        == 200
    )
    assert client.post("/api/sync", json={}).status_code == 401


def test_existing_service_lock_rejects_duplicate_work(client, app, session_factory):
    body = scenario(client, session_factory)
    lock = app.state.gear_service._optimization_lock
    assert lock.acquire(blocking=False)
    try:
        response = client.post("/ui-api/gear/optimizations", json=body)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "optimizer_busy"
    finally:
        lock.release()
    assert client.post("/ui-api/gear/optimizations", json=body).status_code == 200


def test_baseline_ignores_new_locks_and_purchase_budget(client, session_factory):
    body = scenario(client, session_factory)
    body["locks"] = {"weapon": None}
    data = client.post("/ui-api/gear/optimizations", json=body).json()
    assert data["result"]["selected_solution"] is None
    assert data["baseline"]["status"] == "available"
    assert data["baseline"]["equipment"]["weapon"] == 4151
    assert data["baseline"]["performance"]["dps"] > 0


@pytest.mark.parametrize("ids", [(4151, 4587), (4151, 99999999), (861, 12954)])
def test_ambiguous_unmapped_or_conflicting_baseline_has_no_metrics(client, session_factory, ids):
    body = scenario(client, session_factory, ids=ids)
    data = client.post("/ui-api/gear/optimizations", json=body).json()
    assert data["baseline"]["status"] == "unavailable"
    assert data["baseline"]["performance"] is None
    assert data["baseline"]["reasons"]


@pytest.mark.parametrize("disconnect", [True, False])
@pytest.mark.parametrize("multi", [False, True])
def test_disconnect_and_task_cancel_signal_cooperative_worker(
    client, app, session_factory, monkeypatch, disconnect, multi
):
    from fastapi import HTTPException

    from tracker.api import gear_optimizations as api

    raw = scenario(client, session_factory)
    if multi:
        raw["roles"].append({"id": "second", "style": "slash"})
    body = api.BrowserOptimizationRequest.model_validate(raw)
    snapshot = AccountService(session_factory).get_snapshot(1)
    entered, stopped = Event(), Event()

    def blocking_search(*args, cancelled, **kwargs):
        entered.set()
        while not cancelled():
            stopped.wait(0.005)
        stopped.set()
        raise ValueError("optimization_cancelled")

    monkeypatch.setattr(app.state.gear_service, "optimize", blocking_search)
    monkeypatch.setattr(api, "resources", lambda _: (snapshot, app.state.gear_service, {}))

    async def is_disconnected():
        return disconnect and entered.is_set()

    request = SimpleNamespace(
        headers={}, base_url="http://testserver/", is_disconnected=is_disconnected
    )

    async def exercise():
        task = asyncio.create_task(api.optimizations(request, body))
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set(), "Worker did not start outside the event loop"
        if disconnect:
            with pytest.raises(HTTPException) as caught:
                await task
            assert caught.value.status_code == 499
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert await asyncio.to_thread(stopped.wait, 2), "Worker cancellation was not signalled"

    asyncio.run(exercise())


def test_no_account_cannot_optimize(client):
    body = {"roles": [{"id": "single", "style": "crush"}], "expected_snapshot_id": "missing"}
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_unavailable"


def test_purchase_quote_preserves_cached_market_provenance(
    client, app, session_factory, monkeypatch
):
    body = scenario(client, session_factory, ids=())
    body.update(mode="usable", budget_gp=2000000, locks={"weapon": 4151})
    catalog = app.state.gear_service.equipment_catalog()
    monkeypatch.setattr(
        app.state.gear_service,
        "_equipment",
        SimpleNamespace(items={4151: catalog.items[4151]}, revision=catalog.revision),
    )
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            ItemPrice(
                item_id=4151,
                high_price_gp=1234567,
                low_price_gp=1200000,
                high_trade_at=now,
                low_trade_at=now,
                fetched_at=now,
                source=PriceSourceLayer.LIVE,
                provider="osrs_wiki",
            )
        )
        session.commit()
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["result"]["selected_solution"]["purchase_cost_gp"] == 1234567
    assert data["result"]["selected_solution"]["purchases"] == [
        {"item_id": 4151, "cost_gp": 1234567, "conditional": False}
    ]
    quote = data["items"][0]["price"]
    assert quote["amount_gp"] == quote["high_price_gp"] == 1234567
    assert quote["provider"] == "osrs_wiki"
    assert quote["source"] == quote["layer"] == "live"
    assert quote["selected_trade_at"] == now.isoformat().replace("+00:00", "Z")
    assert quote["confidence"] == "high"
