import pytest

from tests.gear.test_prayer_search_efficiency import scenario, search
from tools.benchmark_gear_desktop import without_observations
from tracker.gear.fixed_reporting import active, fixed_reporting
from tracker.gear.optimizer import optimize
from tracker.gear.prayers import PrayerPolicy


def fixed_inputs(style="ranged", priority="balanced_defence"):
    args = list(scenario(style))
    role = args[1].roles[0].model_copy(update={"combat_options": None, "prayers": PrayerPolicy()})
    args[1] = args[1].model_copy(update={"roles": (role,), "secondary_priority": priority})
    return args


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("priority", ["balanced_defence", "accuracy", "ranged_defence_roll"])
@pytest.mark.parametrize("thorough", [False, True])
def test_fixed_complete_parity(style, priority, thorough):
    args = fixed_inputs(style, priority)
    options = {
        "_execution_profile": "combined",
        "local_refinement": thorough,
        "_complete_frontiers": True,
        "_running_frontier": True,
    }
    expected = optimize(*args, **options)
    with fixed_reporting():
        actual = optimize(*args, **options)
    assert without_observations(actual) == without_observations(expected)
    assert not active()


def test_projection_defers_reports_and_honors_full_cache(monkeypatch):
    args = fixed_inputs()
    instance = search(args)
    role = args[1].roles[0]
    equipment = {"weapon": 2}
    expected = instance.performance(equipment, role)
    instance.performance_cache.clear()

    def unexpected(*a, **k):
        pytest.fail("Partial scoring constructed a full report")

    monkeypatch.setattr("tracker.gear.optimizer.evaluate_prepared_loadout", unexpected)
    with fixed_reporting():
        projected = instance.search_performance(equipment, role)
        assert projected["dps"] == expected["dps"]
        key = (role.id, tuple(sorted(equipment.items())))
        instance.performance_cache[key] = expected
        assert instance.search_performance(equipment, role) is expected


def test_context_resets_and_cancellation():
    instance = search(fixed_inputs())
    instance.performance_cache.clear()
    instance.cancelled = lambda: True
    with pytest.raises(ValueError, match="optimization_cancelled"), fixed_reporting():
        instance.search_performance({}, instance.request.roles[0])
    assert not active()


@pytest.mark.parametrize("equipment", [{}, {"weapon": 2}, {"head": 2}])
@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
def test_fixed_projection_matches_full_on_partial_and_invalid_states(equipment, style):
    args = fixed_inputs(style, "ranged_defence_roll")
    instance = search(args)
    role = args[1].roles[0]
    expected = instance.performance(equipment, role)
    instance.performance_cache.clear()
    with fixed_reporting():
        result = instance.search_performance(equipment, role)
    for key in ("supported", "dps", "accuracy", "bonuses"):
        assert result.get(key) == expected.get(key)


def test_ancient_extra_eligibility_is_preserved(monkeypatch):
    args = fixed_inputs("magic")
    instance = search(args)
    role = args[1].roles[0]
    monkeypatch.setattr(
        "tracker.gear.optimizer.ancient_spell_problem", lambda *a: "Unavailable ancient"
    )
    instance.performance_cache.clear()
    expected = instance.performance({"weapon": 2}, role)
    instance.performance_cache.clear()
    with fixed_reporting():
        result = instance.search_performance({"weapon": 2}, role)
        assert not result["supported"]
        assert result["dps"] is None
        assert result["bonuses"] == expected["bonuses"]


def test_fixed_scope_excludes_subclasses_and_other_roles():
    from tracker.gear.optimizer import _Search

    args = fixed_inputs()
    instance = search(args)
    role = args[1].roles[0]

    class CostSearch(_Search):
        pass

    cost = CostSearch.__new__(CostSearch)
    cost.__dict__ = dict(instance.__dict__)
    with fixed_reporting():
        assert instance.fixed_eligible(role)
        assert not cost.fixed_eligible(role)
        assert not instance.fixed_eligible(role.model_copy(update={"style": "special"}))
        assert not instance.fixed_eligible(scenario()[1].roles[0])
        instance.request = instance.request.model_copy(update={"roles": (role, role)})
        assert not instance.fixed_eligible(role)


@pytest.mark.parametrize(
    "target_updates",
    [{"damage_cap": 10}, {"flat_armour": 3}, {"unsupported_mechanics": ("Unknown target effect",)}],
)
@pytest.mark.parametrize("priority", ["balanced_defence", "accuracy", "ranged_defence_roll"])
def test_fixed_target_support_and_secondary_parity(target_updates, priority):
    from tracker.gear.models import CombatTarget

    args = fixed_inputs("ranged", priority)
    role = (
        args[1]
        .roles[0]
        .model_copy(update={"stance": "rapid", "target": CombatTarget(**target_updates)})
    )
    args[1] = args[1].model_copy(update={"roles": (role,)})
    instance = search(args)
    equipment = {"weapon": 2}
    expected = instance.performance(equipment, role)
    expected_secondary = instance.secondary({role.id: equipment})
    instance.performance_cache.clear()
    with fixed_reporting():
        actual = instance.search_performance(equipment, role)
        assert instance.search_secondary(equipment, (role,)) == expected_secondary
    for key in ("supported", "dps", "accuracy", "bonuses"):
        assert actual[key] == expected[key]


def test_fixed_powered_full_archive_parity():
    args = fixed_inputs("magic")
    role = args[1].roles[0].model_copy(update={"powered_attack": "fixture", "locks": {"weapon": 3}})
    args[1] = args[1].model_copy(update={"roles": (role,)})
    options = {
        "_execution_profile": "combined",
        "_complete_frontiers": True,
        "_running_frontier": True,
    }
    expected = optimize(*args, **options)
    assert expected["selected_solution"] is not None
    loadout = expected["selected_solution"]["loadouts"][role.id]
    assert loadout["equipment"]["weapon"] == 3
    assert loadout["performance"]["supported"]
    with fixed_reporting():
        actual = optimize(*args, **options)
    assert without_observations(actual) == without_observations(expected)


def test_fixed_real_ancient_rejection():
    args = fixed_inputs("magic")
    role = args[1].roles[0].model_copy(update={"spell": "ice_burst"})
    args[1] = args[1].model_copy(update={"roles": (role,)})
    instance = search(args)
    expected = instance.performance({}, role)
    assert not expected["supported"]
    assert expected["limitations"]
    instance.performance_cache.clear()
    with fixed_reporting():
        actual = instance.search_performance({}, role)
    assert actual["supported"] is False
    assert actual["dps"] is None
    assert actual["bonuses"] == expected["bonuses"]


def test_fixed_context_nested_reset():
    assert not active()
    with fixed_reporting():
        assert active()
        with fixed_reporting():
            assert active()
        assert active()
        with pytest.raises(RuntimeError), fixed_reporting():
            raise RuntimeError("test")
        assert active()
    assert not active()


def test_fixed_ammunition_mismatch_parity():
    from types import SimpleNamespace

    from tracker.gear.models import EquipmentDefinition

    args = fixed_inputs("ranged")
    items = dict(args[2].items)
    items[2] = items[2].model_copy(update={"ammo_for": ("arrow",)})
    items[4] = EquipmentDefinition(id=4, name="Wrong bolt", slot="ammunition", ammo_type="bolt")
    args[2] = SimpleNamespace(items=items, version=args[2].version)
    role = args[1].roles[0].model_copy(update={"stance": "rapid"})
    args[1] = args[1].model_copy(update={"roles": (role,)})
    instance = search(args)
    equipment = {"weapon": 2, "ammunition": 4}
    expected = instance.performance(equipment, role)
    assert not expected["supported"]
    instance.performance_cache.clear()
    with fixed_reporting():
        actual = instance.search_performance(equipment, role)
    for key in ("supported", "dps", "accuracy", "bonuses"):
        assert actual[key] == expected[key]
