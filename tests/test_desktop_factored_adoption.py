"""Desktop activates qualified P1 and P3 only with its combined profile."""

import pytest
from fastapi.testclient import TestClient

from tracker.gear_desktop import DesktopSettings, create_app


def settings(profile="combined", workers=1):
    return DesktopSettings(
        pi_url="http://127.0.0.1:8502",
        player_id=1,
        read_token="factored-test-token",
        optimization_workers=workers,
        optimization_profile=profile,
        optimization_engine="python",
    )


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
def test_desktop_factored_follows_profile(profile):
    service = create_app(settings(profile)).state.gear_service
    assert service.factored_evaluation is (profile == "combined")
    assert service.compact_states is (profile == "combined")


def test_startup_fallback_keeps_factored_execution_and_logs_it(monkeypatch, caplog):
    def unavailable(workers):
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr("tracker.gear_desktop._process_pool", unavailable)
    caplog.set_level("INFO", logger="tracker.gear_desktop")
    app = create_app(settings(workers=3))
    with TestClient(app):
        assert app.state.gear_execution == "serial_startup_fallback"
        assert app.state.gear_service.factored_evaluation
        assert app.state.gear_service.compact_states
    assert "factored evaluation: enabled" in caplog.text
    assert "compact states: enabled" in caplog.text
    assert "factored-test-token" not in caplog.text


def test_environment_baseline_rollback_disables_all_factored_work(monkeypatch):
    monkeypatch.setenv("TRACKER_DESKTOP_OPTIMIZATION_PROFILE", "baseline")
    service = create_app(
        DesktopSettings(
            pi_url="http://127.0.0.1:8502",
            player_id=1,
            read_token="factored-test-token",
            optimization_workers=1,
        )
    ).state.gear_service
    assert not service.compact_states
    assert not service.factored_evaluation
    assert not service.fixed_reporting
