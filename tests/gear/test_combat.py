import pytest
from pydantic import ValidationError

from tracker.gear.combat import accuracy_probability, evaluate_loadout
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition


@pytest.mark.parametrize("element", ["air", "water", "earth", "fire"])
def test_weakness_explanation_matches_actual_rolls(element):
    spell = ("wind" if element == "air" else element) + "_bolt"
    baseline = evaluate_loadout([], "magic", {"magic": 35}, spell=spell)
    result = evaluate_loadout(
        [],
        "magic",
        {"magic": 35},
        CombatTarget(weakness_element=element, weakness_percent=35),
        spell=spell,
    )
    explanation = result.elemental_weakness
    assert explanation.applied
    assert explanation.element == element
    assert explanation.percent == 35
    assert explanation.reason is None
    assert explanation.max_hit_bonus == result.max_hit - baseline.max_hit
    assert explanation.attack_roll_bonus == result.attack_roll - baseline.attack_roll


def test_weakness_explanation_nonmatching_and_unsupported():
    target = CombatTarget(weakness_element="water", weakness_percent=50)
    result = evaluate_loadout([], "magic", {"magic": 35}, target, spell="fire_bolt")
    assert not result.elemental_weakness.applied
    assert result.elemental_weakness.reason
    assert result.elemental_weakness.max_hit_bonus == 0
    assert evaluate_loadout([], "magic", {}, target).elemental_weakness is None


@pytest.mark.parametrize("element,percent", [(None, 0), ("fire", 0)])
def test_no_active_weakness_explanation(element, percent):
    result = evaluate_loadout(
        [],
        "magic",
        {"magic": 35},
        CombatTarget(weakness_element=element, weakness_percent=percent),
        spell="fire_bolt",
    )
    assert not result.elemental_weakness.applied
    assert result.elemental_weakness.max_hit_bonus == 0
    assert result.elemental_weakness.attack_roll_bonus == 0
    assert result.elemental_weakness.reason == "Target has no active elemental weakness."


def test_accuracy_both_roll_branches():
    assert accuracy_probability(100, 50) == pytest.approx(1 - 52 / 202)
    assert accuracy_probability(50, 100) == pytest.approx(50 / 202)


def test_independently_calculated_melee_hit_distribution():
    # Accurate: effective attack 61, strength 58; +64 strength => max hit 12.
    weapon = EquipmentDefinition(
        id=1,
        name="Fixture",
        slot="weapon",
        bonuses=EquipmentBonuses(stab=10, melee_strength=64),
        attack_styles=("stab",),
    )
    result = evaluate_loadout([weapon], "stab", {"attack": 50, "strength": 50})
    attack_roll = 61 * 74
    defence_roll = 10 * 64
    accuracy = 1 - (defence_roll + 2) / (2 * (attack_roll + 1))
    assert result.supported
    assert result.max_hit == 12
    assert result.accuracy == pytest.approx(accuracy)
    # Accurate zero becomes 1, so E[damage|hit]=(sum(1..12)+1)/13.
    assert result.dps == pytest.approx(accuracy * 79 / 13 / 2.4)


def test_unsupported_effect_and_illegal_attack_are_not_scored():
    weapon = EquipmentDefinition(
        id=2,
        name="Unsupported",
        slot="weapon",
        attack_styles=("slash",),
        unsupported_effects=("complex passive",),
    )
    result = evaluate_loadout([weapon], "stab", {"attack": 99, "strength": 99})
    assert not result.supported
    assert result.dps is None
    assert result.limitations


def test_missing_ammunition_blocks_ranged():
    bow = EquipmentDefinition(
        id=3,
        name="Bow",
        slot="weapon",
        attack_styles=("ranged",),
        ammo_for=("arrow",),
        two_handed=True,
    )
    assert not evaluate_loadout([bow], "ranged", {"ranged": 50}).supported


def test_standard_spell_level_gate_and_damage():
    assert not evaluate_loadout([], "magic", {"magic": 1}, spell="fire_strike").supported
    result = evaluate_loadout([], "magic", {"magic": 13}, spell="fire_strike")
    assert result.supported
    assert result.max_hit == 8
    assert result.attack_interval == 3.0


def test_spell_tier_scales_to_highest_unlocked_and_casting_accuracy():
    result = evaluate_loadout([], "magic", {"magic": 13}, spell="wind_strike")
    assert result.max_hit == 8
    assert result.attack_roll == 24 * 64


def test_legal_rapid_bow_attack_and_target_defence_subtype():
    bow = EquipmentDefinition(
        id=841,
        name="Shortbow",
        slot="weapon",
        bonuses=EquipmentBonuses(ranged=8),
        attack_styles=("ranged",),
        ammo_for=("arrow:884",),
        attack_speed=4,
    )
    arrow = EquipmentDefinition(
        id=884,
        name="Iron arrow",
        slot="ammunition",
        bonuses=EquipmentBonuses(ranged_strength=10),
        ammo_type="arrow:884",
    )
    target = CombatTarget(defence_level=50, ranged_standard=100)
    result = evaluate_loadout([bow, arrow], "ranged", {"ranged": 50}, target, stance="rapid")
    assert result.max_hit == 7
    assert result.attack_interval == pytest.approx(1.8)
    assert result.attack_roll == 58 * 72
    assert result.defence_roll == 59 * 164


def test_invalid_stance_duplicate_slots_and_two_handed_block():
    weapon = EquipmentDefinition(
        id=1,
        name="Weapon",
        slot="weapon",
        two_handed=True,
        attack_styles=("stab",),
        attack_profiles=(("stab", "controlled"),),
    )
    shield = EquipmentDefinition(id=2, name="Shield", slot="shield")
    result = evaluate_loadout(
        [weapon, shield, shield], "stab", {"attack": 50, "strength": 50}, stance="rapid"
    )
    assert not result.supported
    assert len(result.limitations) >= 4


def test_unknown_levels_and_target_mechanics_fail_closed():
    result = evaluate_loadout(
        [],
        "magic",
        {},
        CombatTarget(unsupported_mechanics=("Unmodeled damage cap",)),
        stance="aggressive",
    )
    assert not result.supported
    assert "Unmodeled damage cap" in result.limitations


def test_unarmed_crush_and_unsupported_special_role():
    assert evaluate_loadout([], "crush", {"attack": 1, "strength": 1}).supported
    assert not evaluate_loadout([], "special", {}).supported


def test_elemental_weakness_adds_base_spell_damage_after_gear_rounding():
    # Fire bolt at35 Magic: base12. +25% gear =>15; +50% weakness
    # adds6 from base, not7 from gear-enhanced max. Accuracybase44*64.
    amulet = EquipmentDefinition(
        id=1, name="Fixture", slot="neck", bonuses=EquipmentBonuses(magic_damage=25)
    )
    result = evaluate_loadout(
        [amulet],
        "magic",
        {"magic": 35},
        CombatTarget(weakness_element="fire", weakness_percent=50),
        spell="fire_bolt",
    )
    assert result.max_hit == 21
    assert result.attack_roll == (35 + 11) * 64 * 3 // 2
    wrong_element = evaluate_loadout(
        [amulet],
        "magic",
        {"magic": 35},
        CombatTarget(weakness_element="earth", weakness_percent=50),
        spell="fire_bolt",
    )
    assert wrong_element.max_hit == 15


def test_wind_spells_match_air_weakness_and_fractional_bonus_truncates():
    result = evaluate_loadout(
        [],
        "magic",
        {"magic": 13},
        CombatTarget(weakness_element="air", weakness_percent=35),
        spell="wind_strike",
    )
    assert result.max_hit == 10  # 8 + floor(8*.35)
    assert result.attack_roll == 1536 + 537


def test_target_cap_supported_below_threshold_but_not_approximated_above():
    target = CombatTarget(damage_cap=50, weakness_element="fire", weakness_percent=50)
    assert evaluate_loadout([], "magic", {"magic": 99}, target, spell="fire_surge").supported
    item = EquipmentDefinition(
        id=1, name="Fixture", slot="neck", bonuses=EquipmentBonuses(magic_damage=100)
    )
    result = evaluate_loadout([item], "magic", {"magic": 99}, target, spell="fire_surge")
    assert not result.supported
    assert result.dps is None
    assert any("cap" in message for message in result.limitations)


def test_target_rejects_equipment_defence_field_names():
    with pytest.raises(ValidationError):
        CombatTarget.model_validate({"bonuses": {"defence_magic": 100}})


def test_zero_maximum_accurate_roll_is_raised_to_one():
    weapon = EquipmentDefinition(
        id=1,
        name="Weak fixture",
        slot="weapon",
        attack_styles=("crush",),
        bonuses=EquipmentBonuses(melee_strength=-64),
    )
    result = evaluate_loadout([weapon], "crush", {"attack": 1, "strength": 1})
    assert result.max_hit == 1  # The reported maximum is post-transform damage.
    assert result.dps == pytest.approx(result.accuracy / 2.4)


def test_equipped_arrows_do_not_strengthen_thrown_weapon():
    dart = EquipmentDefinition(
        id=1,
        name="Dart fixture",
        slot="weapon",
        attack_styles=("ranged",),
        bonuses=EquipmentBonuses(ranged_strength=10),
    )
    arrow = EquipmentDefinition(
        id=2,
        name="Arrow fixture",
        slot="ammunition",
        ammo_type="arrow:2",
        bonuses=EquipmentBonuses(ranged_strength=50, ranged=20, prayer=1),
    )
    without = evaluate_loadout([dart], "ranged", {"ranged": 50})
    with_arrow = evaluate_loadout([dart, arrow], "ranged", {"ranged": 50})
    assert with_arrow.max_hit == without.max_hit
    assert with_arrow.attack_roll == without.attack_roll
    assert with_arrow.bonuses.prayer == 1


def test_all_melee_stances_apply_their_distinct_effective_level_modifiers():
    from types import SimpleNamespace

    blade = EquipmentDefinition(
        id=80,
        name="Stance blade",
        slot="weapon",
        attack_styles=("stab",),
        attack_profiles=tuple(
            ("stab", stance) for stance in ("accurate", "aggressive", "defensive", "controlled")
        ),
        bonuses=EquipmentBonuses(stab=20, melee_strength=64),
    )
    results = {
        stance: evaluate_loadout(
            [blade], SimpleNamespace(style="stab", stance=stance), {"attack": 50, "strength": 50}
        )
        for stance in ("accurate", "aggressive", "defensive", "controlled")
    }
    assert results["accurate"].attack_roll == 61 * 84
    assert results["aggressive"].attack_roll == results["defensive"].attack_roll == 58 * 84
    assert results["controlled"].attack_roll == 59 * 84
    assert results["aggressive"].max_hit >= results["controlled"].max_hit
    assert results["controlled"].max_hit >= results["accurate"].max_hit


def test_ranged_accurate_and_longrange_keep_weapon_interval_but_rapid_reduces_it():
    from types import SimpleNamespace

    dart = EquipmentDefinition(
        id=81,
        name="Stance dart",
        slot="weapon",
        attack_styles=("ranged",),
        attack_profiles=(("ranged", "accurate"), ("ranged", "rapid"), ("ranged", "longrange")),
        attack_speed=4,
        bonuses=EquipmentBonuses(ranged=20, ranged_strength=64),
    )
    result = {
        stance: evaluate_loadout(
            [dart], SimpleNamespace(style="ranged", stance=stance), {"ranged": 50}
        )
        for stance in ("accurate", "rapid", "longrange")
    }
    assert result["accurate"].attack_roll == 61 * 84
    assert result["longrange"].attack_roll == result["rapid"].attack_roll == 58 * 84
    assert result["accurate"].attack_interval == result["longrange"].attack_interval == 2.4
    assert result["rapid"].attack_interval == pytest.approx(1.8)


def test_powered_staff_uses_authored_hit_speed_and_stances():
    from types import SimpleNamespace

    staff = EquipmentDefinition(
        id=82,
        name="Authored powered fixture",
        slot="weapon",
        attack_speed=4,
        powered_attack="fixture_bolt",
        powered_attack_base_max_hit=18,
        powered_attack_stances=("accurate", "longrange"),
        bonuses=EquipmentBonuses(magic=20),
    )
    selected = SimpleNamespace(
        style="magic", stance="longrange", spell="fire_strike", powered_attack="fixture_bolt"
    )
    result = evaluate_loadout([staff], selected, {"magic": 50})
    assert result.supported
    assert result.max_hit == 18
    assert result.attack_interval == 2.4
    assert not evaluate_loadout(
        [staff],
        SimpleNamespace(
            style="magic", stance="defensive", spell="fire_strike", powered_attack="fixture_bolt"
        ),
        {"magic": 50},
    ).supported
