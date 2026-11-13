"""Process failures have a retryable browser error and never leak worker details."""

from datetime import datetime

import pytest

from tests.api.test_gear_auto_disciplines import auto_role
from tests.api.test_gear_optimizations import NOW, scenario


def stable(value):
    if isinstance(value, dict):
        return {
            key: stable(row)
            for key, row in value.items()
            if key not in {"duration_seconds", "timings_seconds"}
        }
    if isinstance(value, list):
        return [stable(row) for row in value]
    return value


@pytest.mark.parametrize(
    "code", ["optimizer_worker_unavailable", "optimizer_worker_context_mismatch"]
)
def test_worker_failure_is_retryable_and_sanitized(client, app, session_factory, monkeypatch, code):
    body = {**scenario(client, session_factory), "roles": [auto_role()]}

    def failed(*args, **kwargs):
        raise ValueError(f"{code}: private worker traceback")

    monkeypatch.setattr(app.state.gear_service, "optimize", failed)
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "optimizer_worker_unavailable"
    assert "private worker traceback" not in response.text


@pytest.mark.parametrize("mode", ["fast", "thorough"])
def test_actual_spawn_pool_matches_full_serial_api_response(
    client,
    app,
    session_factory,
    monkeypatch,
    mode,
):
    from tracker.api import gear_optimizations
    from tracker.gear.parallel import AutoProcessPool

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(gear_optimizations, "datetime", FrozenDateTime)
    body = {**scenario(client, session_factory), "roles": [auto_role()], "optimization_mode": mode}
    before = client.post("/ui-api/gear/optimizations", json=body)
    assert before.status_code == 200, before.text
    gear = app.state.gear_service
    pool = AutoProcessPool(3)
    try:
        pool.start(gear.content, gear.equipment_catalog())
        gear.auto_pool = pool
        after = client.post("/ui-api/gear/optimizations", json=body)
        assert after.status_code == 200, after.text
        assert stable(after.json()) == stable(before.json())
        assert client.get("/healthz").status_code == 200
    finally:
        pool.close()
        gear.auto_pool = None
