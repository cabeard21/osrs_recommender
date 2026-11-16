"""Read-only timeline parity and API boundaries."""

import pytest

from tests.api.test_gear_optimizations import scenario


def timeline_body(client, session_factory, **changes):
    submitted = {
        **scenario(client, session_factory),
        "potions": {"mode": "fixed", "selected_ids": ["super_strength"]},
        **changes,
    }
    return optimize_timeline(client, submitted)


def optimize_timeline(client, submitted):
    reply = client.post("/ui-api/gear/optimizations", json=submitted)
    assert reply.status_code == 200, reply.text
    result = reply.json()["result"]
    chosen = result["selected_solution"]
    assert chosen is not None, result
    return {
        "scenario": submitted,
        "selected_potion_ids": chosen["potions"]["selected_ids"],
        "loadouts": {
            key: {
                "equipment": row["equipment"],
                "combat_option": row["combat_option"],
                "selected_prayer_ids": row.get("selected_prayer_ids", []),
            }
            for key, row in chosen["loadouts"].items()
        },
        "expected_catalog_version": result["catalog_version"],
        "expected_model_version": result["model_version"],
    }, chosen


@pytest.mark.parametrize("prayer_mode", ["fixed", "optimize"])
def test_selected_prayers_preserve_timeline_parity(client, session_factory, prayer_mode):
    from tests.api.test_gear_prayers import prayer_body

    policy = {
        "mode": prayer_mode,
        "selected_ids" if prayer_mode == "fixed" else "allowed_ids": ["ultimate_strength"],
    }
    submitted = prayer_body(client, session_factory, policy)["scenario"]
    submitted["potions"] = {"mode": "fixed", "selected_ids": ["super_strength"]}
    body, selected = optimize_timeline(client, submitted)
    assert body["loadouts"]["single"]["selected_prayer_ids"] == ["ultimate_strength"]
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["samples"][0]["dps"] == selected["score"]
    assert data["samples"][-1]["dps"] == data["baseline"]["dps"]
    forged = {
        **body,
        "loadouts": {
            "single": {**body["loadouts"]["single"], "selected_prayer_ids": ["incredible_reflexes"]}
        },
    }
    assert client.post("/ui-api/gear/potion-timelines", json=forged).status_code == 422


def test_boosted_powered_magic_parity_and_decay(client, app, session_factory):
    from tracker.gear.catalog import EquipmentCatalog

    weapon = app.state.gear_service.equipment_catalog().items[11907]
    app.state.gear_service._equipment = EquipmentCatalog(
        {weapon.id: weapon}, revision="timeline-powered-fixture"
    )
    submitted = {
        **scenario(client, session_factory, ids=(weapon.id,)),
        "roles": [
            {
                "id": "single",
                "style": "magic",
                "combat_options": {
                    "attack_types": ["magic"],
                    "stances": ["accurate"],
                    "spells": [f"powered:{weapon.id}"],
                },
            }
        ],
        "potions": {"mode": "fixed", "selected_ids": ["magic"]},
        "secondary_priority": "accuracy",
    }
    body, selected = optimize_timeline(client, submitted)
    assert body["loadouts"]["single"]["combat_option"]["powered_attack"] == "seas"
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["samples"][0]["levels"]["magic"] == 103
    assert data["samples"][0]["dps"] == selected["score"]
    assert data["samples"][0]["secondary_value"] == selected["secondary_value"]
    assert data["samples"][0]["dps"] > data["baseline"]["dps"]
    assert data["samples"][-1]["dps"] == data["baseline"]["dps"]


def test_spell_becomes_unavailable_at_boost_threshold(client, session_factory):
    submitted = {
        **scenario(client, session_factory, ids=(1381,)),
        "mode": "future",
        "skill_overrides": {"magic": 91},
        "roles": [{"id": "single", "style": "magic", "spell": "fire_surge"}],
        "potions": {"mode": "fixed", "selected_ids": ["magic"]},
        "secondary_priority": "accuracy",
    }
    body, selected = optimize_timeline(client, submitted)
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["samples"][0]["levels"]["magic"] == 95
    assert data["samples"][0]["dps"] == selected["score"]
    decayed = next(row for row in data["samples"] if row["time_seconds"] == 60)
    assert decayed["levels"]["magic"] == 94
    assert decayed["dps"] is decayed["secondary_value"] is None
    assert "Magic level is unmet" in " ".join(decayed["roles"]["single"]["reasons"])
    assert data["baseline"]["dps"] is None


def test_measurements_share_unique_level_vectors(client, session_factory, monkeypatch):
    from tracker.gear import potion_timeline

    body, _ = timeline_body(client, session_factory)
    original = potion_timeline.measure
    calls = []

    def counted(time, levels, *args):
        calls.append(tuple(sorted(levels.items())))
        return original(time, levels, *args)

    monkeypatch.setattr(potion_timeline, "measure", counted)
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert len(calls) == len(set(calls))
    assert len(calls) < len(data["samples"]) + 1
    assert data["samples"][-1]["time_seconds"] > data["samples"][-2]["time_seconds"]


def test_timeline_fresh_parity_and_baseline(client, app, session_factory, monkeypatch):
    body, selected = timeline_body(client, session_factory, secondary_priority="accuracy")
    monkeypatch.setattr(
        app.state.gear_service, "optimize", lambda *a, **k: pytest.fail("search invoked")
    )
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert reply.headers["cache-control"] == "no-store"
    assert data["samples"][0]["dps"] == selected["score"]
    assert data["samples"][0]["secondary_value"] == selected["secondary_value"]
    assert data["samples"][-1]["dps"] == data["baseline"]["dps"]
    assert data["samples"][0]["levels"]["strength"] == 118


def test_timeline_boundaries(client, app, session_factory):
    body, _ = timeline_body(client, session_factory)
    assert (
        client.post(
            "/ui-api/gear/potion-timelines",
            json=body,
            headers={"Origin": "https://example.invalid"},
        ).status_code
        == 403
    )
    stale = {**body, "scenario": {**body["scenario"], "expected_snapshot_id": "old"}}
    assert client.post("/ui-api/gear/potion-timelines", json=stale).status_code == 409
    assert (
        client.post(
            "/ui-api/gear/potion-timelines", json={**body, "selected_potion_ids": ["ranging"]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/ui-api/gear/potion-timelines", json={**body, "expected_model_version": "old"}
        ).status_code
        == 409
    )
    assert app.state.gear_service._optimization_lock.acquire(blocking=False)
    try:
        assert client.post("/ui-api/gear/potion-timelines", json=body).status_code == 503
    finally:
        app.state.gear_service._optimization_lock.release()


@pytest.mark.parametrize(
    "priority",
    [
        "balanced_defence_roll",
        "melee_defence_roll",
        "melee_magic_defence_roll",
        "melee_ranged_defence_roll",
        "prayer_bonus",
        "default",
    ],
)
def test_secondary_metric_parity(client, session_factory, priority):
    body, selected = timeline_body(client, session_factory, secondary_priority=priority)
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["samples"][0]["dps"] == selected["score"]
    assert data["samples"][0]["secondary_value"] == (
        None if priority == "default" else selected["secondary_value"]
    )


@pytest.mark.parametrize(
    "priority", ["melee_defence_roll", "melee_magic_defence_roll", "melee_ranged_defence_roll"]
)
def test_melee_roll_timeline_tracks_defensive_boost_decay(client, session_factory, priority):
    body, selected = timeline_body(
        client,
        session_factory,
        secondary_priority=priority,
        potions={"mode": "fixed", "selected_ids": ["super_defence", "magic"]},
    )
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["secondary_priority"] == priority
    assert data["samples"][0]["secondary_value"] == selected["secondary_value"]
    assert data["samples"][0]["secondary_value"] > data["baseline"]["secondary_value"]
    assert data["samples"][-1]["secondary_value"] == data["baseline"]["secondary_value"]
    assert all(
        earlier["secondary_value"] >= later["secondary_value"]
        for earlier, later in zip(data["samples"], data["samples"][1:], strict=False)
    )


@pytest.mark.parametrize(
    "loadouts",
    [
        {},
        {
            "single": {
                "equipment": {"head": 4151},
                "combat_option": {"attack_type": "slash", "stance": "accurate"},
            }
        },
        {
            "single": {
                "equipment": {"weapon": 4151},
                "combat_option": {"attack_type": "stab", "stance": "accurate"},
            }
        },
    ],
)
def test_invalid_configuration(client, session_factory, loadouts):
    body, _ = timeline_body(client, session_factory)
    reply = client.post("/ui-api/gear/potion-timelines", json={**body, "loadouts": loadouts})
    assert reply.status_code == 422, reply.text


def test_multi_roles_and_utility(client, app, session_factory):
    from tests.api.test_gear_joint_optimizations import joint_scenario

    submitted = {
        **joint_scenario(client, app, session_factory),
        "potions": {"mode": "fixed", "selected_ids": ["super_strength"]},
        "secondary_priority": "accuracy",
    }
    submitted["roles"].append(
        {"id": "utility", "style": "special", "parent_role": "role-0", "locks": {"weapon": 4151}}
    )
    reply = client.post("/ui-api/gear/optimizations", json=submitted)
    assert reply.status_code == 200, reply.text
    result = reply.json()["result"]
    selected = result["selected_solution"]
    body = {
        "scenario": submitted,
        "selected_potion_ids": ["super_strength"],
        "expected_catalog_version": result["catalog_version"],
        "expected_model_version": result["model_version"],
        "loadouts": {
            key: {
                "equipment": row["equipment"],
                "combat_option": row["combat_option"],
                "selected_prayer_ids": row.get("selected_prayer_ids", []),
            }
            for key, row in selected["loadouts"].items()
            if key != "utility"
        },
    }
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    fresh = reply.json()["samples"][0]
    assert fresh["dps"] == selected["score"]
    assert fresh["secondary_value"] == selected["secondary_value"]
    assert set(fresh["roles"]) == {"role-0", "role-1"}


@pytest.mark.parametrize("disconnect", [False, True])
def test_cancel_signals_worker(client, app, session_factory, monkeypatch, disconnect):
    import asyncio
    from threading import Event
    from types import SimpleNamespace

    from fastapi import HTTPException

    from tracker.accounts.service import AccountService
    from tracker.api import gear_potion_timelines as api

    data, _ = timeline_body(client, session_factory)
    body = api.PotionTimelineRequest.model_validate(data)
    snapshot = AccountService(session_factory).get_snapshot(1)
    entered, stopped = Event(), Event()

    def blocking(*args):
        signal = args[-1]
        entered.set()
        while not signal.is_set():
            stopped.wait(0.005)
        stopped.set()
        raise ValueError("evaluation_cancelled")

    monkeypatch.setattr(api, "calculate_timeline", blocking)
    monkeypatch.setattr(api, "resources", lambda _: (snapshot, app.state.gear_service, {}))

    async def is_disconnected():
        return disconnect and entered.is_set()

    request = SimpleNamespace(
        headers={}, base_url="http://testserver/", is_disconnected=is_disconnected
    )

    async def exercise():
        task = asyncio.create_task(api.potion_timelines(request, body))
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


def test_changed_snapshot_during_timeline(client, app, session_factory, monkeypatch):
    from tracker.api import gear_potion_timelines as api

    body, _ = timeline_body(client, session_factory)
    original = api.resources
    calls = []

    def changing(request):
        calls.append(1)
        return original(request) if len(calls) == 1 else (None, app.state.gear_service, {})

    monkeypatch.setattr(api, "resources", changing)
    assert client.post("/ui-api/gear/potion-timelines", json=body).status_code == 409


def test_auto_selection_is_frozen(client, session_factory):
    body, selected = timeline_body(
        client,
        session_factory,
        roles=[
            {
                "id": "single",
                "style": "slash",
                "allowed_disciplines": ["melee"],
                "combat_options": {
                    "attack_types": ["stab", "slash", "crush"],
                    "stances": ["accurate", "aggressive", "controlled", "defensive"],
                    "spells": [],
                },
            }
        ],
    )
    reply = client.post("/ui-api/gear/potion-timelines", json=body)
    assert reply.status_code == 200, reply.text
    assert reply.json()["samples"][0]["dps"] == selected["score"]
