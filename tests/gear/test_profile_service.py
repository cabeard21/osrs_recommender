"""Desktop profiles are server-owned and propagated without public request fields."""

import pytest
from pydantic import ValidationError

from tools.gear_search_quality_fixture import load_case
from tracker.gear.service import GearService, _timing_key
from tracker.gear_desktop import DesktopSettings, create_app


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
def test_service_propagates_selected_profile(profile, monkeypatch):
    case = load_case("melee_1m")
    service = GearService(case.content, optimization_profile=profile)
    service._equipment = case.catalog
    received = []

    def run(*args, **kwargs):
        received.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr("tracker.gear.optimizer.optimize", run)
    assert service.optimize(
        case.snapshot, case.request, price_records=case.prices, now=case.at
    ) == {"ok": True}
    assert received[0].get("_execution_profile", "baseline") == profile
    assert ("_execution_profile" in received[0]) == (profile != "baseline")


def test_generic_service_remains_baseline():
    assert GearService(load_case("melee_1m").content).optimization_profile == "baseline"


@pytest.mark.parametrize("profile", ["unknown", "", True, None])
def test_service_rejects_invalid_profiles(profile):
    with pytest.raises(ValueError, match="profile"):
        GearService(load_case("melee_1m").content, optimization_profile=profile)


def test_timing_profiles_are_isolated():
    request = load_case("melee_1m").request
    keys = {
        _timing_key(request, False, False, profile) for profile in ("baseline", "lazy", "combined")
    }
    assert len(keys) == 3


@pytest.mark.parametrize("profile", ["invalid", "", True, None])
def test_desktop_rejects_invalid_profiles(profile):
    with pytest.raises(ValidationError):
        DesktopSettings(
            pi_url="http://pi.local:8502",
            player_id=1,
            read_token="test-token",
            optimization_profile=profile,
        )


@pytest.mark.parametrize("branch", ["auto", "potions"])
@pytest.mark.parametrize("fixed", [False, True])
def test_service_worker_dispatch_keeps_profile(branch, fixed, monkeypatch):
    from types import SimpleNamespace

    from tracker.gear.potions import PotionPolicy

    case = load_case("melee_1m")
    service = GearService(case.content, optimization_profile="combined", fixed_reporting=fixed)
    service._equipment = case.catalog
    service.auto_pool = SimpleNamespace(run=lambda: None, run_potions=lambda: None)
    captured = []

    def runner(*args, **kwargs):
        captured.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr("tracker.gear.optimizer.optimize", runner)
    monkeypatch.setattr("tracker.gear.auto.optimize_auto", runner)
    if branch == "auto":
        request = case.request.model_copy(
            update={
                "roles": (
                    case.request.roles[0].model_copy(
                        update={"allowed_disciplines": ("melee", "ranged")}
                    ),
                )
            }
        )
        expected_key = "branch_runner"
    else:
        request = case.request.model_copy(
            update={"potions": PotionPolicy(mode="optimize", allowed_ids=("ranging",))}
        )
        expected_key = "potion_branch_runner"
    service.optimize(case.snapshot, request, now=case.at)
    assert captured[0]["_execution_profile"] == "combined"
    assert captured[0].get("_fixed_reporting", False) == fixed
    assert expected_key in captured[0]


def test_startup_profile_log_has_no_secret(monkeypatch, caplog):
    from fastapi.testclient import TestClient

    monkeypatch.setattr("tracker.gear_desktop.require_native", lambda: None)
    caplog.set_level("INFO", logger="tracker.gear_desktop")
    secret = "profile-test-secret"
    settings = DesktopSettings(
        pi_url="http://pi.local:8502",
        player_id=1,
        read_token=secret,
        optimization_workers=1,
    )
    with TestClient(create_app(settings)):
        pass
    assert "optimization profile: combined" in caplog.text
    assert secret not in caplog.text


def test_failure_is_not_retried_and_service_recovers(monkeypatch):
    case = load_case("melee_1m")
    service = GearService(case.content, optimization_profile="lazy")
    service._equipment = case.catalog
    calls = []

    def runner(*args, **kwargs):
        calls.append(kwargs["_execution_profile"])
        if len(calls) == 1:
            raise ValueError("optimized failure")
        return {"ok": True}

    monkeypatch.setattr("tracker.gear.optimizer.optimize", runner)
    with pytest.raises(ValueError, match="optimized failure"):
        service.optimize(case.snapshot, case.request, now=case.at)
    assert calls == ["lazy"]
    assert service.optimize(case.snapshot, case.request, now=case.at) == {"ok": True}
    assert calls == ["lazy", "lazy"]


def test_qualified_desktop_default_is_combined(tmp_path, monkeypatch):
    config = tmp_path / "desktop.yaml"
    config.write_text(
        "pi_url: http://pi.local:8502\nplayer_id: 1\n"
        "read_token: test-token\noptimization_workers: 1\n"
    )
    monkeypatch.setenv("TRACKER_CONFIG_FILE", str(config))
    monkeypatch.delenv("TRACKER_DESKTOP_OPTIMIZATION_PROFILE", raising=False)
    settings = DesktopSettings()
    assert settings.optimization_profile == "combined"
    assert create_app(settings).state.gear_service.optimization_profile == "combined"


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
def test_service_fixed_reporting_propagates_only_combined(profile, monkeypatch):
    case = load_case("melee_1m")
    service = GearService(case.content, optimization_profile=profile, fixed_reporting=True)
    service._equipment = case.catalog
    received = []
    monkeypatch.setattr("tracker.gear.optimizer.optimize", lambda *a, **k: received.append(k) or {})
    service.optimize(case.snapshot, case.request, now=case.at)
    assert received[0].get("_fixed_reporting", False) == (profile == "combined")


def test_fixed_reporting_separates_timing_estimates():
    request = load_case("melee_1m").request
    assert _timing_key(request, False, False, "combined", True) != _timing_key(
        request, False, False, "combined", False
    )


@pytest.mark.parametrize("bad", [None, 1, "true"])
def test_service_fixed_reporting_rejects_nonbool(bad):
    with pytest.raises(ValueError, match="fixed reporting"):
        GearService(load_case("melee_1m").content, fixed_reporting=bad)
