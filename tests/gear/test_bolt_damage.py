import pytest

from tracker.gear.bolts import expected_bolt_damage


def test_ruby_replaces_normal_damage():
    result = expected_bolt_damage("ruby", 99, 40, 0.5, 1000, False, False, ())
    assert result[0] == pytest.approx(0.94 * (20 + 1 / 41) * 0.5 + 6)
    assert result[1] == 100


def test_diamond_bypasses_accuracy():
    assert expected_bolt_damage("diamond", 99, 40, 0, None, False, False, ())[0] > 0


def test_replacement_roll_independent_arithmetic():
    ordinary = 20 + 1 / 41
    diamond = 0.9 * 0.5 * ordinary + 0.1 * (23 + 1 / 47)
    onyx = 0.5 * (0.89 * ordinary + 0.11 * (24 + 1 / 49))
    assert expected_bolt_damage("diamond", 99, 40, 0.5, None, False, False, ())[0] == pytest.approx(
        diamond
    )
    assert expected_bolt_damage("onyx", 99, 40, 0.5, None, False, False, ())[0] == pytest.approx(
        onyx
    )
    assert expected_bolt_damage("ruby", 99, 40, 1, 10, False, False, ())[0] < ordinary


@pytest.mark.parametrize("family,traits", [("onyx", ("undead",)), ("dragonstone", ("dragon",))])
def test_immunity_uses_ordinary_damage(family, traits):
    assert expected_bolt_damage(family, 99, 40, 0.5, None, False, False, traits)[
        0
    ] == pytest.approx(0.5 * (20 + 1 / 41))


@pytest.mark.parametrize("family", ["opal", "pearl", "ruby", "diamond", "dragonstone", "onyx"])
@pytest.mark.parametrize("zaryte", [False, True])
@pytest.mark.parametrize("diary", [False, True])
def test_full_score_parity(family, zaryte, diary):
    from types import SimpleNamespace

    from tracker.gear.combat import evaluate_prepared_loadout, evaluate_prepared_score
    from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
    from tracker.gear.scoring import prepare_equipment

    weapon = EquipmentDefinition(
        id=26374 if zaryte else 9185,
        name="Crossbow",
        slot="weapon",
        attack_styles=("ranged",),
        ammo_for=("bolt:test",),
    )
    ammo = EquipmentDefinition(
        id=9236,
        name="Bolt",
        slot="ammunition",
        ammo_type="bolt:test",
        bolt_effect=family,
        bonuses=EquipmentBonuses(ranged_strength=100),
    )
    prepared = prepare_equipment([weapon, ammo])
    role = SimpleNamespace(
        style="ranged",
        stance="rapid",
        target=CombatTarget(hitpoints=500),
        bolt_diary_boost=diary,
        bolt_diary_known=True,
    )
    full = evaluate_prepared_loadout(prepared, role, {"ranged": 99})
    score = evaluate_prepared_score(prepared, role, {"ranged": 99})
    assert full.supported
    assert full.dps == score.dps
    assert full.bolt_effect.expected_damage_per_attack == full.dps * full.attack_interval


def test_pearl_fiery_bonus_and_zero_bonus():
    assert (
        expected_bolt_damage("pearl", 90, 20, 0.5, None, True, True, ("fiery",))[0]
        > expected_bolt_damage("pearl", 90, 20, 0.5, None, True, True, ())[0]
    )
    assert expected_bolt_damage("opal", 1, 20, 0.5, None, False, False, ())[0] == pytest.approx(
        0.5 * (10 + 1 / 21)
    )


def test_missing_hp():
    with pytest.raises(ValueError, match="hitpoints"):
        expected_bolt_damage("ruby", 99, 40, 0.5, None, False, False, ())


@pytest.mark.parametrize("armour", [-5, 0, 4, 100])
@pytest.mark.parametrize(
    "family,bonus,chance", [("opal", 9, 0.05), ("pearl", 4, 0.06), ("dragonstone", 18, 0.06)]
)
def test_additive_damage_against_independent_outcomes(armour, family, bonus, chance):
    accuracy, maximum = 0.4, 20
    ordinary = sum(max(0, max(1, x) - armour) for x in range(maximum + 1)) / (maximum + 1)
    proc = sum(max(0, max(1, x + bonus) - armour) for x in range(maximum + 1)) / (maximum + 1)
    expected = accuracy * ((1 - chance) * ordinary + chance * proc)
    if family != "dragonstone":
        expected += (1 - accuracy) * chance * bonus
    assert expected_bolt_damage(family, 90, maximum, accuracy, None, False, False, (), armour)[
        0
    ] == pytest.approx(expected)
