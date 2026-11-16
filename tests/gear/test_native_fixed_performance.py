"""Fixed native searches reuse compiled scores without changing projections."""

import pytest

from tests.gear.test_fixed_reporting import fixed_inputs
from tests.gear.test_prayer_search_efficiency import search
from tools.benchmark_gear_desktop import without_observations
from tracker.gear.fixed_reporting import fixed_reporting
from tracker.gear.optimizer import optimize


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("priority", ["default", "accuracy", "stab_defence_roll"])
@pytest.mark.parametrize("equipment", [{}, {"weapon": 2}, {"weapon": 2, "head": 1}])
def test_fixed_native_projection_matches_python_without_python_score(
    monkeypatch, style, priority, equipment
):
    native = pytest.importorskip("tracker.gear.native._scoring")
    instance = search(fixed_inputs(style, priority))
    role = instance.request.roles[0]
    expected = instance.fixed_performance(equipment, role)
    instance.compact_cache.clear()
    instance.native_context = native.ScoringContext(instance)
    instance.performance_cache.clear()

    def unexpected(*args, **kwargs):
        pytest.fail("Fixed native projection evaluated ordinary scoring in Python")

    monkeypatch.setattr("tracker.gear.optimizer.evaluate_prepared_score", unexpected)
    with fixed_reporting():
        assert instance.search_performance(equipment, role) == expected
        assert instance.search_performance(equipment, role) == expected


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("priority", ["default", "stab_defence_roll"])
def test_fixed_native_complete_result_parity(style, priority):
    pytest.importorskip("tracker.gear.native._scoring")
    args = fixed_inputs(style, priority)
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
    }
    expected = optimize(*args, **flags)
    actual = optimize(*args, **flags, _native_search=True)
    assert without_observations(actual) == without_observations(expected)


def test_fixed_projection_preserves_unknown_defence_contract():
    native = pytest.importorskip("tracker.gear.native._scoring")
    instance = search(fixed_inputs("slash", "stab_defence_roll"))
    instance.levels = {key: value for key, value in instance.levels.items() if key != "defence"}
    role = instance.request.roles[0]
    expected = instance.fixed_performance({"weapon": 2}, role)
    instance.compact_cache.clear()
    instance.native_context = native.ScoringContext(instance)
    assert instance.fixed_performance({"weapon": 2}, role) == expected


def test_fixed_native_context_does_not_override_a_different_configured_role():
    native = pytest.importorskip("tracker.gear.native._scoring")
    instance = search(fixed_inputs("slash"))
    role = instance.request.roles[0].model_copy(update={"stance": "aggressive"})
    expected = instance.fixed_performance({"weapon": 2}, role)
    instance.compact_cache.clear()
    instance.native_context = native.ScoringContext(instance)
    assert instance.fixed_performance({"weapon": 2}, role) == expected


def test_fixed_native_multi_complete_archive_parity():
    pytest.importorskip("tracker.gear.native._scoring")
    from tests.gear.test_factored_multi import multi_case

    args = multi_case(False, priority="stab_defence_roll")
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
    }
    expected = optimize(*args, **flags)
    actual = optimize(*args, **flags, _native_search=True)
    assert without_observations(actual) == without_observations(expected)
