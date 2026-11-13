"""Equipment-dependent native magic scoring matches the Python oracle exactly."""

from types import SimpleNamespace

import pytest

from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_prepared_score
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import RoleConfig
from tracker.gear.scoring import prepare_equipment


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(load_content())


def magic_context(catalog, ids, role):
    ScoringContext = pytest.importorskip("tracker.gear.native._scoring").ScoringContext

    items = {i: catalog.items[i] for i in ids}
    search = SimpleNamespace(
        items=items,
        eligible=items,
        request=SimpleNamespace(roles=(role,), secondary_priority="prayer_bonus"),
        levels={"magic": 99, "ranged": 99, "attack": 99, "strength": 99, "defence": 99},
    )
    return ScoringContext(search), search


@pytest.mark.parametrize("tome", [20714, 20716, 25574, 25576, 30064, 30066])
@pytest.mark.parametrize("amulet", [34407, 34413, 34419, 34425, 34428])
@pytest.mark.parametrize("spell", ["wind_wave", "water_wave", "earth_wave", "fire_wave"])
@pytest.mark.parametrize("pages", ["burnt", "searing"])
def test_native_magic_effects_are_exact(catalog, tome, amulet, spell, pages):
    role = RoleConfig(
        id="mage",
        style="magic",
        spell=spell,
        target=CombatTarget(weakness_element="water", weakness_percent=53),
    ).model_copy(update={"fire_tome_pages": pages})
    context, search = magic_context(catalog, [4675, tome, amulet, 4091], role)
    equipment = {"weapon": 4675, "shield": tome, "neck": amulet, "body": 4091}
    expected = evaluate_prepared_score(
        prepare_equipment({s: search.items[i] for s, i in equipment.items()}), role, search.levels
    )
    actual = context.score(equipment, 0)
    assert actual["supported"] == expected.supported
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy


@pytest.mark.parametrize("spell", ["iban_blast", "ice_barrage"])
def test_nonstandard_spells_ignore_magic_effects(catalog, spell):
    role = RoleConfig(id="mage", style="magic", spell=spell)
    context, search = magic_context(catalog, [4675, 25574, 34428], role)
    equipment = {"weapon": 4675, "shield": 25574, "neck": 34428}
    expected = evaluate_prepared_score(
        prepare_equipment({s: search.items[i] for s, i in equipment.items()}), role, search.levels
    )
    actual = context.score(equipment, 0)
    assert actual["supported"] == expected.supported
    assert actual["dps"] == expected.dps


def test_equipped_amulet_keeps_spell_discarded_by_effect_blind_compression(catalog):
    ScoringContext = pytest.importorskip("tracker.gear.native._scoring").ScoringContext

    from tracker.gear.combat_options import CombatOption
    from tracker.gear.optimizer import CombatOptionFilters

    role = RoleConfig(
        id="mage",
        style="magic",
        combat_options=CombatOptionFilters(
            attack_types=("magic",), stances=("accurate",), spells=("water_wave", "fire_wave")
        ),
    )
    items = {i: catalog.items[i] for i in [4675, 34413]}
    records = tuple(
        (
            role.model_copy(update={"spell": spell}),
            CombatOption(attack_type="magic", stance="accurate", spell=spell),
        )
        for spell in ("water_wave", "fire_wave")
    )
    search = SimpleNamespace(
        items=items,
        eligible=items,
        request=SimpleNamespace(roles=(role,), secondary_priority="prayer_bonus"),
        levels={"magic": 99},
        configured_options=lambda role, weapon: records,
        scoring_options=lambda role, weapon: records[1:],
    )
    context = ScoringContext(search)
    actual = context.score({"weapon": 4675, "neck": 34413}, 0)
    assert context.option_records[actual["option_index"]][1].spell == "water_wave"


@pytest.mark.parametrize("kind", ["amulet", "tome"])
def test_unsafe_effect_metadata_falls_back_before_packing(catalog, kind):
    from tracker.gear.models import ElementalSpellBonus, TomeEffect
    from tracker.gear.native.packing import support_reason

    item = (
        catalog.items[34428].model_copy(
            update={
                "elemental_spell_bonus": ElementalSpellBonus(
                    elements=("air",), base_max_hit_bonus=10001
                )
            }
        )
        if kind == "amulet"
        else catalog.items[20714].model_copy(
            update={"tome_effect": TomeEffect(element="fire", rune_id=2**63)}
        )
    )
    role = RoleConfig(id="mage", style="magic")
    search = SimpleNamespace(
        items={item.id: item},
        eligible={item.id: item},
        request=SimpleNamespace(roles=(role,), secondary_priority="prayer_bonus"),
        levels={"magic": 99},
    )
    assert support_reason(search) == (
        "elemental_bonus_range" if kind == "amulet" else "tome_rune_range"
    )


def test_hopper_requires_crossbow_ammunition_membership(catalog):
    ScoringContext = pytest.importorskip("tracker.gear.native._scoring").ScoringContext

    weapon = catalog.items[9185].model_copy(update={"ammo_for": ()})
    items = {9185: weapon, 32879: catalog.items[32879], 9144: catalog.items[9144]}
    role = RoleConfig(
        id="ranged", style="ranged", stance="rapid", target=CombatTarget(hitpoints=500)
    )
    levels = {"ranged": 99}
    search = SimpleNamespace(
        items=items,
        eligible=items,
        request=SimpleNamespace(roles=(role,), secondary_priority="prayer_bonus"),
        levels=levels,
    )
    equipment = {"weapon": 9185, "shield": 32879, "ammunition": 9144}
    expected = evaluate_prepared_score(
        prepare_equipment({s: items[i] for s, i in equipment.items()}), role, levels
    )
    actual = ScoringContext(search).score(equipment, 0)
    assert actual["dps"] == expected.dps
