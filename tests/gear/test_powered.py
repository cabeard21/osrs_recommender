from types import SimpleNamespace

import pytest

from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.powered import STAFFS, base_hit, review, supports_powered
from tracker.gear.scoring import prepare_equipment


def test_warped_physical_identity_matches_runelite_gameval():
    # RuneLite ItemID.WARPED_SCEPTRE_UNCHARGED and WARPED_SCEPTRE.
    from tracker.gear.powered import MARKET_FORMS

    entry = review(28583)
    assert entry.uncharged_id == 28583
    assert entry.charged_id == 28585
    assert review(28585) == entry
    assert 28583 in MARKET_FORMS
    assert 28585 not in MARKET_FORMS


@pytest.mark.parametrize(
    "model,magic,hit",
    [
        ("warped", 62, 16),
        ("seas", 75, 20),
        ("swamp", 78, 24),
        ("sanguinesti", 99, 33),
        ("shadow", 99, 34),
        ("ayak", 83, 21),
        ("thammaron", 60, 12),
        ("accursed", 70, 17),
        ("bone", 50, 21),
    ],
)
def test_reviewed_formulas(model, magic, hit):
    assert base_hit(model, magic) == hit


def staff(model, **bonuses):
    entry = next(s for s in STAFFS if s.model == model)
    return EquipmentDefinition(
        id=entry.charged_id,
        name=entry.name,
        slot="weapon",
        attack_speed=entry.speed,
        powered_attack=model,
        powered_attack_model=model,
        powered_attack_stances=("accurate", "longrange"),
        bonuses=EquipmentBonuses(**bonuses),
    )


def score(item, magic=99, target=None):
    role = SimpleNamespace(
        style="magic", stance="accurate", spell="fire_strike", powered_attack=item.powered_attack
    )
    return evaluate_loadout([item], role, {"magic": magic, "_base_magic": 75}, target=target)


def test_models_support_boosts_and_shadow_keeps_raw_bonuses():
    item = staff("shadow", magic=20, magic_damage=40)
    result = score(item)
    assert result.supported
    assert result.max_hit == 68
    assert result.attack_roll == 110 * 124
    assert result.bonuses.magic == 20
    assert result.attack_interval == 3


def test_bone_requires_rat_trait():
    item = staff("bone")
    assert not score(item).supported
    assert score(item, target=CombatTarget(traits=("rat",))).supported


def test_sanguinesti_proc_mean_and_maximum():
    result = score(staff("sanguinesti"))
    assert result.supported
    assert result.max_hit == 41
    assert result.dps == pytest.approx(result.accuracy * ((33 / 2 + 1 / 34) + 1.6) / 2.4)
    assert not score(staff("sanguinesti"), target=CombatTarget(damage_cap=40)).supported


def test_registry_exact_forms_and_formula_validation():
    assert review(11905) == review(11907)
    assert review(33323) == review(33322)
    assert review(33322).uncharged_id == 33434
    assert review(31115).charged_id == 31113
    assert review(22516) is None
    assert review(27679) is None
    assert supports_powered(staff("warped"))
    with pytest.raises(ValueError):
        base_hit("unreviewed", 99)


@pytest.mark.parametrize("entry", STAFFS)
@pytest.mark.parametrize("magic", [1, 50, 75, 99, 112, 125])
def test_detailed_and_fast_score_match_for_every_edition(entry, magic):
    item = staff(entry.model, magic=25, magic_damage=12).model_copy(
        update={"id": entry.charged_id, "name": entry.name, "attack_speed": entry.speed}
    )
    role = SimpleNamespace(
        style="magic",
        stance="longrange",
        spell="fire_strike",
        powered_attack=item.powered_attack,
        active_prayer_ids=("augury",),
        target=CombatTarget(traits=("rat",)),
    )
    levels = {"magic": magic, "_base_magic": 75}
    detailed = evaluate_loadout([item], role, levels)
    fast = evaluate_prepared_score(prepare_equipment([item]), role, levels, include_defence=True)
    assert detailed.supported == fast.supported
    assert detailed.dps == fast.dps
    assert detailed.accuracy == fast.accuracy
    assert detailed.max_hit >= 1


def test_shadow_prayer_is_not_tripled():
    item = staff("shadow", magic=20, magic_damage=10)
    role = SimpleNamespace(
        style="magic",
        stance="accurate",
        spell="fire_strike",
        powered_attack="shadow",
        active_prayer_ids=("augury",),
    )
    result = evaluate_loadout([item], role, {"magic": 99})
    assert result.max_hit == 45  # floor(34 * (1 + .30 + .04))


@pytest.mark.parametrize("model", sorted({s.model for s in STAFFS}))
def test_drained_minimum_and_growth(model):
    assert base_hit(model, 0) == (11 if model == "bone" else 2 if model == "warped" else 1)
    assert base_hit(model, 125) >= base_hit(model, 99) >= base_hit(model, 50)
