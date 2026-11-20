"""Physical revenant weapon forms and their legal ordinary attacks."""

import pytest

from tests.gear.test_combat_options import account
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_loadout
from tracker.gear.combat_options import eligible_combat_options
from tracker.gear.revenant import apply_review, passive_applies


@pytest.fixture(scope="module")
def items():
    from tracker.content.loader import Content

    return load_catalog(Content()).items


@pytest.mark.parametrize(
    "charged,uncharged,skill,level",
    [
        (22545, 22542, "attack", 60),
        (27660, 27657, "attack", 70),
        (22550, 22547, "ranged", 60),
        (27655, 27652, "ranged", 70),
        (22555, 22552, "magic", 60),
        (27665, 27662, "magic", 70),
        (27788, 27785, "magic", 60),
        (27679, 27676, "magic", 70),
    ],
)
def test_physical_forms_have_distinct_names_and_verified_wear_gates(
    items, charged, uncharged, skill, level
):
    for item_id in (charged, uncharged):
        item = items[item_id]
        assert item.name.endswith("(charged)" if item_id == charged else "(uncharged)")
        assert item.tradeable is (item_id == uncharged)
        assert item.requirements_complete and item.requires.skill == skill
        assert item.requires.level == level


@pytest.mark.parametrize("item_id", [22542, 22545, 27660, 27657])
def test_each_mace_has_all_four_profiles(items, item_id):
    item = items[item_id]
    options = eligible_combat_options(item, account(), discipline="melee", levels={})
    assert {(o.attack_type, o.stance) for o in options} == {
        ("crush", "accurate"),
        ("crush", "aggressive"),
        ("stab", "controlled"),
        ("crush", "defensive"),
    }
    assert {o.charges for o in options} == (
        {"unknown"} if item_id in {22545, 27660} else {"not_applicable"}
    )
    assert not item.unsupported_effects


@pytest.mark.parametrize("charged,uncharged", [(22550, 22547), (27655, 27652)])
def test_bows_require_ether_and_use_standard_projectiles(items, charged, uncharged):
    options = eligible_combat_options(items[charged], account(), discipline="ranged", levels={})
    assert {(o.attack_type, o.stance) for o in options} == {
        ("standard", "accurate"),
        ("standard", "rapid"),
        ("standard", "longrange"),
    }
    assert all(o.charges == "unknown" and o.ammunition == "not_applicable" for o in options)
    assert not items[charged].ammo_for and not items[charged].unsupported_effects
    assert not eligible_combat_options(items[uncharged], account(), discipline="ranged", levels={})


@pytest.mark.parametrize("bow", [22550, 27655])
def test_internal_arrows_ignore_equipped_projectiles_and_keep_blessing_prayer(items, bow):
    from tracker.gear.optimizer import RoleConfig

    role = RoleConfig(id="range", style="ranged", stance="rapid")
    base = evaluate_loadout([items[bow]], role, {"ranged": 99})
    assert base.supported
    for ammo in (892, 9243, 20226):  # Rune arrow, diamond bolts (e), Peaceful blessing
        result = evaluate_loadout([items[bow], items[ammo]], role, {"ranged": 99})
        assert result.supported
        assert (result.attack_roll, result.max_hit, result.dps) == (
            base.attack_roll,
            base.max_hit,
            base.dps,
        )
        assert result.bolt_effect is None
        assert result.bonuses.prayer == base.bonuses.prayer + items[ammo].bonuses.prayer


@pytest.mark.parametrize("charged,uncharged", [(27788, 27785), (27679, 27676)])
def test_autocasting_forms_disclose_charge_status_only_for_charged_casts(items, charged, uncharged):
    for item_id in (charged, uncharged):
        options = eligible_combat_options(items[item_id], account(), discipline="magic", levels={})
        assert options and {o.charges for o in options} == (
            {"unknown"} if item_id == charged else {"not_applicable"}
        )


def test_review_rejects_unexpected_physical_forms_and_preserves_specific_blockers():
    row = {
        "id": 22545,
        "name": "Viggora's chainmace",
        "slot": "weapon",
        "unsupported_effects": ["Additional unreviewed effect"],
    }
    assert apply_review(row)["unsupported_effects"] == row["unsupported_effects"]
    with pytest.raises(ValueError, match="physical form changed"):
        apply_review({**row, "name": "A different weapon"})


@pytest.mark.parametrize(
    "charged,empty,style",
    [
        (22545, 22542, "crush"),
        (27660, 27657, "stab"),
        (22550, 22547, "standard"),
        (27655, 27652, "ranged"),
        (22555, 22552, "magic"),
        (27665, 27662, "magic"),
        (27788, 27785, "magic"),
        (27679, 27676, "magic"),
    ],
)
def test_passive_requires_charged_physical_id_and_discipline(charged, empty, style):
    assert passive_applies(charged, style)
    assert not passive_applies(empty, style)
    assert not passive_applies(charged, "magic" if style != "magic" else "crush")
