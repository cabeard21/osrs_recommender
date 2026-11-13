from itertools import product

import pytest

from tracker.gear.bolts import _mean, expected_bolt_damage
from tracker.gear.hopper import active, expected_secondary_damage
from tracker.gear.models import EquipmentDefinition


@pytest.mark.parametrize(
    "maximum,armour,bonus,divisor", tuple(product(range(12), [-5, 0, 1, 4], [0, 1, 9], [1, 3]))
)
def test_analytic_divided_mean_against_independent_outcomes(maximum, armour, bonus, divisor):
    expected = sum(
        max(0, max(1, roll + bonus) // divisor - armour) for roll in range(maximum + 1)
    ) / (maximum + 1)
    assert _mean(maximum, armour, bonus, divisor) == pytest.approx(expected)


@pytest.mark.parametrize(
    "family,diary,zaryte,armour,accuracy",
    tuple(
        product(
            ["opal", "pearl", "ruby", "diamond", "dragonstone", "onyx"],
            [False, True],
            [False, True],
            [-5, 0, 4],
            [0, 0.4, 1],
        )
    ),
)
def test_secondary_bolts_against_enumerated_outcomes(family, diary, zaryte, armour, accuracy):
    ranged, maximum, hp, primary_activation = 90, 20, 500, 0.13
    chance = {
        "opal": 0.05,
        "pearl": 0.06,
        "ruby": 0.06,
        "diamond": 0.1,
        "dragonstone": 0.06,
        "onyx": 0.11,
    }[family]
    chance *= (1.1 if diary else 1) / 3 * (1 - primary_activation)
    ordinary = sum(max(0, max(1, x) // 3 - armour) for x in range(maximum + 1)) / (maximum + 1)
    base = accuracy * ordinary
    if family == "ruby":
        proc = max(0, min(110 if zaryte else 100, hp * (22 if zaryte else 20) // 100) // 3 - armour)
        expected = (1 - chance) * base + chance * proc
    elif family in {"diamond", "onyx"}:
        mult = (126 if zaryte else 115) if family == "diamond" else (132 if zaryte else 120)
        limit = maximum * mult // 100
        proc = sum(max(0, max(1, x) // 3 - armour) for x in range(limit + 1)) / (limit + 1)
        expected = (
            (1 - chance) * base + chance * proc
            if family == "diamond"
            else accuracy * ((1 - chance) * ordinary + chance * proc)
        )
    else:
        bonus = (
            ranged // (9 if zaryte else 10)
            if family == "opal"
            else (
                ranged // (18 if zaryte else 20)
                if family == "pearl"
                else ranged * 2 // (9 if zaryte else 10)
            )
        )
        proc = sum(max(0, max(1, x + bonus) // 3 - armour) for x in range(maximum + 1)) / (
            maximum + 1
        )
        expected = accuracy * ((1 - chance) * ordinary + chance * proc)
        if family != "dragonstone":
            expected += chance * (1 - accuracy) * (bonus // 3)
    result = expected_secondary_damage(
        family, ranged, maximum, accuracy, hp, diary, zaryte, (), armour, primary_activation
    )
    assert result[0] == pytest.approx(expected)
    assert result[2] == pytest.approx(
        chance * (accuracy if family in {"onyx", "dragonstone"} else 1)
    )


@pytest.mark.parametrize(
    "family,traits",
    [("onyx", ("undead",)), ("dragonstone", ("dragon",)), ("dragonstone", ("fiery",))],
)
def test_secondary_immunity_and_primary_proc_leave_ordinary_shot(family, traits):
    ordinary = expected_secondary_damage(None, 99, 40, 0.4, 500, False, False, traits)
    assert expected_secondary_damage(family, 99, 40, 0.4, 500, True, True, traits) == ordinary
    assert (
        expected_secondary_damage("ruby", 99, 40, 0.4, 500, True, True, (), primary_activation=1)
        == ordinary
    )


def test_secondary_missing_hp_and_zero_rounding():
    with pytest.raises(ValueError, match="hitpoints"):
        expected_secondary_damage("ruby", 99, 40, 0.4, None, False, False, ())
    assert expected_secondary_damage(None, 99, 2, 1, None, False, False, ()) == (0, 0, 0)


def test_fiery_pearl_and_divided_zero_bonus():
    assert (
        expected_secondary_damage("pearl", 90, 20, 0.4, None, True, True, ("fiery",))[0]
        > expected_secondary_damage("pearl", 90, 20, 0.4, None, True, True, ())[0]
    )
    assert expected_bolt_damage("opal", 1, 2, 1, None, False, False, (), damage_divisor=3)[0] == 0


def test_active_requires_reviewed_crossbow_shield_and_legal_ammo():
    weapon = EquipmentDefinition(
        id=9185, name="Rune crossbow", slot="weapon", ammo_for=("bolt:9144",)
    )
    shield = EquipmentDefinition(id=32879, name="Aquanite hopper", slot="shield")
    ammo = EquipmentDefinition(
        id=9144, name="Runite bolts", slot="ammunition", ammo_type="bolt:9144"
    )
    assert active(weapon, shield, ammo)
    assert not active(None, shield, ammo)
    assert not active(weapon, None, ammo)
    assert not active(weapon, shield, None)
    assert not active(weapon.model_copy(update={"id": 10156}), shield, ammo)
    assert not active(weapon, shield.model_copy(update={"id": 1}), ammo)
    assert not active(weapon, shield, ammo.model_copy(update={"ammo_type": "arrow:1"}))
