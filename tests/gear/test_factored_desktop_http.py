"""Isolated desktop HTTP acceptance over synthetic frozen, read-only facts.

This exercises real sockets and app lifespan, never the user's desktop process.
The actual desktop factory enables the qualified combined implementation.
"""

from __future__ import annotations

import json
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import httpx
import pytest
import uvicorn

from tests.gear.test_prayer_search_efficiency import scenario
from tools.benchmark_gear_desktop import without_observations
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.optimizer import _Search
from tracker.gear.prayers import PrayerPolicy
from tracker.gear_desktop import DesktopSettings, create_app

ENDPOINT = "/ui-api/gear/optimizations"


def _active_contexts():
    from tracker.gear.compact_costs import active as costs
    from tracker.gear.fixed_reporting import active as fixed
    from tracker.gear.prepared_combat import active as combat
    from tracker.gear.ranged_score_finalization import active as finalization
    from tracker.gear.variant_reporting import active as variants

    return tuple(check() for check in (costs, fixed, combat, finalization, variants))


@dataclass(frozen=True)
class FrozenSource:
    snapshot: object

    def load(self):
        return self.snapshot, {}


@contextmanager
def _serve(app):
    """Hold an ephemeral loopback socket through startup to avoid a port race."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        address = listener.getsockname()
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", access_log=False, lifespan="on")
        )
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = monotonic() + 10
            while not server.started and thread.is_alive() and monotonic() < deadline:
                Event().wait(0.01)
            assert server.started, "Isolated desktop server did not start"
            with httpx.Client(
                base_url=f"http://{address[0]}:{address[1]}", trust_env=False, timeout=10
            ) as client:
                yield client, address
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "Isolated desktop server did not stop"


@pytest.fixture
def desktop_factory(monkeypatch):
    snapshot, request, catalog, content, _, now = scenario("ranged", PrayerPolicy())
    request = request.model_copy(
        update={
            "roles": (
                request.roles[0].model_copy(
                    update={
                        "combat_options": None,
                        "stance": "rapid",
                    }
                ),
            ),
        }
    )

    class FrozenTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr("tracker.content.loader.load_content", lambda _: content)
    monkeypatch.setattr("tracker.api.gear_optimizations.datetime", FrozenTime)

    def build(profile="combined"):
        app = create_app(
            DesktopSettings(
                pi_url="http://127.0.0.1:1",
                player_id=1,
                read_token="fixture-only",
                optimization_workers=1,
                optimization_profile=profile,
            )
        )
        app.state.gear_service._equipment = EquipmentCatalog(catalog.items, "http-fixture")
        app.state.gear_data_source = FrozenSource(snapshot)
        body = {**request.model_dump(mode="json"), "expected_snapshot_id": snapshot.fingerprint}
        return app, body

    return build


def _run(client, body):
    identity = str(uuid4())
    response = client.post(ENDPOINT, params={"progress_id": identity}, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["result"]["selected_solution"] is not None
    progress = client.get(f"{ENDPOINT}/progress", params={"progress_id": identity})
    assert progress.status_code == 200
    assert progress.json()["progress"]["phase"] == "complete"
    assert progress.json()["progress"]["scenario_fingerprint"] == result["scenario_fingerprint"]
    other = client.get(f"{ENDPOINT}/progress", params={"progress_id": str(uuid4())})
    assert other.json()["progress"] is None
    return result


def test_http_factored_fixed_result_progress_and_baseline_rollback(desktop_factory, monkeypatch):
    observations = []
    original = _Search.tick

    def observed_tick(search):
        observations.append(_active_contexts())
        return original(search)

    monkeypatch.setattr(_Search, "tick", observed_tick)
    app, body = desktop_factory()
    with _serve(app) as (client, _):
        assert client.get("/healthz").json() == {"status": "ok"}
        context = client.get("/ui-api/gear/context")
        assert context.status_code == 200, context.text
        assert context.json()["account"]["snapshot_id"] == body["expected_snapshot_id"]
        candidate = _run(client, body)
        assert observations and all(all(flags) for flags in observations)
    assert not any(_active_contexts())

    observations.clear()
    rollback, same_body = desktop_factory("baseline")
    with _serve(rollback) as (client, _):
        baseline = _run(client, same_body)
        assert observations and not any(any(flags) for flags in observations)
    assert without_observations(candidate) == without_observations(baseline)


def test_tcp_disconnect_cancels_factored_search_and_next_request_recovers(
    desktop_factory,
    monkeypatch,
):
    entered, cancelled = Event(), Event()
    original = _Search.tick
    pause = True

    def wait_for_disconnect(search):
        if pause and not entered.is_set():
            assert all(_active_contexts())
            entered.set()
            deadline = monotonic() + 5
            while not search.cancelled() and monotonic() < deadline:
                Event().wait(0.005)
            assert search.cancelled(), "HTTP disconnect did not reach the optimizer"
            cancelled.set()
        return original(search)

    monkeypatch.setattr(_Search, "tick", wait_for_disconnect)
    app, body = desktop_factory()
    with _serve(app) as (client, address):
        identity = str(uuid4())
        data = json.dumps(body).encode()
        with socket.create_connection(address, timeout=5) as connection:
            headers = (
                f"POST {ENDPOINT}?progress_id={identity} HTTP/1.1\r\n"
                f"Host: {address[0]}:{address[1]}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(data)}\r\n\r\n"
            ).encode()
            connection.sendall(headers + data)
            assert entered.wait(5), "Real optimizer did not start"
            progress = client.get(f"{ENDPOINT}/progress", params={"progress_id": identity})
            assert progress.json()["progress"]["phase"] not in ("complete", "failed")
            connection.shutdown(socket.SHUT_RDWR)
        assert cancelled.wait(5), "Real optimizer did not observe cancellation"
        deadline = monotonic() + 5
        while monotonic() < deadline:
            progress = client.get(f"{ENDPOINT}/progress", params={"progress_id": identity})
            if progress.json()["progress"]["phase"] == "failed":
                break
            Event().wait(0.01)
        assert progress.json()["progress"]["phase"] == "failed"
        pause = False
        _run(client, body)
    assert not any(_active_contexts())


@pytest.mark.browser
def test_browser_publishes_factored_result_without_javascript_errors(desktop_factory, page):
    from playwright.sync_api import expect

    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    app, _ = desktop_factory()
    with _serve(app) as (client, _):
        page.goto(str(client.base_url.join("/gear")), wait_until="domcontentloaded")
        run = page.get_by_role("button", name="Run optimization", exact=True)
        expect(run).to_be_enabled()
        with page.expect_response(
            lambda response: ENDPOINT in response.url and response.request.method == "POST"
        ) as pending:
            run.click()
        response = pending.value
        assert response.status == 200, response.text()
        assert response.json()["result"]["selected_solution"] is not None
        expect(page.get_by_role("heading", name="Best configuration found")).to_be_visible()
        expect(page.get_by_role("button", name="Reoptimize", exact=True)).to_be_enabled()
        assert not errors, errors
