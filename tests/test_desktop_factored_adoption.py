"""Desktop native execution enables factored evaluation and compact states."""

from fastapi.testclient import TestClient

from tracker.gear_desktop import DesktopSettings, create_app


def test_desktop_enables_and_logs_factored_execution(monkeypatch, caplog):
    monkeypatch.setattr("tracker.gear_desktop.require_native", lambda: None)
    caplog.set_level("INFO", logger="tracker.gear_desktop")
    settings = DesktopSettings(
        pi_url="http://127.0.0.1:8502",
        player_id=1,
        read_token="factored-test-token",
        optimization_workers=1,
    )
    app = create_app(settings)
    with TestClient(app):
        assert app.state.gear_service.factored_evaluation
        assert app.state.gear_service.compact_states
    assert "factored evaluation: enabled" in caplog.text
    assert "compact states: enabled" in caplog.text
    assert "factored-test-token" not in caplog.text
