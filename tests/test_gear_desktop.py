import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tracker.gear_desktop import DesktopSettings, create_app


def settings(**kwargs):
    return DesktopSettings(
        pi_url="http://100.117.157.57:8502", player_id=1, read_token="test-read-token", **kwargs
    )


def test_desktop_has_no_database_or_write_routes():
    app = create_app(settings())
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
    config = DesktopSettings()
    assert config.player_id == 2
    assert config.read_token.get_secret_value() == "env-token"
