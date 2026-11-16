"""Composable objective identity and browser response projection."""

import pytest

from tests.api.test_gear_optimizations import scenario


def test_objective_fingerprint_is_semantic():
    from tracker.api.gear_optimizations import BrowserOptimizationRequest, scenario_fingerprint

    base = {"roles": [{"id": "a", "style": "slash"}], "expected_snapshot_id": "snapshot"}
    first = BrowserOptimizationRequest(
        **base,
        objectives=[
            {"kind": "defence_roll", "styles": ["magic", "stab"]},
            {"kind": "prayer_bonus"},
        ],
    )
    second = BrowserOptimizationRequest(
        **base,
        objectives=[
            {"kind": "prayer_bonus"},
            {"kind": "defence_roll", "styles": ["stab", "magic"], "aggregation": "minimum"},
            {"kind": "prayer_bonus"},
        ],
    )
    assert scenario_fingerprint(first) == scenario_fingerprint(second)
    assert scenario_fingerprint(first) != scenario_fingerprint(
        BrowserOptimizationRequest(**base, objectives=[{"kind": "prayer_bonus"}])
    )


@pytest.mark.parametrize(
    "objectives",
    [
        [{"kind": "defence_roll", "styles": []}],
        [{"kind": "defence_roll", "styles": ["invalid"]}],
        [{"kind": "prayer_bonus", "weight": 5}],
        [{"kind": "unknown"}],
    ],
)
def test_invalid_objectives_are_rejected(client, session_factory, objectives):
    response = client.post(
        "/ui-api/gear/optimizations",
        json={**scenario(client, session_factory), "objectives": objectives},
    )
    assert response.status_code == 422


def test_vector_objectives_roundtrip(client, session_factory):
    response = client.post(
        "/ui-api/gear/optimizations",
        json={
            **scenario(client, session_factory),
            "objectives": [
                {"kind": "defence_roll", "styles": ["stab", "ranged"]},
                {"kind": "prayer_bonus"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["frontier_policy"]["expansion_limit"] == 1000000
    result = data["result"]
    definitions = result["objective_definitions"]
    assert len(definitions) == 2
    chosen = result["selected_solution"]
    assert set(chosen["objective_values"]) == {d["id"] for d in definitions}
    assert chosen["secondary_value"] is None
    assert result["objective_frontiers"]
    run = data["objective_run"]
    restored = client.get(f"/ui-api/gear/optimization-runs/{run['run_id']}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["response"] == data
    detail = client.get(
        f"/ui-api/gear/optimization-runs/{run['run_id']}/solutions/{run['selected_solution_id']}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["solution"]["objective_values"] == chosen["objective_values"]


def test_frozen_vector_timeline_keeps_original_context(client, app, session_factory, monkeypatch):
    from types import SimpleNamespace

    from tracker.api import gear_potion_timelines

    response = client.post(
        "/ui-api/gear/optimizations",
        json={
            **scenario(client, session_factory),
            "objectives": [{"kind": "defence_roll", "styles": ["stab", "magic"]}],
            "potions": {"mode": "fixed", "selected_ids": ["super_defence", "magic"]},
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    run = result["objective_run"]
    assert run["selected_solution_id"]
    # An unrelated newer live snapshot must not replace frozen inputs.
    original_resources = gear_potion_timelines.resources
    monkeypatch.setattr(
        gear_potion_timelines,
        "resources",
        lambda request: (
            SimpleNamespace(player_id=1, fingerprint="new-live-snapshot"),
            app.state.gear_service,
            {},
        ),
    )
    timeline = client.post(
        "/ui-api/gear/potion-timelines",
        json={
            "run_id": run["run_id"],
            "solution_id": run["selected_solution_id"],
        },
    )
    assert timeline.status_code == 200, timeline.text
    values = timeline.json()
    assert values["snapshot_id"] == result["result"]["snapshot_id"]
    assert (
        values["samples"][0]["objective_values"]
        == result["result"]["selected_solution"]["objective_values"]
    )
    monkeypatch.setattr(gear_potion_timelines, "resources", original_resources)


def test_disconnect_during_archive_publication_signals_worker():
    import asyncio
    from threading import Event
    from types import SimpleNamespace

    from fastapi import HTTPException

    from tracker.api.gear_optimizations import _await_publication

    stopped, entered = Event(), Event()

    def publishing():
        entered.set()
        assert stopped.wait(5)
        return {}

    async def disconnected():
        return entered.is_set()

    async def exercise():
        task = asyncio.create_task(asyncio.to_thread(publishing))
        with pytest.raises(HTTPException) as caught:
            await _await_publication(SimpleNamespace(is_disconnected=disconnected), stopped, task)
        assert caught.value.status_code == 499
        assert stopped.is_set()
        await task

    asyncio.run(exercise())
