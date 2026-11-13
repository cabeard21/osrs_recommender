import pytest

from tracker.gear.combat import evaluate_loadout
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.ranged_numerics import ranged_experiment


def weapon():
    return EquipmentDefinition(
        id=1,
        name="Bow",
        slot="weapon",
        attack_styles=("ranged",),
        bonuses=EquipmentBonuses(ranged=30, ranged_strength=20),
    )


def test_cache_preserves_candidate_reporting_and_resets():
    bow = weapon()
    body = EquipmentDefinition(
        id=2, name="Body", slot="body", bonuses=EquipmentBonuses(defence_ranged=40)
    )
    baseline = evaluate_loadout([bow, body], "ranged", {"ranged": 70})
    with ranged_experiment(capacity=2, observe=True) as experiment:
        evaluate_loadout([bow], "ranged", {"ranged": 70})
        assert evaluate_loadout([bow, body], "ranged", {"ranged": 70}) == baseline
        assert experiment.cache_info().hits == 1
        assert len(experiment.accesses) == 2
    with ranged_experiment(capacity=2) as experiment:
        evaluate_loadout([bow], "ranged", {"ranged": 70})
        assert experiment.cache_info().misses == 1


def test_context_invalidation_and_eviction():
    with ranged_experiment(capacity=1) as experiment:
        for level in (70, 71, 70):
            evaluate_loadout([weapon()], "ranged", {"ranged": level})
        assert experiment.cache_info().hits == 0
        assert experiment.cache_info().misses == 3
        assert experiment.cache_info().currsize == 1
    with pytest.raises(ValueError), ranged_experiment(capacity=-1):
        pass


@pytest.mark.parametrize("stance", ["accurate", "rapid", "longrange"])
@pytest.mark.parametrize("armour", [-3, 0, 5])
@pytest.mark.parametrize("pattern", ["single", "double", "conditional_double"])
def test_cached_matches_uncached(stance, armour, pattern):
    from tracker.gear.models import CombatTarget

    bow = weapon().model_copy(update={"attack_pattern": pattern})
    args = ([bow], "ranged", {"ranged": 70}, CombatTarget(flat_armour=armour))
    baseline = evaluate_loadout(*args, stance=stance)
    with ranged_experiment(capacity=2, observe=True) as experiment:
        assert evaluate_loadout(*args, stance=stance) == baseline
        assert evaluate_loadout(*args, stance=stance) == baseline
        assert experiment.cache_info().hits == 1


@pytest.mark.parametrize("cap", [1, None])
@pytest.mark.parametrize("kind", ["bolt:fixture", "arrow:fixture", None])
def test_subtypes_caps_scalar_and_ammunition(kind, cap):
    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.models import CombatTarget
    from tracker.gear.optimizer import RoleConfig
    from tracker.gear.scoring import prepare_equipment

    bow = weapon().model_copy(update={"ammo_for": (kind,) if kind else ()})
    ammo = EquipmentDefinition(
        id=3,
        name="Ammo",
        slot="ammunition",
        ammo_type=kind,
        bonuses=EquipmentBonuses(ranged=10, ranged_strength=30),
    )
    prepared = prepare_equipment([bow, ammo])
    role = RoleConfig(
        id="ranged",
        style="ranged",
        target=CombatTarget(damage_cap=cap, ranged_heavy=100, ranged_standard=50, ranged_light=10),
    )
    levels = {"ranged": 70, "defence": 50, "magic": 50}
    from tracker.gear.combat import evaluate_prepared_loadout

    reference = evaluate_prepared_loadout(prepared, role, levels)
    score = evaluate_prepared_score(prepared, role, levels, include_defence=True)
    with ranged_experiment(capacity=3) as experiment:
        assert evaluate_prepared_loadout(prepared, role, levels) == reference
        assert evaluate_prepared_score(prepared, role, levels, include_defence=True) == score
        assert experiment.cache_info().hits == 1


def test_unsupported_does_not_enter_cache():
    bow = weapon().model_copy(update={"unsupported_effects": ("Unreviewed",)})
    with ranged_experiment(capacity=1) as experiment:
        assert not evaluate_loadout([bow], "ranged", {"ranged": 70}).supported
        assert experiment.cache_info().misses == 0


def test_observer_times_only_key_construction(monkeypatch):
    from tracker.gear import combat
    from tracker.gear.ranged_numerics import observer

    assert observer() is None
    ticks = iter((10.0, 10.25))
    monkeypatch.setattr(combat, "perf_counter", lambda: next(ticks))
    with ranged_experiment(capacity=1, observe=True) as experiment:
        evaluate_loadout([weapon()], "ranged", {"ranged": 70})
        assert experiment.key_seconds == 0.25
    with ranged_experiment(capacity=1) as experiment:
        # The exhausted clock proves timing is not invoked without observation.
        evaluate_loadout([weapon()], "ranged", {"ranged": 70})
        assert experiment.key_seconds == 0.0
