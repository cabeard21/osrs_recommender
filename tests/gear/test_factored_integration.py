"""Complete P1 execution stays isolated and retains complete public results."""

import pytest

from tests.gear.test_prayer_search_efficiency import scenario, search
from tools.benchmark_gear_desktop import without_observations
from tracker.gear.optimizer import optimize


@pytest.mark.parametrize("style,weapon", [("slash", 1), ("ranged", 2), ("magic", 3)])
def test_compact_combat_matches_full_without_reporting(monkeypatch, style, weapon):
    args = scenario(style)
    if style == "magic":
        role = args[1].roles[0]
        role = role.model_copy(
            update={
                "combat_options": role.combat_options.model_copy(update={"spells": ("powered:3",)}),
            }
        )
        args = (args[0], args[1].model_copy(update={"roles": (role,)}), *args[2:])
    instance = search(args)
    role = args[1].roles[0]
    equipment = {"weapon": weapon}
    expected = instance.performance(equipment, role)
    assert expected["supported"]
    option = instance.combat_option(equipment, role)
    instance.performance_cache.clear()
    instance.option_cache.clear()

    def unexpected(*args, **kwargs):
        pytest.fail("Compact scoring must not construct full reports")

    monkeypatch.setattr(instance, "evaluate", unexpected)
    monkeypatch.setattr("tracker.gear.optimizer.evaluate_prepared_loadout", unexpected)
    actual, selected = instance.compact_combat(equipment, role)
    assert selected == option
    for name in ("supported", "dps", "accuracy", "attack_interval"):
        assert actual.get(name) == expected.get(name)


def test_compact_combat_preserves_seeded_variant_override():
    args = scenario()
    instance = search(args)
    role = args[1].roles[0]
    equipment = {"weapon": 2}
    key = (role.id, tuple(equipment.items()))
    override = {"supported": True, "dps": 12345, "attack_interval": 1.2}
    option = {"attack_type": "ranged", "stance": "longrange", "__prayer_ids": ["rigour"]}
    instance.performance_cache[key] = override
    instance.option_cache[key] = option
    actual, selected = instance.compact_combat(equipment, role)
    assert actual is override
    assert selected == {"attack_type": "ranged", "stance": "longrange"}


@pytest.mark.parametrize("bad", [None, 0, 1, "true"])
def test_factored_flag_requires_boolean(bad):
    with pytest.raises(ValueError, match="factored evaluation"):
        optimize(*scenario(), _factored_evaluation=bad)


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("thorough", [False, True])
def test_complete_p1_archive_parity(style, thorough):
    args = scenario(style)
    options = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
        "local_refinement": thorough,
    }
    expected = optimize(*args, **options)
    actual = optimize(*args, **options, _factored_evaluation=True)
    assert without_observations(actual) == without_observations(expected)


def test_factored_context_cleanup_and_baseline_rollback():
    from tracker.gear.compact_costs import active as costs_active
    from tracker.gear.execution_profile import execution_context
    from tracker.gear.prepared_combat import active as combat_active
    from tracker.gear.ranged_score_finalization import active as finalization_active
    from tracker.gear.variant_reporting import active as variants_active

    checks = (costs_active, combat_active, finalization_active, variants_active)
    with (
        pytest.raises(RuntimeError),
        execution_context(
            "combined",
            scenario()[1],
            factored_evaluation=True,
        ),
    ):
        assert all(check() for check in checks)
        raise RuntimeError("cancelled")
    assert not any(check() for check in checks)
    with execution_context("baseline", scenario()[1], factored_evaluation=True):
        assert not any(check() for check in checks)


def test_full_p1_multi_context_is_explicit_and_cleans_up():
    from tracker.gear.execution_profile import execution_context, factored_evaluation_active
    from tracker.gear.fixed_reporting import active as fixed_active
    from tracker.gear.lazy_reporting import active as lazy_active

    request = scenario()[1]
    request = request.model_copy(update={
        "roles": (request.roles[0], request.roles[0].model_copy(update={"id": "second"})),
    })
    with execution_context("combined", request, fixed_reporting=True):
        assert not lazy_active() and not fixed_active() and not factored_evaluation_active()
    with pytest.raises(ValueError), execution_context(
        "combined", request, fixed_reporting=True, factored_evaluation=True,
    ):
        assert lazy_active() and fixed_active() and factored_evaluation_active()
        raise ValueError("optimization_cancelled")
    assert not lazy_active() and not fixed_active() and not factored_evaluation_active()
