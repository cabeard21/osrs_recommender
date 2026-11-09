"""Complete result parity for opt-in partial-state reporting."""

import pytest

from tests.gear.test_frontier_evaluation_reuse import scenario
from tools.benchmark_gear_desktop import without_observations as without_timings
from tracker.gear.lazy_reporting import active, lazy_reporting


@pytest.mark.parametrize(
    "priority", ["balanced_defence", "accuracy", "ranged_defence_roll", "magic_ranged_defence_roll"]
)
def test_complete_parity(priority):
    reference = scenario(priority)
    with lazy_reporting():
        assert active()
        result = scenario(priority)
    assert not active()
    assert without_timings(reference) == without_timings(result)


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("priority", ["balanced_defence", "accuracy", "ranged_defence_roll"])
@pytest.mark.parametrize("thorough", [False, True])
def test_prayer_potion_archives(style, priority, thorough):
    from tests.gear.test_prayer_search_efficiency import scenario as inputs
    from tracker.gear.optimizer import optimize
    from tracker.gear.potions import PotionPolicy
    from tracker.gear.prayers import PrayerPolicy

    args = list(
        inputs(
            style,
            PrayerPolicy(
                mode="optimize", allowed_ids=("steel_skin", "eagle_eye", "ultimate_strength")
            ),
        )
    )
    args[1] = args[1].model_copy(
        update={
            "secondary_priority": priority,
            "potions": PotionPolicy(mode="fixed", selected_ids=("ranging",)),
        }
    )
    reference = optimize(
        *args, local_refinement=thorough, _complete_frontiers=True, _running_frontier=True
    )
    with lazy_reporting():
        result = optimize(
            *args, local_refinement=thorough, _complete_frontiers=True, _running_frontier=True
        )
    assert without_timings(reference) == without_timings(result)


def test_partial_reporting_decreases(monkeypatch):
    from tracker.gear import optimizer

    original = optimizer.evaluate_prepared_loadout
    calls = []

    def counted(*a, **k):
        calls.append(1)
        return original(*a, **k)

    monkeypatch.setattr(optimizer, "evaluate_prepared_loadout", counted)
    from tests.gear.test_prayer_search_efficiency import scenario as inputs
    from tests.gear.test_prayer_search_efficiency import search

    args = inputs()
    ordinary = search(args)
    lazy = search(args)
    ordinary.performance_cache.clear()
    lazy.performance_cache.clear()
    calls.clear()
    baseline = ordinary.performance({"weapon": 2}, args[1].roles[0])
    original_count = len(calls)
    calls.clear()
    with lazy_reporting():
        result = lazy.search_performance({"weapon": 2}, args[1].roles[0])
    assert baseline["dps"] == result["dps"]
    assert len(calls) < original_count


def test_authoritative_full_override_and_winner_reuse(monkeypatch):
    from tests.gear.test_prayer_search_efficiency import scenario as inputs
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear import optimizer

    args = inputs()
    instance = search(args)
    role = args[1].roles[0]
    equipment = {"weapon": 2}
    instance.performance_cache.clear()
    instance.option_cache.clear()
    with lazy_reporting():
        instance.search_performance(equipment, role)
        assert instance.compact_cache

        def unexpected(*args, **kwargs):
            pytest.fail("Materialization rescored options")

        monkeypatch.setattr(optimizer, "evaluate_prepared_score", unexpected)
        full = instance.performance(equipment, role)
        assert full["supported"]
        key = (role.id, tuple(sorted(equipment.items())))
        override = {"supported": True, "dps": 123456}
        instance.performance_cache[key] = override
        assert instance.search_performance(equipment, role) is override


def test_context_recovers_after_cancellation():
    with pytest.raises(ValueError), lazy_reporting():
        raise ValueError("optimization_cancelled")
    assert not active()


def test_no_legal_option_projection_has_no_candidate_bonuses():
    from tests.gear.test_prayer_search_efficiency import scenario as inputs
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear.optimizer import CombatOptionFilters

    args = list(inputs())
    args[1] = args[1].model_copy(
        update={
            "secondary_priority": "balanced_defence",
            "roles": (
                args[1]
                .roles[0]
                .model_copy(
                    update={
                        "combat_options": CombatOptionFilters(
                            attack_types=(), stances=(), spells=()
                        )
                    }
                ),
            ),
        }
    )
    instance = search(args)
    role = args[1].roles[0]
    with lazy_reporting():
        instance.performance_cache.clear()
        projected = instance.search_performance({"weapon": 2}, role)
        assert projected == {"supported": False, "dps": None}
        assert instance.search_secondary({"weapon": 2}, (role,)) == 0


def test_fallbacks_keep_original_reporting():
    from tests.gear.test_prayer_search_efficiency import scenario as inputs
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear.optimizer import _Search
    from tracker.gear.prayers import PrayerPolicy

    args = inputs()
    instance = search(args)
    role = args[1].roles[0]
    fixed = role.model_copy(update={"combat_options": None, "prayers": PrayerPolicy()})
    special = role.model_copy(update={"style": "special"})

    class CostSearch(_Search):
        pass

    cost = CostSearch.__new__(CostSearch)
    cost.__dict__ = dict(instance.__dict__)
    with lazy_reporting():
        assert not instance.lazy_eligible(fixed)
        assert not instance.lazy_eligible(special)
        assert not cost.lazy_eligible(role)
        instance.request = instance.request.model_copy(
            update={"roles": (role, role.model_copy(update={"id": "b"}))}
        )
        assert not instance.lazy_eligible(role)


def test_default_performance_prepares_once(monkeypatch):
    from tests.gear.test_prayer_search_efficiency import scenario as inputs
    from tests.gear.test_prayer_search_efficiency import search

    args = inputs()
    instance = search(args)
    role = args[1].roles[0]
    instance.performance_cache.clear()
    original = instance.prepare
    calls = []

    def counted(equipment):
        calls.append(1)
        return original(equipment)

    monkeypatch.setattr(instance, "prepare", counted)
    instance.performance({"weapon": 2}, role)
    assert len(calls) == 1
