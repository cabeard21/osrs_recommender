from types import SimpleNamespace

import pytest

from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget
from tracker.gear.scoring import prepare_equipment
from tracker.gear.tomes import applied_tome, apply_review


@pytest.mark.parametrize("item_id", [20714, 20716, 25574, 25576, 30064, 30066])
def test_tome_forms_reviewed(make_content, item_id):
    item = load_catalog(make_content()).items[item_id]
    assert not item.unsupported_effects
    assert item.requirements_complete
    assert item.requires.to_yaml() == {"skill": {"magic": 50}}
    assert item.bonuses.magic == item.bonuses.defence_magic == 8
    assert item.bonuses.magic_damage == 0
    assert item.tradeable == (item_id in {20716, 25576, 30066})
    assert bool(item.tome_effect) == (item_id in {20714, 25574, 30064})


@pytest.mark.parametrize("item_id,element", [(20714, "fire"), (25574, "water"), (30064, "earth")])
def test_matching_tome_damage_and_score_parity(make_content, item_id, element):
    tome = load_catalog(make_content()).items[item_id]
    role = SimpleNamespace(style="magic", spell=f"{element}_surge", stance="accurate")
    result = evaluate_loadout([tome], role, {"magic": 99})
    assert result.supported
    assert result.max_hit == 26
    assert result.tome_bonus.damage_percent == 10
    assert result.tome_bonus.accuracy_percent == (20 if element == "water" else 0)
    assert evaluate_prepared_score(prepare_equipment([tome]), role, {"magic": 99}).dps == result.dps


@pytest.mark.parametrize("spell", ["wind_surge", "water_surge", "iban_blast", "ice_barrage"])
def test_fire_nonmatching_and_empty_have_no_effect(make_content, spell):
    catalog = load_catalog(make_content())
    for item_id in (20714, 20716):
        weapon = catalog.items[
            1409 if spell == "iban_blast" else 4675 if spell == "ice_barrage" else 1387
        ]
        result = evaluate_loadout(
            [weapon, catalog.items[item_id]], "magic", {"magic": 99}, spell=spell
        )
        assert result.supported
        assert result.tome_bonus is None


def test_searing_minimum_and_weakness_order(make_content):
    tome = load_catalog(make_content()).items[20714]
    role = SimpleNamespace(
        style="magic", spell="fire_surge", stance="accurate", fire_tome_pages="searing"
    )
    result = evaluate_loadout(
        [tome], role, {"magic": 99}, CombatTarget(weakness_element="fire", weakness_percent=50)
    )
    assert result.max_hit == 39  # floor((24 + 12) * 1.1)
    assert result.tome_bonus.minimum_hit == 3
    assert result.dps == pytest.approx(result.accuracy * 21 / 3)
    score = evaluate_prepared_score(prepare_equipment([tome]), role, {"magic": 99})
    plain = evaluate_loadout([tome], role, {"magic": 99})
    assert plain.tome_bonus.minimum_hit == 2
    assert score.dps == plain.dps


def test_water_accuracy_does_not_multiply_weakness(make_content):
    tome = load_catalog(make_content()).items[25574]
    result = evaluate_loadout(
        [tome],
        "magic",
        {"magic": 99},
        CombatTarget(weakness_element="water", weakness_percent=50),
        spell="water_surge",
    )
    base = 110 * 72
    assert result.attack_roll == base * 120 // 100 + base // 2
    assert result.max_hit == 39


def test_tome_cap_uses_boosted_maximum(make_content):
    tome = load_catalog(make_content()).items[20714]
    assert not evaluate_loadout(
        [tome], "magic", {"magic": 99}, CombatTarget(damage_cap=25), spell="fire_surge"
    ).supported


def test_review_preserves_other_blockers_and_does_not_mutate(make_content):
    tome = load_catalog(make_content()).items[20714]
    row = tome.model_dump()
    row["unsupported_effects"] = ["Offensive effects have not been validated.", "Other"]
    assert apply_review(row)["unsupported_effects"] == ["Other"]
    assert len(row["unsupported_effects"]) == 2
    with pytest.raises(ValueError, match="physical form changed"):
        apply_review({**row, "slot": "neck"})
    assert applied_tome(None, "fire_surge") is None
    assert applied_tome(tome, "fire_surge", "warped") is None


def test_searing_low_hit_retains_accurate_zero_rule(make_content):
    tome = load_catalog(make_content()).items[20714]
    role = SimpleNamespace(
        style="magic", spell="fire_strike", stance="accurate", fire_tome_pages="searing"
    )
    result = evaluate_loadout([tome], role, {"magic": 13})
    assert result.max_hit == 8
    assert result.tome_bonus.minimum_hit == 1
    assert result.dps == pytest.approx(result.accuracy * (4 + 1 / 9) / 3)
