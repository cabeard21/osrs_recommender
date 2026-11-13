import pytest

from tracker.gear.catalog import load_catalog
from tracker.gear.combat import ELEMENTAL_SPELLS, evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig
from tracker.gear.scoring import prepare_equipment

IDS = {34407: "air", 34413: "water", 34419: "earth", 34425: "fire", 34428: "all"}


@pytest.mark.parametrize("item_id", IDS)
@pytest.mark.parametrize("spell", ELEMENTAL_SPELLS)
def test_elemental_bonus_matches_element(make_content, item_id, spell):
    amulet = load_catalog(make_content()).items[item_id]
    assert not amulet.unsupported_effects
    assert amulet.tradeable
    element = spell.split("_")[0].replace("wind", "air")
    applies = IDS[item_id] in (element, "all")
    baseline = evaluate_loadout([], "magic", {"magic": 99}, spell=spell)
    result = evaluate_loadout([amulet], "magic", {"magic": 99}, spell=spell)
    assert result.supported
    assert result.max_hit == baseline.max_hit + (2 if applies else 0)
    assert bool(result.elemental_amulet_bonus) == applies
    assert result.bonuses.magic_damage == 0
    role = RoleConfig(id="mage", style="magic", spell=spell)
    score = evaluate_prepared_score(prepare_equipment([amulet]), role, {"magic": 99})
    assert score.dps == result.dps


def test_bonus_precedes_damage_and_weakness(make_content):
    amulet = load_catalog(make_content()).items[34428]
    body = EquipmentDefinition(
        id=1, name="Damage", slot="body", bonuses=EquipmentBonuses(magic_damage=25)
    )
    result = evaluate_loadout(
        [amulet, body],
        "magic",
        {"magic": 59},
        CombatTarget(weakness_element="fire", weakness_percent=50),
        spell="fire_blast",
    )
    assert result.max_hit == 31
    assert result.elemental_weakness.max_hit_bonus == 9


@pytest.mark.parametrize("spell", ["iban_blast", "ice_barrage"])
def test_non_elemental_helper_has_no_bonus(make_content, spell):
    from tracker.gear.elemental_amulets import applied_spell_bonus

    amulet = load_catalog(make_content()).items[34428]
    assert applied_spell_bonus(amulet, spell) == 0
    assert applied_spell_bonus(amulet, "fire_strike", "shadow") == 0
    assert applied_spell_bonus(None, "fire_strike") == 0


@pytest.mark.parametrize("item_id", IDS)
@pytest.mark.parametrize("policy", ["verified_only", "community_best_effort"])
def test_wear_boundary_and_roundtrip(item_id, policy):
    from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
    from tracker.content.loader import load_content
    from tracker.gear.facts import equipment_fact
    from tracker.gear.support import project_catalog

    content = load_content()
    item = project_catalog(load_catalog(content), policy).items[item_id]
    assert item.requires.to_yaml() == {"skill": {"magic": 59}}
    assert item.requirements_complete
    assert item.content_ids
    assert EquipmentDefinition.model_validate_json(item.model_dump_json()) == item
    for level, status in [(58, "unsatisfied"), (59, "satisfied")]:
        fact = equipment_fact(snapshot(levels={"magic": level}), item, content, {}, NOW)
        assert fact["wear"]["status"] == status


def test_review_preserves_blockers_and_rejects_changed_form():
    from tracker.gear.elemental_amulets import apply_review

    row = {
        "id": 34428,
        "name": "Elemental amulet",
        "slot": "neck",
        "unsupported_effects": ["Offensive effects have not been validated.", "Other"],
    }
    assert apply_review(row)["unsupported_effects"] == ["Other"]
    assert len(row["unsupported_effects"]) == 2
    with pytest.raises(ValueError, match="physical form changed"):
        apply_review({**row, "slot": "body"})


def test_non_magic_attacks_and_damage_cap(make_content):
    amulet = load_catalog(make_content()).items[34428]
    for style in ["crush", "ranged"]:
        result = evaluate_loadout([amulet], style, {"attack": 99, "strength": 99, "ranged": 99})
        assert result.elemental_amulet_bonus is None
    result = evaluate_loadout(
        [amulet], "magic", {"magic": 99}, CombatTarget(damage_cap=1), spell="fire_surge"
    )
    assert not result.supported
    assert any("cap" in text.lower() for text in result.limitations)
    supported = evaluate_loadout(
        [amulet], "magic", {"magic": 99}, CombatTarget(damage_cap=30), spell="fire_surge"
    )
    assert supported.max_hit == 26
    assert supported.elemental_amulet_bonus.base_max_hit_bonus == 2


def test_prayer_rounding_and_score_parity(make_content):
    amulet = load_catalog(make_content()).items[34425]
    body = EquipmentDefinition(
        id=1, name="Damage", slot="body", bonuses=EquipmentBonuses(magic_damage=25)
    )
    role = RoleConfig(
        id="mage",
        style="magic",
        spell="fire_surge",
        target=CombatTarget(weakness_element="fire", weakness_percent=35),
    )
    role = role.model_copy(update={"active_prayer_ids": ("augury",)})
    result = evaluate_loadout([amulet, body], role, {"magic": 99})
    score = evaluate_prepared_score(prepare_equipment([amulet, body]), role, {"magic": 99})
    assert result.max_hit == 42  # floor(26 * 1.29) + floor(26 * .35)
    assert score.dps == result.dps


@pytest.mark.parametrize(
    "weapon_id,spell,powered",
    [
        (1409, "iban_blast", None),
        (4675, "ice_barrage", None),
        (11907, "fire_surge", "trident_of_the_seas"),
    ],
)
def test_non_elemental_combat_excludes_bonus(make_content, weapon_id, spell, powered):
    catalog = load_catalog(make_content())
    weapon = catalog.items[weapon_id]
    role = RoleConfig(
        id="mage",
        style="magic",
        spell=spell,
    )
    role = role.model_copy(update={"powered_attack": weapon.powered_attack if powered else None})
    amulet = catalog.items[34428]
    result = evaluate_loadout([amulet, weapon], role, {"magic": 99})
    assert result.supported
    assert result.elemental_amulet_bonus is None
