"""The serving benchmark preserves role topology and stages only declared static inputs."""

import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest

from tools import benchmark_gear_modes_api as benchmark
from tools.benchmark_gear_modes_api import archive_inputs, requests
from tracker.api.gear_optimizations import BrowserOptimizationRequest


def test_workloads_cover_single_styles_and_all_joint_roles_without_dropping_edges():
    rows = requests("frozen-snapshot")
    assert set(rows) == {"slash", "ranged", "magic", "joint_2", "joint_3", "joint_4"}
    for name, body in rows.items():
        parsed = BrowserOptimizationRequest.model_validate(body)
        count = int(name[-1]) if name.startswith("joint_") else 1
        assert len(parsed.roles) == count
        assert parsed.expected_snapshot_id == "frozen-snapshot"
        assert parsed.optimization_mode == "fast"
        assert parsed.max_swaps == (4 if count > 1 else 8)
        assert parsed.reserved_supply_slots == 12
        assert parsed.mode == "usable" and parsed.budget_gp == 5_000_000


def test_transfer_is_explicit_static_allowlist_and_manifest_covers_every_byte():
    payload, manifest = archive_inputs()
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert names == set(manifest)
        assert "content/equipment/catalog.json" in names
        assert "tools/benchmark_gear_modes_api.py" in names
        assert "tracker/gear/local_refinement.py" in names
        assert "tracker/api/gear_optimizations.py" in names
        assert not any("config" in name or ".tmp" in name or ".env" in name for name in names)
        assert all(name.endswith((".py", ".json", ".yaml")) for name in names)
        for name in names:
            assert len(archive.read(name)) == manifest[name]["bytes"]
            assert len(manifest[name]["sha256"]) == 64


def mock_transport(monkeypatch, responses):
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def sendall(self, payload):
            assert b"POST /ui-api/gear/optimizations HTTP/1.1" in payload

    class Client(Connection):
        def __init__(self, **kwargs):
            pass

        def post(self, url, **kwargs):
            calls.append(url)
            status, body = responses.pop(0)
            return SimpleNamespace(status_code=status, json=lambda: body)

    monkeypatch.setattr(benchmark.socket, "create_connection", lambda *a, **k: Connection())
    monkeypatch.setattr(benchmark.httpx, "Client", Client)
    monkeypatch.setattr(benchmark.time, "sleep", lambda _: None)
    return calls


@pytest.mark.parametrize("status", [200, 422, 409, 500])
def test_cancellation_requires_observed_busy_guard(monkeypatch, status):
    calls = mock_transport(monkeypatch, [(status, {})])
    result = benchmark.cancellation("http://127.0.0.1:1234", requests("snapshot")["joint_4"])
    assert result["status"] == "not_measured"
    assert "guard_released_after_disconnect_seconds" not in result
    assert calls == ["http://127.0.0.1:1234/ui-api/gear/optimizations"]


@pytest.mark.parametrize("status", [422, 409, 500])
def test_evaluation_errors_cannot_prove_cancellation(monkeypatch, status):
    mock_transport(
        monkeypatch,
        [(503, {"error": {"code": "optimizer_busy"}}), (status, {})],
    )
    result = benchmark.cancellation("http://127.0.0.1:1234", requests("snapshot")["joint_4"])
    assert result["status"] == "not_measured"
    assert result["evaluation_status"] == status
    assert "guard_released_after_disconnect_seconds" not in result


def test_cancellation_requires_valid_evaluation_after_busy(monkeypatch):
    busy = (503, {"error": {"code": "optimizer_busy"}})
    mock_transport(
        monkeypatch,
        [busy, busy, (200, {"baseline": {"status": "valid"}, "proposed": {"status": "valid"}})],
    )
    result = benchmark.cancellation("http://127.0.0.1:1234", requests("snapshot")["joint_4"])
    assert result["status"] == "measured"
    assert result["evaluation_status"] == 200
    assert result["guard_released_after_disconnect_seconds"] >= 0


def test_disconnect_age_includes_busy_response_wait(monkeypatch):
    mock_transport(
        monkeypatch,
        [
            (503, {"error": {"code": "optimizer_busy"}}),
            (200, {"baseline": {"status": "valid"}, "proposed": {"status": "valid"}}),
        ],
    )
    ticks = iter([10, 10.9, 11])
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(ticks))
    result = benchmark.cancellation("http://127.0.0.1:1234", requests("snapshot")["joint_4"])
    assert result["scheduled_sleep_seconds"] == 0.2
    assert result["disconnect_after_seconds"] == pytest.approx(0.9)
    assert result["guard_released_after_disconnect_seconds"] == pytest.approx(0.1)


def test_invalid_200_evaluation_is_not_cancellation_acceptance(monkeypatch):
    mock_transport(
        monkeypatch,
        [
            (503, {"error": {"code": "optimizer_busy"}}),
            (200, {"baseline": {"status": "invalid"}, "proposed": {"status": "valid"}}),
        ],
    )
    result = benchmark.cancellation("http://127.0.0.1:1234", requests("snapshot")["joint_4"])
    assert result["status"] == "not_measured"
    assert "guard_released_after_disconnect_seconds" not in result


def test_inherited_environment_cannot_select_production_content_or_database(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_CONTENT_DIR", "/production/content")
    monkeypatch.setenv("TRACKER_DATABASE_URL", "sqlite:////production/tracker.db")
    monkeypatch.setenv("TRACKER_CONFIG_FILE", "/production/config.yaml")
    env = benchmark.service_environment(tmp_path / "synthetic.sqlite", tmp_path, 1234, "disposable")
    assert env["TRACKER_CONTENT_DIR"] == str(benchmark.Path("content").resolve())
    assert env["TRACKER_DATABASE_URL"] == f"sqlite:///{tmp_path / 'synthetic.sqlite'}"
    assert env["TRACKER_CONFIG_FILE"] == str(tmp_path / "absent.yaml")
    assert env["TRACKER_API_TOKEN"] == "disposable"
    assert env["TRACKER_MCP__PORT"] == "1234"
