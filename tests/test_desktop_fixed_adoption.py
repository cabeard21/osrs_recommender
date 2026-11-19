"""Desktop native execution enables qualified fixed reporting."""

from tracker.gear_desktop import DesktopSettings, create_app


def test_desktop_enables_fixed_reporting():
    settings = DesktopSettings(
        pi_url="http://127.0.0.1:8502",
        player_id=1,
        read_token="test-token",
        optimization_workers=1,
    )
    service = create_app(settings).state.gear_service
    assert service.fixed_reporting
