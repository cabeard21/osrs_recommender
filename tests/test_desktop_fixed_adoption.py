"""Qualified fixed reporting is enabled only by desktop combined configuration."""

import pytest

from tracker.gear_desktop import DesktopSettings, create_app


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
def test_desktop_fixed_reporting_follows_profile(profile):
    settings = DesktopSettings(
        pi_url="http://127.0.0.1:8502",
        player_id=1,
        read_token="test-token",
        optimization_workers=1,
        optimization_profile=profile,
    )
    service = create_app(settings).state.gear_service
    assert service.fixed_reporting is (profile == "combined")


def test_environment_rollback_disables_fixed_reporting(tmp_path, monkeypatch):
    config = tmp_path / "desktop.yaml"
    config.write_text(
        "pi_url: http://127.0.0.1:8502\nplayer_id: 1\nread_token: test-token\n"
        "optimization_workers: 1\noptimization_profile: combined\n"
    )
    monkeypatch.setenv("TRACKER_CONFIG_FILE", str(config))
    monkeypatch.setenv("TRACKER_DESKTOP_OPTIMIZATION_PROFILE", "baseline")
    assert not create_app(DesktopSettings()).state.gear_service.fixed_reporting


def test_pool_startup_fallback_preserves_fixed_reporting(monkeypatch):
    from fastapi.testclient import TestClient

    def unavailable(workers):
        raise RuntimeError("test pool unavailable")

    monkeypatch.setattr("tracker.gear_desktop._process_pool", unavailable)
    settings = DesktopSettings(
        pi_url="http://127.0.0.1:8502",
        player_id=1,
        read_token="test-token",
        optimization_workers=3,
        optimization_profile="combined",
    )
    app = create_app(settings)
    with TestClient(app):
        assert app.state.gear_execution == "serial_startup_fallback"
        assert app.state.gear_service.fixed_reporting
