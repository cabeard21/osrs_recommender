"""Desktop-only execution profile lifetime and complete-result parity."""

import pytest

from tests.gear.test_prayer_search_efficiency import scenario
from tools.benchmark_gear_desktop import without_observations
from tracker.gear.execution_profile import execution_context, validate_profile
from tracker.gear.lazy_reporting import active as lazy_active
from tracker.gear.optimizer import optimize
from tracker.gear.ranged_numerics import active as ranged_active


@pytest.mark.parametrize("bad", [True, None, 1, "", "fast"])
def test_profile_validation(bad):
    with pytest.raises(ValueError, match="profile"):
        validate_profile(bad)


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
def test_concrete_context_lifetime_and_parity(profile):
    args = scenario("ranged")
    with execution_context(profile, args[1]):
        assert lazy_active() == (profile != "baseline")
        assert ranged_active() == (profile == "combined")
    assert not lazy_active() and not ranged_active()
    baseline = optimize(*args)
    actual = optimize(*args, _execution_profile=profile)
    assert without_observations(actual) == without_observations(baseline)
    assert not lazy_active() and not ranged_active()


def test_context_cleanup_on_error_and_nonranged():
    args = scenario("slash")
    with pytest.raises(RuntimeError), execution_context("combined", args[1]):
        assert lazy_active() and not ranged_active()
        raise RuntimeError("test")
    assert not lazy_active() and not ranged_active()


def test_worker_boolean_options_remain_strict():
    from tracker.gear.execution_profile import validate_worker_options

    for options in ({"local_refinement": 1}, {"unknown": True}):
        with pytest.raises(ValueError, match="worker options"):
            validate_worker_options(options, {"local_refinement"})


def test_multi_and_special_profiles_leave_contexts_inactive():
    from types import SimpleNamespace

    from tracker.gear.optimizer import RoleConfig

    roles = (RoleConfig(id="a", style="ranged"), RoleConfig(id="b", style="slash"))
    for request in (
        SimpleNamespace(roles=roles),
        SimpleNamespace(roles=(SimpleNamespace(style="special"),)),
    ):
        with execution_context("combined", request):
            assert not lazy_active() and not ranged_active()


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
def test_fixed_reporting_context_only_combined_and_cleans_up(profile):
    from tracker.gear.fixed_reporting import active as fixed_active

    args = scenario("ranged")
    with pytest.raises(RuntimeError), execution_context(profile, args[1], fixed_reporting=True):
        assert fixed_active() == (profile == "combined")
        raise RuntimeError("test")
    assert not fixed_active()


@pytest.mark.parametrize("bad", [None, 0, 1, "true"])
def test_fixed_flag_is_strict(bad):
    args = scenario()
    with pytest.raises(ValueError, match="fixed reporting"):
        optimize(*args, _execution_profile="combined", _fixed_reporting=bad)


def test_fixed_optimizer_path_is_explicit_and_default_unchanged(monkeypatch):
    from tools.gear_search_quality_fixture import load_case
    from tracker.gear.optimizer import _Search
    from tracker.gear.prayers import PrayerPolicy

    case = load_case("melee_1m")
    role = case.request.roles[0].model_copy(
        update={"combat_options": None, "prayers": PrayerPolicy()}
    )
    request = case.request.model_copy(update={"roles": (role,)})
    args = (case.snapshot, request, case.catalog, case.content, case.prices, case.at)
    calls = []
    original = _Search.fixed_performance

    def counted(self, *args, **kwargs):
        calls.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_Search, "fixed_performance", counted)
    expected = optimize(
        *args, _execution_profile="combined", _complete_frontiers=True, _running_frontier=True
    )
    assert not calls
    actual = optimize(
        *args,
        _execution_profile="combined",
        _fixed_reporting=True,
        _complete_frontiers=True,
        _running_frontier=True,
    )
    assert calls
    assert without_observations(actual) == without_observations(expected)

def test_context_rejects_nonboolean_fixed_flag():
    with pytest.raises(ValueError, match="fixed reporting"), execution_context(
        "combined", scenario()[1], fixed_reporting=1
    ):
        pass
