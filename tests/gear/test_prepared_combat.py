"""Differential checks against the retained, unfactored combat path."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from tracker.gear import combat
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.prepared_combat import active, freeze_levels, prepared_combat
from tracker.gear.ranged_numerics import ranged_experiment
from tracker.gear.ranged_score_finalization import ranged_score_finalization
from tracker.gear.scoring import prepare_equipment


@pytest.mark.parametrize(
    "item_ids,spell,pages",
    [
        ((34425,), "fire_surge", "burnt"),
        ((20714,), "fire_surge", "searing"),
        ((34425, 20714), "fire_surge", "searing"),
        ((25574,), "water_surge", "burnt"),
    ],
)
def test_prepared_spell_effects_retain_reference_reports_and_scores(
    make_content, item_ids, spell, pages
):
    from tracker.gear.catalog import load_catalog

    catalog = load_catalog(make_content())
    equipment = prepare_equipment([catalog.items[i] for i in item_ids])
    role = SimpleNamespace(
        style="magic",
        stance="accurate",
        spell=spell,
        fire_tome_pages=pages,
        target=CombatTarget(weakness_element=spell.split("_")[0], weakness_percent=50),
    )
    levels = {"magic": 99, "defence": 80}
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    score = combat.evaluate_prepared_score(equipment, role, levels, include_defence=True)
    assert expected.supported
    assert expected.dps == score.dps
    with prepared_combat(), ranged_score_finalization():
        assert combat.evaluate_prepared_loadout(equipment, role, levels) == expected
        assert (
            combat.evaluate_prepared_score(equipment, role, levels, include_defence=True) == score
        )


@pytest.mark.parametrize("family", [None, "opal", "ruby", "diamond", "onyx"])
@pytest.mark.parametrize("hopper", [False, True])
@pytest.mark.parametrize("cap", [None, 30])
def test_prepared_ranged_effects_retain_reference_reports_and_scores(family, hopper, cap):
    weapon = EquipmentDefinition(
        id=9185,
        name="Crossbow",
        slot="weapon",
        attack_styles=("ranged",),
        ammo_for=("bolt:fixture",),
    )
    ammo = EquipmentDefinition(
        id=3,
        name="Bolt",
        slot="ammunition",
        ammo_type="bolt:fixture",
        bolt_effect=family,
        bonuses=EquipmentBonuses(ranged_strength=100),
    )
    shield = EquipmentDefinition(id=32879, name="Hopper", slot="shield")
    equipment = prepare_equipment([weapon, ammo, *([shield] if hopper else [])])
    role = SimpleNamespace(
        style="ranged",
        stance="rapid",
        bolt_diary_boost=True,
        bolt_diary_known=True,
        target=CombatTarget(hitpoints=500, damage_cap=cap),
    )
    levels = {"ranged": 99, "magic": 80, "defence": 80}
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    score = combat.evaluate_prepared_score(equipment, role, levels, include_defence=True)
    assert expected.dps == score.dps
    with prepared_combat(), ranged_experiment(), ranged_score_finalization():
        assert combat.evaluate_prepared_loadout(equipment, role, levels) == expected
        assert (
            combat.evaluate_prepared_score(equipment, role, levels, include_defence=True) == score
        )


def case(style="slash", stance="accurate", spell="fire_wave", pattern="single"):
    weapon = EquipmentDefinition(
        id=1,
        name="Fixture",
        slot="weapon",
        attack_styles=("slash", "stab", "crush", "ranged"),
        attack_pattern=pattern,
        spell_compatibility=("fire_wave", "wind_strike", "ice_barrage", "iban_blast"),
        bonuses=EquipmentBonuses(
            slash=45,
            stab=18,
            crush=9,
            melee_strength=66,
            ranged=30,
            ranged_strength=38,
            magic=12,
            magic_damage=15.5,
            defence_magic=30,
        ),
    )
    role = SimpleNamespace(
        style=style,
        stance=stance,
        spell=spell,
        active_prayer_ids=(),
        target=CombatTarget(defence_level=125, magic_level=150),
    )
    levels = {"attack": 91, "strength": 87, "ranged": 85, "magic": 99, "defence": 78}
    return prepare_equipment([weapon]), role, levels


@pytest.mark.parametrize(
    "style,stance",
    [
        ("slash", "accurate"),
        ("stab", "controlled"),
        ("crush", "aggressive"),
        ("slash", "defensive"),
        ("ranged", "rapid"),
        ("ranged", "longrange"),
        ("magic", "accurate"),
        ("magic", "defensive"),
    ],
)
@pytest.mark.parametrize("pattern", ["single", "independent_double", "conditional_double"])
@pytest.mark.parametrize("armour,cap", [(-4, None), (0, 1), (6, 50)])
@pytest.mark.parametrize("prayed", [False, True])
def test_complete_numeric_and_report_parity(style, stance, pattern, armour, cap, prayed):
    equipment, role, levels = case(style, stance, pattern=pattern)
    role.target = CombatTarget(
        defence_level=125,
        magic_level=150,
        flat_armour=armour,
        damage_cap=cap,
        weakness_element="fire",
        weakness_percent=35,
    )
    if prayed:
        role.active_prayer_ids = (
            "augury" if style == "magic" else "rigour" if style == "ranged" else "piety",
        )
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    score = combat.evaluate_prepared_score(equipment, role, levels, include_defence=True)
    with prepared_combat() as context:
        actual = combat.evaluate_prepared_loadout(equipment, role, levels)
        first = combat.evaluate_prepared_score(equipment, role, levels, include_defence=True)
        second = combat.evaluate_prepared_score(equipment, role, levels)
        assert context.cache_info().hits >= 2
    assert actual == expected
    assert first == score
    assert second == score._replace(player_defence_rolls=None)


@pytest.mark.parametrize("spell", ["wind_strike", "fire_wave", "ice_barrage", "iban_blast"])
@pytest.mark.parametrize("weakness", [None, "air", "fire"])
def test_spell_base_and_weakness(spell, weakness):
    equipment, role, levels = case("magic", spell=spell)
    if spell == "iban_blast":
        equipment = prepare_equipment([equipment.weapon.model_copy(update={"id": 1409})])
    role.target = CombatTarget(weakness_element=weakness, weakness_percent=50 if weakness else 0)
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    with prepared_combat():
        assert combat.evaluate_prepared_loadout(equipment, role, levels) == expected


@pytest.mark.parametrize("model", ["seas", "swamp", "shadow", "sanguinesti", "bone", None])
def test_powered_models(model):
    equipment, role, levels = case("magic")
    weapon = equipment.weapon.model_copy(
        update={
            "powered_attack": "fixture",
            "powered_attack_model": model,
            "powered_attack_base_max_hit": 28,
            "powered_attack_stances": ("accurate",),
        }
    )
    equipment = prepare_equipment([weapon])
    role.powered_attack = "fixture"
    role.target = CombatTarget(traits=("rat",), weakness_element="fire", weakness_percent=50)
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    expected_score = combat.evaluate_prepared_score(equipment, role, levels, include_defence=True)
    with prepared_combat():
        assert combat.evaluate_prepared_loadout(equipment, role, levels) == expected
        assert (
            combat.evaluate_prepared_score(equipment, role, levels, include_defence=True)
            == expected_score
        )


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("include_defence", [False, True])
def test_prepared_single_score_avoids_hitsplat_collection(monkeypatch, style, include_defence):
    equipment, role, levels = case(style)
    expected = combat.evaluate_prepared_score(
        equipment, role, levels, include_defence=include_defence
    )

    def forbidden_zip(*args, **kwargs):
        pytest.fail("single-attack score reconstructed a hitsplat collection")

    with prepared_combat():
        monkeypatch.setattr(combat, "zip", forbidden_zip, raising=False)
        assert (
            combat.evaluate_prepared_score(equipment, role, levels, include_defence=include_defence)
            == expected
        )


@pytest.mark.parametrize("armour", [-10, 0, 6])
@pytest.mark.parametrize(
    "maximum,cap_offset,sanguinesti",
    [
        (maximum, offset, sanguinesti)
        for maximum in (0, 1, 30)
        for offset in (-1, 0, 1)
        for sanguinesti in (False, True)
        if max(1, maximum) + (8 if sanguinesti else 0) + offset >= 1
    ],
)
def test_prepared_single_score_cap_and_zero_boundaries(armour, maximum, cap_offset, sanguinesti):
    from dataclasses import replace
    from unittest.mock import patch

    from tracker.gear.prayers import NO_PRAYERS

    equipment, role, levels = case("magic" if sanguinesti else "slash")
    target = CombatTarget(
        flat_armour=armour,
        damage_cap=max(1, maximum) + (8 if sanguinesti else 0) + cap_offset,
    )
    # A direct immutable fixture isolates numerical finalization, including zero
    # maximum hits and the Sanguinesti proc's extra eight-damage cap threshold.
    with prepared_combat() as context:
        constants = context.prepare(
            equipment.weapon, role.style, levels, target, role.stance, role.spell, None, NO_PRAYERS
        )
    constants = replace(constants, sanguinesti=sanguinesti)
    bonuses = EquipmentBonuses()

    with patch.object(type(constants), "rolls", return_value=(maximum, 1000, 0)):
        actual = combat._calculate(
            equipment.weapon,
            role.style,
            levels,
            target,
            role.stance,
            role.spell,
            bonuses,
            None,
            score_only=True,
            include_defence=True,
            _constants=constants,
        )
        report = combat._calculate(
            equipment.weapon,
            role.style,
            levels,
            target,
            role.stance,
            role.spell,
            bonuses,
            None,
            _constants=constants,
        )
    assert actual.supported == report.supported
    assert actual.dps == report.dps
    assert actual.accuracy == report.accuracy


@pytest.mark.parametrize(
    "dependency",
    [
        "attack",
        "strength",
        "ranged",
        "magic",
        "defence",
        "prayers",
        "target",
        "stance",
        "spell",
        "weapon",
        "bonus",
    ],
)
def test_changed_dependencies_do_not_reuse_stale_values(dependency):
    equipment, role, levels = case("magic" if dependency in {"magic", "spell"} else "slash")
    with prepared_combat() as context:
        combat.evaluate_prepared_loadout(equipment, role, levels)
        if dependency in levels:
            levels = {**levels, dependency: levels[dependency] + 10}
        elif dependency == "prayers":
            role = SimpleNamespace(**{**vars(role), "active_prayer_ids": ("piety",)})
        elif dependency == "target":
            role = SimpleNamespace(**{**vars(role), "target": CombatTarget(defence_level=12)})
        elif dependency == "stance":
            role = SimpleNamespace(**{**vars(role), "stance": "defensive"})
        elif dependency == "spell":
            role = SimpleNamespace(**{**vars(role), "spell": "wind_strike"})
        elif dependency == "weapon":
            equipment = prepare_equipment([equipment.weapon.model_copy(update={"attack_speed": 6})])
        else:
            equipment = prepare_equipment(
                [
                    equipment.weapon.model_copy(
                        update={
                            "bonuses": equipment.weapon.bonuses.model_copy(
                                update={"melee_strength": 92}
                            ),
                        }
                    )
                ]
            )
        actual = combat.evaluate_prepared_loadout(equipment, role, levels)
        assert context.cache_info().currsize <= 2
    assert actual == combat.evaluate_prepared_loadout(equipment, role, levels)


def test_bounded_immutable_context_and_nested_cleanup():
    equipment, role, levels = case()
    assert not active()
    with prepared_combat(2) as context:
        for attack in range(80, 85):
            combat.evaluate_prepared_score(equipment, role, {**levels, "attack": attack})
        assert context.cache_info().currsize == 2
        with pytest.raises(RuntimeError, match="fixture"), prepared_combat():
            raise RuntimeError("fixture")
        assert active()
        record = context.last_prepared
        with pytest.raises((FrozenInstanceError, AttributeError)):
            record.attack_level = 0
    assert not active()
    with pytest.raises(ValueError, match="nonnegative"), prepared_combat(-1):
        pass


def test_unknown_defence_and_existing_ranged_contexts():
    equipment, role, levels = case("ranged", "rapid")
    levels = {"ranged": levels["ranged"]}
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    with ranged_experiment(4), ranged_score_finalization(), prepared_combat():
        assert combat.evaluate_prepared_loadout(equipment, role, levels) == expected
        score = combat.evaluate_prepared_score(equipment, role, levels, include_defence=True)
        assert dict(score.player_defence_rolls) == expected.player_defence_rolls.model_dump(
            exclude={"limitations"}
        )


def test_unsupported_equipment_is_checked_before_preparation():
    equipment, role, levels = case()
    equipment = prepare_equipment(
        [
            equipment.weapon.model_copy(
                update={
                    "unsupported_effects": ("fixture",),
                }
            )
        ]
    )
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    with prepared_combat() as context:
        assert combat.evaluate_prepared_loadout(equipment, role, levels) == expected
        assert context.cache_info().misses == 0


def test_constants_reused_across_equipment_without_reusing_bonuses():
    equipment, role, levels = case()
    stronger = prepare_equipment(
        [
            equipment.weapon,
            EquipmentDefinition(
                id=2, name="Strength", slot="head", bonuses=EquipmentBonuses(melee_strength=50)
            ),
        ]
    )
    expected = combat.evaluate_prepared_score(stronger, role, levels, include_defence=True)
    with prepared_combat() as context:
        weaker = combat.evaluate_prepared_score(equipment, role, levels, include_defence=True)
        actual = combat.evaluate_prepared_score(stronger, role, levels, include_defence=True)
        assert context.cache_info().hits == 1
        assert context.cache_info().misses == 1
    assert actual == expected
    assert actual.dps > weaker.dps


def test_zero_capacity_and_in_place_level_change():
    equipment, role, levels = case()
    with prepared_combat(0) as context:
        combat.evaluate_prepared_score(equipment, role, levels)
        combat.evaluate_prepared_score(equipment, role, levels)
        assert context.cache_info().currsize == context.cache_info().hits == 0
        assert context.cache_info().misses == 2
    with prepared_combat() as context:
        combat.evaluate_prepared_score(equipment, role, levels)
        levels["strength"] = 30
        actual = combat.evaluate_prepared_score(equipment, role, levels)
        assert context.cache_info().misses == 2
    assert actual == combat.evaluate_prepared_score(equipment, role, levels)


@pytest.mark.parametrize(
    "style,stance",
    [
        ("slash", "accurate"),
        ("ranged", "rapid"),
        ("magic", "accurate"),
    ],
)
def test_numeric_interval_matches_supported_report(style, stance):
    equipment, role, levels = case(style, stance)
    report = combat.evaluate_prepared_loadout(equipment, role, levels)
    assert report.supported
    assert combat.numeric_attack_interval(equipment.weapon, role) == report.attack_interval


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("fixed", [False, True])
@pytest.mark.parametrize("thorough", [False, True])
def test_complete_search_archives_match_unfactored(style, fixed, thorough):
    from tests.gear.test_fixed_reporting import fixed_inputs
    from tests.gear.test_prayer_search_efficiency import scenario
    from tools.benchmark_gear_desktop import without_observations
    from tracker.gear.optimizer import optimize

    args = fixed_inputs(style) if fixed else scenario(style)
    options = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
        "local_refinement": thorough,
    }
    expected = optimize(*args, **options)
    with prepared_combat():
        actual = optimize(*args, **options)
    assert without_observations(actual) == without_observations(expected)


def test_owned_frozen_levels_do_not_follow_original_mutations():
    from tracker.gear.optimizer import RoleConfig

    equipment, _, levels = case()
    role = RoleConfig(id="fixture", style="slash")
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    with prepared_combat() as context:
        frozen = freeze_levels(levels)
        assert dict(frozen) == levels
        assert combat.evaluate_prepared_loadout(equipment, role, frozen) == expected
        levels["strength"] = 1
        assert combat.evaluate_prepared_loadout(equipment, role, frozen) == expected
        assert context.cache_info().hits == 1
        with pytest.raises(TypeError):
            frozen["strength"] = 0
        changed = freeze_levels(levels)
        actual = combat.evaluate_prepared_loadout(equipment, role, changed)
    assert actual == combat.evaluate_prepared_loadout(equipment, role, levels)
    assert actual.dps != expected.dps


def test_frozen_role_lookup_respects_role_and_explicit_target_changes():
    from tracker.gear.optimizer import RoleConfig

    equipment, _, levels = case("magic")
    role = RoleConfig(id="fixture", style="magic", spell="fire_wave")
    changed = role.model_copy(update={"spell": "wind_strike", "active_prayer_ids": ("augury",)})
    target = CombatTarget(magic_level=200, weakness_element="fire", weakness_percent=50)
    expected = combat.evaluate_prepared_loadout(equipment, changed, levels, target)
    with prepared_combat() as context:
        frozen = freeze_levels(levels)
        combat.evaluate_prepared_loadout(equipment, role, frozen)
        combat.evaluate_prepared_loadout(equipment, role, frozen, target)
        actual = combat.evaluate_prepared_loadout(equipment, changed, frozen, target)
        assert context.cache_info().misses == 3
    assert actual == expected


def test_repeated_frozen_context_does_not_rebuild_identity_key(monkeypatch):
    from importlib import import_module

    from tracker.gear.optimizer import RoleConfig

    module = import_module("tracker.gear.prepared_combat")
    equipment, _, levels = case()
    role = RoleConfig(id="fixture", style="slash")
    with prepared_combat() as context:
        frozen = freeze_levels(levels)
        expected = combat.evaluate_prepared_score(equipment, role, frozen)
        monkeypatch.setattr(
            module,
            "id",
            lambda value: pytest.fail("repeated frozen context rebuilt its key"),
            raising=False,
        )
        assert combat.evaluate_prepared_score(equipment, role, frozen) == expected
        assert context.cache_info().hits == context.cache_info().misses == 1


def test_role_shortcut_respects_zero_capacity_and_fallback_eviction():
    from tracker.gear.optimizer import RoleConfig

    equipment, fallback_role, levels = case()
    role = RoleConfig(id="fixture", style="slash")
    with prepared_combat(0) as context:
        frozen = freeze_levels(levels)
        combat.evaluate_prepared_score(equipment, role, frozen)
        combat.evaluate_prepared_score(equipment, role, frozen)
        assert context.cache_info().hits == context.cache_info().currsize == 0
        assert context.cache_info().misses == 2
    with prepared_combat(1) as context:
        frozen = freeze_levels(levels)
        expected = combat.evaluate_prepared_score(equipment, role, frozen)
        # The mutable generic caller inserts into the same bounded cache.
        combat.evaluate_prepared_score(equipment, fallback_role, levels)
        assert combat.evaluate_prepared_score(equipment, role, frozen) == expected
        assert context.cache_info().misses == 3
        assert context.cache_info().hits == 0
        assert context.cache_info().currsize == 1


def test_prepared_constants_do_not_repeat_context_lookup(monkeypatch):
    from tracker.gear.optimizer import RoleConfig

    equipment, _, levels = case()
    role = RoleConfig(id="fixture", style="slash")
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    original = combat.prepared_combat_context
    calls = []

    def counted():
        calls.append(1)
        return original()

    with prepared_combat():
        frozen = freeze_levels(levels)
        monkeypatch.setattr(combat, "prepared_combat_context", counted)
        assert combat.evaluate_prepared_loadout(equipment, role, frozen) == expected
    assert len(calls) == 1


@pytest.mark.parametrize("include_defence", [False, True])
@pytest.mark.parametrize("finalize", [False, True])
def test_cached_ranged_score_does_not_prepare_unused_attack_context(
    monkeypatch, include_defence, finalize
):
    from contextlib import nullcontext

    from tracker.gear.optimizer import RoleConfig

    equipment, _, levels = case("ranged", "rapid")
    role = RoleConfig(id="fixture", style="ranged", stance="rapid")
    expected = combat.evaluate_prepared_score(
        equipment, role, levels, include_defence=include_defence
    )
    calls = []
    original_active = combat.ranged_experiment_active

    def checked_active():
        calls.append(1)
        return original_active()

    with (
        prepared_combat() as context,
        ranged_experiment(4),
        ranged_score_finalization() if finalize else nullcontext(),
    ):
        frozen = freeze_levels(levels)
        monkeypatch.setattr(
            context,
            "prepare_role",
            lambda *args: pytest.fail("prepared unused cached-ranged constants"),
        )
        monkeypatch.setattr(combat, "ranged_experiment_active", checked_active)
        assert (
            combat.evaluate_prepared_score(equipment, role, frozen, include_defence=include_defence)
            == expected
        )
    assert len(calls) == 1


def test_cached_ranged_full_report_still_reuses_prepared_defence():
    from tracker.gear.optimizer import RoleConfig

    equipment, _, levels = case("ranged", "rapid")
    role = RoleConfig(id="fixture", style="ranged", stance="rapid")
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    with prepared_combat() as context, ranged_experiment(4):
        frozen = freeze_levels(levels)
        assert combat.evaluate_prepared_loadout(equipment, role, frozen) == expected
        assert combat.evaluate_prepared_loadout(equipment, role, frozen) == expected
        assert context.cache_info().hits == context.cache_info().misses == 1


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("cached", [False, True])
def test_direct_calculator_retains_automatic_context_detection(style, cached):
    from contextlib import nullcontext

    equipment, role, levels = case(style)
    expected = combat.evaluate_prepared_loadout(equipment, role, levels)
    target = role.target
    with prepared_combat(), ranged_experiment(4) if cached else nullcontext():
        actual = combat._calculate(
            equipment.weapon,
            style,
            levels,
            target,
            role.stance,
            role.spell,
            equipment.bonuses,
            None,
        )
    assert actual == expected


def test_obsolete_frozen_roles_are_reclaimed_while_context_is_alive():
    import weakref

    from tracker.gear.optimizer import RoleConfig

    equipment, _, levels = case()
    with prepared_combat() as context:
        frozen = freeze_levels(levels)
        first = RoleConfig(id="first", style="slash")
        second = RoleConfig(id="second", style="slash", stance="aggressive")
        first_ref = weakref.ref(first)
        combat.evaluate_prepared_score(equipment, first, frozen)
        combat.evaluate_prepared_score(equipment, second, frozen)
        del first
        assert first_ref() is None
        assert context.cache_info().currsize == 1
        assert context.cache_info().misses == 2


def test_reused_role_identity_and_stale_callback_cannot_hit_or_delete_new_entry(monkeypatch):
    import builtins
    from importlib import import_module

    from tracker.gear.optimizer import RoleConfig

    module = import_module("tracker.gear.prepared_combat")
    equipment, _, levels = case()
    first = RoleConfig(id="first", style="slash", stance="accurate")
    second = RoleConfig(id="second", style="slash", stance="aggressive")
    expected = combat.evaluate_prepared_score(equipment, second, levels)
    monkeypatch.setattr(
        module,
        "id",
        lambda value: 7 if type(value) is RoleConfig else builtins.id(value),
        raising=False,
    )
    with prepared_combat() as context:
        frozen = freeze_levels(levels)
        combat.evaluate_prepared_score(equipment, first, frozen)
        old_ref = next(iter(context._entries.values())).role_ref
        assert combat.evaluate_prepared_score(equipment, second, frozen) == expected
        assert context.cache_info().misses == 2
        assert context.cache_info().hits == 0
        del first
        assert old_ref() is None
        assert context.cache_info().currsize == 1
        assert combat.evaluate_prepared_score(equipment, second, frozen) == expected
        assert context.cache_info().hits == 1


def test_only_one_mru_role_owner_and_no_context_reference_cycle():
    import weakref

    from tracker.gear.optimizer import RoleConfig

    equipment, _, levels = case()
    role_refs = []
    with prepared_combat() as context:
        context_ref = weakref.ref(context)
        frozen = freeze_levels(levels)
        for index in range(10):
            role = RoleConfig(id=f"role{index}", style="slash")
            role_refs.append(weakref.ref(role))
            combat.evaluate_prepared_score(equipment, role, frozen)
        del role
        assert sum(ref() is not None for ref in role_refs) == 1
        assert context.cache_info().currsize == 1
    del context
    # Immediate refcount destruction proves callbacks do not capture the context.
    assert context_ref() is None
    assert all(ref() is None for ref in role_refs)
