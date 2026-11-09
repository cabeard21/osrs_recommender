import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tracker.gear_desktop import DesktopSettings, create_app


def settings(**kwargs):
    return DesktopSettings(
        pi_url="http://100.117.157.57:8502", player_id=1, read_token="test-read-token", **kwargs
    )


def test_desktop_has_no_database_or_write_routes():
    app = create_app(settings(optimization_workers=1))
    assert not hasattr(app.state, "session_factory")
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/api/sync", json={}).status_code == 404
        assert client.get("/", follow_redirects=False).status_code == 307
    assert not hasattr(app.state, "scheduler")


def test_desktop_rejects_exposure_and_placeholder():
    with pytest.raises(ValidationError):
        settings(bind_address="0.0.0.0")
    with pytest.raises(ValidationError):
        DesktopSettings(pi_url="http://pi:8502", player_id=1, read_token="CHANGE_ME")


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "100.101.102.103", "fd7a:115c:a1e0::1"])
def test_desktop_accepts_loopback_and_tailscale(address):
    assert settings(bind_address=address).bind_address == address


@pytest.mark.parametrize(
    "address", ["0.0.0.0", "::", "192.168.1.10", "8.8.8.8", "pc.local", "100.128.0.1"]
)
def test_desktop_rejects_other_interfaces(address):
    with pytest.raises(ValidationError):
        settings(bind_address=address)


def test_settings_errors_hide_credentials():
    from tracker.config.settings import Settings

    secret = "private-test-credential"
    with pytest.raises(ValidationError) as error:
        Settings(bind_address="127.0.0.1", api_token=secret, gear_data_token=secret)
    assert secret not in str(error.value)


def test_desktop_yaml_and_env(tmp_path, monkeypatch):
    path = tmp_path / "desktop.yaml"
    path.write_text("pi_url: http://pi.local:8502\nplayer_id: 2\nread_token: yaml-token\n")
    monkeypatch.setenv("TRACKER_CONFIG_FILE", str(path))
    monkeypatch.setenv("TRACKER_DESKTOP_READ_TOKEN", "env-token")
    monkeypatch.setenv("TRACKER_DESKTOP_OPTIMIZATION_WORKERS", "2")
    config = DesktopSettings()
    assert config.player_id == 2
    assert config.read_token.get_secret_value() == "env-token"
    assert config.optimization_workers == 2


def test_desktop_defaults_to_three_workers():
    assert settings().optimization_workers == 3


def test_desktop_entrypoint_prints_profile_at_startup():
    import subprocess
    import sys

    script = """
from fastapi.testclient import TestClient
import tracker.gear_desktop as desktop

desktop.load_desktop_settings = lambda: desktop.DesktopSettings(
    pi_url="http://127.0.0.1:8502", player_id=1,
    read_token="startup-test-secret", optimization_workers=1,
    optimization_profile="combined",
)
def run(app, **kwargs):
    with TestClient(app):
        pass
desktop.uvicorn.run = run
desktop.main()
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Desktop Gear optimization profile: combined" in result.stderr
    assert "Desktop Gear fixed-option reporting: enabled" in result.stderr
    assert "startup-test-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("workers", [0, 4, -1, True, False, 1.5, "2.5"])
def test_desktop_rejects_invalid_worker_counts(workers):
    with pytest.raises(ValidationError):
        settings(optimization_workers=workers)


class FakePool:
    def __init__(self, workers, *, fail=False):
        self.workers = workers
        self.fail = fail
        self.events = []

    def start(self, content, catalog):
        self.events.append(("start", content, catalog))
        if self.fail:
            raise RuntimeError("test pool failed")

    def close(self):
        self.events.append(("close",))


def test_desktop_owns_warm_pool_lifecycle(monkeypatch):
    import tracker.gear_desktop as desktop

    pool = FakePool(3)
    monkeypatch.setattr(desktop, "_process_pool", lambda workers: pool, raising=False)
    app = create_app(settings())
    gear = app.state.gear_service
    assert not pool.events
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert app.state.gear_execution == "processes"
        assert gear.auto_pool is pool
        assert pool.events == [("start", gear.content, gear.equipment_catalog())]
    assert pool.events[-1] == ("close",)
    assert gear.auto_pool is None


def test_desktop_serial_setting_never_creates_pool(monkeypatch):
    import tracker.gear_desktop as desktop

    def unexpected(workers):
        raise AssertionError("serial configuration created a pool")

    monkeypatch.setattr(desktop, "_process_pool", unexpected, raising=False)
    app = create_app(settings(optimization_workers=1))
    with TestClient(app):
        assert app.state.gear_execution == "serial"
        assert app.state.gear_service.auto_pool is None


def test_desktop_startup_failure_closes_pool_and_reports_serial_fallback(monkeypatch, caplog):
    import tracker.gear_desktop as desktop

    pool = FakePool(3, fail=True)
    monkeypatch.setattr(desktop, "_process_pool", lambda workers: pool, raising=False)
    app = create_app(settings())
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert app.state.gear_execution == "serial_startup_fallback"
        assert app.state.gear_service.auto_pool is None
        assert pool.events[-1] == ("close",)
        assert "serial" in caplog.text
    assert sum(event[0] == "close" for event in pool.events) == 1


def test_desktop_pool_creation_failure_falls_back_without_leaking_error_detail(monkeypatch, caplog):
    import tracker.gear_desktop as desktop

    def unavailable(workers):
        raise RuntimeError("private-internal-detail")

    monkeypatch.setattr(desktop, "_process_pool", unavailable)
    app = create_app(settings())
    with TestClient(app):
        assert app.state.gear_execution == "serial_startup_fallback"
        assert app.state.gear_service.auto_pool is None
    assert "RuntimeError" in caplog.text
    assert "private-internal-detail" not in caplog.text


def test_desktop_detaches_pool_if_shutdown_fails(monkeypatch):
    import tracker.gear_desktop as desktop

    class FailedClosePool(FakePool):
        def close(self):
            super().close()
            raise RuntimeError("close failed")

    pool = FailedClosePool(3)
    monkeypatch.setattr(desktop, "_process_pool", lambda workers: pool)
    app = create_app(settings())
    with pytest.raises(RuntimeError, match="close failed"), TestClient(app):
        assert app.state.gear_service.auto_pool is pool
    assert app.state.gear_service.auto_pool is None
