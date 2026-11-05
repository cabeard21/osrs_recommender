from types import SimpleNamespace

import pytest

from tracker.gear.combat import evaluate_prepared_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.scoring import prepare_equipment


@pytest.mark.parametrize(
    "style,stance,prayers",
    [
        ("slash", "controlled", ("piety",)),
        ("ranged", "rapid", ("rigour",)),
        ("magic", "accurate", ("augury",)),
    ],
)
@pytest.mark.parametrize("armour", [-4, 0, 6])
@pytest.mark.parametrize("pattern", ["single", "independent_double", "conditional_double"])
def test_score_matches_full(style, stance, prayers, armour, pattern):
    weapon = EquipmentDefinition(
        id=1,
        name="Fixture",
        slot="weapon",
        attack_styles=("slash", "ranged"),
        attack_pattern=pattern,
        bonuses=EquipmentBonuses(
            slash=45,
            ranged=30,
            magic=12,
            melee_strength=66,
            ranged_strength=38,
            magic_damage=15.5,
            defence_magic=30,
        ),
    )
    prepared = prepare_equipment([weapon])
    role = SimpleNamespace(
        style=style,
        stance=stance,
        spell="fire_wave",
        active_prayer_ids=prayers,
        target=CombatTarget(
            defence_level=125,
            magic_level=150,
            flat_armour=armour,
            weakness_element="fire",
            weakness_percent=35,
        ),
    )
    levels = {"attack": 91, "strength": 87, "ranged": 85, "magic": 90, "defence": 78}
    full = evaluate_prepared_loadout(prepared, role, levels)
    score = evaluate_prepared_score(prepared, role, levels, include_defence=True)
    assert score.supported == full.supported
    assert score.dps == full.dps
    assert score.accuracy == full.accuracy
    assert score.bonuses == full.bonuses
    assert dict(score.player_defence_rolls) == full.player_defence_rolls.model_dump(
        exclude={"limitations"}
    )
    assert evaluate_prepared_score(prepared, role, levels).player_defence_rolls is None
    with pytest.raises(AttributeError):
        score.dps = 0
    with pytest.raises(TypeError):
        score.player_defence_rolls["magic"] = 0


@pytest.mark.parametrize(
    "target,style,levels",
    [
        (CombatTarget(damage_cap=1), "crush", {"attack": 99, "strength": 99}),
        (
            CombatTarget(unsupported_mechanics=("unsupported",)),
            "crush",
            {"attack": 99, "strength": 99},
        ),
        (CombatTarget(), "slash", {"attack": 99, "strength": 99}),
        (CombatTarget(), "magic", {}),
        (CombatTarget(), "special", {}),
    ],
)
def test_unsupported_score_matches_full(target, style, levels):
    role = SimpleNamespace(style=style, stance="accurate", spell="fire_strike", target=target)
    prepared = prepare_equipment([])
    full = evaluate_prepared_loadout(prepared, role, levels)
    score = evaluate_prepared_score(prepared, role, levels, include_defence=True)
    assert not full.supported
    assert not score.supported
    assert score.dps is None
    assert score.accuracy is None
    assert score.bonuses == full.bonuses
    assert score.player_defence_rolls is None


def test_score_never_builds_reporting_models(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("reporting model constructed")

    prepared = prepare_equipment([])
    role = SimpleNamespace(style="magic", stance="accurate", spell="fire_strike")
    for name in (
        "CombatPerformance",
        "HitsplatPerformance",
        "ElementalWeakness",
        "player_defence_rolls",
    ):
        monkeypatch.setattr("tracker.gear.combat." + name, fail)
    assert evaluate_prepared_score(
        prepared, role, {"magic": 99, "defence": 99}, include_defence=True
    ).supported


@pytest.mark.parametrize("boosted", [False, True])
def test_powered_score_matches_full(boosted):
    prepared = prepare_equipment(
        [
            EquipmentDefinition(
                id=1,
                name="Powered",
                slot="weapon",
                powered_attack="fixture",
                powered_attack_base_max_hit=28,
                powered_attack_stances=("accurate",),
            )
        ]
    )
    role = SimpleNamespace(
        style="magic",
        stance="accurate",
        powered_attack="fixture",
        active_prayer_ids=("augury",),
        target=CombatTarget(weakness_element="fire", weakness_percent=40),
    )
    levels = {"magic": 99, "defence": 75, "_base_magic": 90 if boosted else 99}
    score = evaluate_prepared_score(prepared, role, levels, include_defence=True)
    full = evaluate_prepared_loadout(prepared, role, levels)
    assert score.supported == full.supported
    assert score.dps == full.dps
    assert score.accuracy == full.accuracy


@pytest.mark.parametrize(
    "levels", [{"magic": 99}, {"magic": 99, "defence": 75}, {"magic": 1, "defence": 1}]
)
def test_score_unknown_defensive_levels_match_full(levels):
    role = SimpleNamespace(style="magic", stance="defensive", spell="wind_strike")
    prepared = prepare_equipment([])
    score = evaluate_prepared_score(prepared, role, levels, include_defence=True)
    full = evaluate_prepared_loadout(prepared, role, levels)
    assert dict(score.player_defence_rolls) == full.player_defence_rolls.model_dump(
        exclude={"limitations"}
    )
