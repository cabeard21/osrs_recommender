from types import SimpleNamespace

import pytest

from tests.gear.test_fixed_reporting import fixed_inputs
from tests.gear.test_prayer_search_efficiency import scenario
from tools.benchmark_gear_desktop import without_observations
from tracker.gear import combat
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import optimize
from tracker.gear.ranged_numerics import ranged_experiment
from tracker.gear.ranged_score_finalization import active, ranged_score_finalization
from tracker.gear.scoring import prepare_equipment


def inputs(stance="rapid", pattern="single", armour=0, cap=None, prayers=()):
    prepared = prepare_equipment(
        [
            EquipmentDefinition(
                id=1,
                name="Fixture bow",
                slot="weapon",
                attack_styles=("ranged",),
                attack_pattern=pattern,
                bonuses=EquipmentBonuses(ranged=30, ranged_strength=38, defence_magic=14),
            )
        ]
    )
    role = SimpleNamespace(
        style="ranged",
        stance=stance,
        active_prayer_ids=prayers,
        target=CombatTarget(defence_level=115, flat_armour=armour, damage_cap=cap),
    )
    return prepared, role, {"ranged": 85, "defence": 78, "magic": 90}


@pytest.mark.parametrize("stance", ["accurate", "rapid", "longrange"])
@pytest.mark.parametrize("pattern", ["single", "independent_double", "conditional_double"])
@pytest.mark.parametrize("armour", [-4, 0, 6])
@pytest.mark.parametrize("cap", [None, 1, 50])
@pytest.mark.parametrize("prayers", [(), ("rigour",)])
@pytest.mark.parametrize("include_defence", [False, True])
def test_cached_score_matches_original_and_full(
    stance, pattern, armour, cap, prayers, include_defence
):
    args = inputs(stance, pattern, armour, cap, prayers)
    expected = combat.evaluate_prepared_score(*args, include_defence=include_defence)
    with ranged_experiment(4):
        cached = combat.evaluate_prepared_score(*args, include_defence=include_defence)
        with ranged_score_finalization():
            first = combat.evaluate_prepared_score(*args, include_defence=include_defence)
            second = combat.evaluate_prepared_score(*args, include_defence=include_defence)
            full = combat.evaluate_prepared_loadout(*args)
    assert first == second == cached == expected
    assert first.supported == full.supported
    assert first.dps == full.dps
    assert first.accuracy == full.accuracy
    if first.supported and include_defence:
        assert dict(first.player_defence_rolls) == full.player_defence_rolls.model_dump(
            exclude={"limitations"}
        )


def test_direct_score_does_not_reconstruct_cached_numerics(monkeypatch):
    args = inputs()
    expected = combat.evaluate_prepared_score(*args)

    def unexpected(*args, **kwargs):
        pytest.fail("Cached outgoing score repeated numerical finalization")

    with ranged_experiment(4), ranged_score_finalization():
        monkeypatch.setattr(combat, "max", unexpected, raising=False)
        assert combat.evaluate_prepared_score(*args) == expected


@pytest.mark.parametrize("levels", [{"ranged": 1}, {"ranged": 99}, {"ranged": 0}, {}])
def test_level_and_unknown_defence_parity(levels):
    prepared, role, _ = inputs()
    expected = combat.evaluate_prepared_score(prepared, role, levels, include_defence=True)
    with ranged_experiment(4), ranged_score_finalization():
        assert (
            combat.evaluate_prepared_score(prepared, role, levels, include_defence=True) == expected
        )


@pytest.mark.parametrize("problem", ["ammo", "shield", "effect", "target", "stance"])
def test_original_legality_runs_before_finalization(problem):
    prepared, role, levels = inputs()
    weapon = prepared.weapon
    equipment = [weapon]
    if problem == "ammo":
        equipment = [weapon.model_copy(update={"ammo_for": ("arrow:fixture",)})]
    elif problem == "shield":
        equipment = [
            weapon.model_copy(update={"two_handed": True}),
            EquipmentDefinition(id=2, name="Shield", slot="shield"),
        ]
    elif problem == "effect":
        equipment = [weapon.model_copy(update={"unsupported_effects": ("Unknown",)})]
    elif problem == "target":
        role.target = CombatTarget(unsupported_mechanics=("Unknown",))
    else:
        role.stance = "aggressive"
    prepared = prepare_equipment(equipment)
    expected = combat.evaluate_prepared_score(prepared, role, levels, include_defence=True)
    assert not expected.supported
    with ranged_experiment(4), ranged_score_finalization():
        assert (
            combat.evaluate_prepared_score(prepared, role, levels, include_defence=True) == expected
        )


def test_scope_and_nested_exception_cleanup():
    args = inputs()
    expected = combat.evaluate_prepared_score(*args)
    assert not active()
    with ranged_score_finalization():
        assert active()
        # Without the numerical cache there is no outgoing record to consume.
        assert combat.evaluate_prepared_score(*args) == expected
        with pytest.raises(RuntimeError, match="fixture"), ranged_score_finalization():
            raise RuntimeError("fixture")
        assert active()
    assert not active()


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("fixed", [False, True])
@pytest.mark.parametrize("thorough", [False, True])
def test_complete_fixture_archive_parity(style, fixed, thorough):
    args = fixed_inputs(style) if fixed else scenario(style)
    options = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
        "local_refinement": thorough,
    }
    expected = optimize(*args, **options)
    with ranged_score_finalization():
        actual = optimize(*args, **options)
    assert without_observations(actual) == without_observations(expected)


def test_full_report_remains_unchanged():
    args = inputs(prayers=("rigour",))
    with ranged_experiment(4):
        expected = combat.evaluate_prepared_loadout(*args)
        with ranged_score_finalization():
            actual = combat.evaluate_prepared_loadout(*args)
    assert actual == expected


@pytest.mark.parametrize(
    "ammo_kind,subtype", [("bolt:fixture", "heavy"), ("arrow:fixture", "standard"), (None, "light")]
)
@pytest.mark.parametrize("subtype_bonus", [None, 140])
def test_ammunition_and_target_subtype_parity(ammo_kind, subtype, subtype_bonus):
    prepared, role, levels = inputs()
    weapon = prepared.weapon.model_copy(update={"ammo_for": (ammo_kind,) if ammo_kind else ()})
    ammunition = EquipmentDefinition(
        id=2,
        name="Fixture ammunition",
        slot="ammunition",
        ammo_type=ammo_kind or "arrow:fixture",
        bonuses=EquipmentBonuses(ranged=10, ranged_strength=25),
    )
    prepared = prepare_equipment([weapon, ammunition])
    role.target = CombatTarget(
        defence_level=115,
        bonuses={"ranged": 5},
        **{"ranged_" + subtype: subtype_bonus},
    )
    expected = combat.evaluate_prepared_score(prepared, role, levels, include_defence=True)
    full = combat.evaluate_prepared_loadout(prepared, role, levels)
    assert full.supported
    assert full.defence_roll == 124 * ((5 if subtype_bonus is None else subtype_bonus) + 64)
    with ranged_experiment(4), ranged_score_finalization():
        assert (
            combat.evaluate_prepared_score(prepared, role, levels, include_defence=True) == expected
        )
        assert combat.evaluate_prepared_loadout(prepared, role, levels) == full
    if ammo_kind is None:
        assert expected.bonuses.ranged_strength == weapon.bonuses.ranged_strength
    else:
        assert expected.bonuses.ranged_strength == (
            weapon.bonuses.ranged_strength + ammunition.bonuses.ranged_strength
        )


@pytest.mark.parametrize("pattern", ["single", "independent_double", "conditional_double"])
@pytest.mark.parametrize("below_boundary", [False, True])
def test_exact_per_hitsplat_damage_cap_boundary(pattern, below_boundary):
    prepared, role, levels = inputs(pattern=pattern)
    full = combat.evaluate_prepared_loadout(prepared, role, levels)
    boundary = max(hitsplat.max_hit for hitsplat in full.hitsplats)
    role.target = role.target.model_copy(update={"damage_cap": boundary - int(below_boundary)})
    expected = combat.evaluate_prepared_score(prepared, role, levels, include_defence=True)
    assert expected.supported is not below_boundary
    with ranged_experiment(4), ranged_score_finalization():
        assert (
            combat.evaluate_prepared_score(prepared, role, levels, include_defence=True) == expected
        )


@pytest.mark.parametrize("pattern", ["single", "independent_double", "conditional_double"])
def test_zero_maximum_preserves_accurate_zero_damage_and_cap(pattern):
    prepared, role, _ = inputs(pattern=pattern, cap=1)
    weapon = prepared.weapon.model_copy(
        update={"bonuses": EquipmentBonuses(ranged=30, ranged_strength=-64)}
    )
    prepared = prepare_equipment([weapon])
    levels = {"ranged": 1}
    expected = combat.evaluate_prepared_score(prepared, role, levels, include_defence=True)
    full = combat.evaluate_prepared_loadout(prepared, role, levels)
    assert expected.supported
    assert full.supported
    assert expected.dps == full.dps
    assert expected.dps > 0
    with ranged_experiment(4), ranged_score_finalization():
        assert (
            combat.evaluate_prepared_score(prepared, role, levels, include_defence=True) == expected
        )
