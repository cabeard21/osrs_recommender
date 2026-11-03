"""Incremental aggregates retain full-sum semantics and request-local isolation."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from tracker.gear.combat import evaluate_loadout, evaluate_prepared_loadout
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.scoring import EquipmentScorer, prepare_equipment


def item(item_id, slot, **bonuses):
    return EquipmentDefinition(
        id=item_id, name=str(item_id), slot=slot, bonuses=EquipmentBonuses(**bonuses)
    )


def original_bonuses(equipment, ranged=False):
    weapon = next((i for i in equipment if i.slot == "weapon"), None)
    return EquipmentBonuses(
        **{
            field: sum(
                getattr(i.bonuses, field)
                for i in equipment
                if not (
                    ranged
                    and i.slot == "ammunition"
                    and field in {"ranged", "ranged_strength"}
                    and (not weapon or not weapon.ammo_for)
                )
            )
            for field in EquipmentBonuses.model_fields
        }
    )


@pytest.mark.parametrize("bow", [False, True])
def test_incremental_append_replace_remove_and_ammunition_correction(bow):
    weapon = item(1, "weapon", ranged=20, melee_strength=11).model_copy(
        update={"ammo_for": ("arrow:test",) if bow else ()}
    )
    items = {
        1: weapon,
        2: item(2, "ammunition", ranged=5, ranged_strength=9, prayer=3, magic_damage=0.3),
        3: item(3, "head", magic_damage=0.1, defence_ranged=17),
        4: item(4, "head", magic_damage=-0.2, ranged=-4),
    }
    scorer = EquipmentScorer(items)
    for equipment in (
        {},
        {"weapon": 1},
        {"weapon": 1, "ammunition": 2},
        {"weapon": 1, "ammunition": 2, "head": 3},
        {"weapon": 1, "ammunition": 2, "head": 4},
        {"ammunition": 2, "head": 4},
        {"head": 3},
    ):
        prepared = scorer.prepare(equipment)
        equipped = tuple(items[i] for i in equipment.values())
        assert prepared == prepare_equipment(equipped)
        assert prepared.bonuses == original_bonuses(equipped)
        assert prepared.ranged_bonuses == original_bonuses(equipped, ranged=True)


def test_full_preparation_preserves_mapping_order_and_first_physical_slots():
    items = (
        item(1, "ammunition", ranged=1, ranged_strength=2, magic_damage=0.1),
        item(2, "weapon", melee_strength=3),
        item(3, "ammunition", ranged=7, ranged_strength=8, magic_damage=0.2),
        item(4, "weapon", melee_strength=13).model_copy(update={"ammo_for": ("arrow:test",)}),
    )
    prepared = prepare_equipment(dict(enumerate(items)))
    assert prepared.equipment == items
    assert prepared.weapon is items[1]
    assert prepared.ammunition is items[0]
    assert prepared.ranged_bonuses == original_bonuses(items, ranged=True)


@pytest.mark.parametrize(
    "values",
    [(1e16, 1.0, -1e16), (0.1, 0.2, -0.3), (1e16, -1e16, 1.0), (0.7, 0.1, 0.2)],
)
def test_float_magic_damage_uses_original_ordered_builtin_sum(values):
    items = {
        i: item(i, slot, magic_damage=value)
        for i, (slot, value) in enumerate(zip(("head", "body", "legs"), values, strict=True), 1)
    }
    scorer = EquipmentScorer(items)
    ordered = {definition.slot: key for key, definition in items.items()}
    reverse = dict(reversed(tuple(ordered.items())))
    for equipment in (ordered, reverse):
        prepared = scorer.prepare(equipment)
        assert prepared.bonuses.magic_damage == sum(
            items[i].bonuses.magic_damage for i in equipment.values()
        )
        assert prepared == prepare_equipment(tuple(items[i] for i in equipment.values()))
        assert prepared.equipment == tuple(items[i] for i in equipment.values())
    assert scorer.prepare(ordered).equipment != scorer.prepare(reverse).equipment


def test_cached_prefixes_are_reused_and_return_values_are_immutable():
    items = {1: item(1, "weapon", stab=7), 2: item(2, "head", prayer=2)}
    scorer = EquipmentScorer(items)
    parent = scorer.prepare({"weapon": 1})
    before = scorer.cache_info()
    child = scorer.prepare({"weapon": 1, "head": 2})
    after = scorer.cache_info()
    assert after.misses == before.misses + 1
    assert after.hits == before.hits + 1
    assert scorer.prepare({"weapon": 1}) is parent
    assert scorer.prepare({"weapon": 1, "head": 2}) is child
    assert parent.bonuses.prayer == 0
    assert child.bonuses.prayer == 2
    with pytest.raises(FrozenInstanceError):
        child.weapon = None


def test_preparation_does_not_copy_unused_ranged_bonus_models(monkeypatch):
    definitions = (
        item(1, "weapon", stab=10),
        item(2, "ammunition", ranged=3, ranged_strength=8, prayer=2),
        item(3, "head", melee_strength=7),
    )
    copies = []
    original = EquipmentBonuses.model_copy

    def measured(bonuses, **kwargs):
        copies.append(kwargs)
        return original(bonuses, **kwargs)

    monkeypatch.setattr(EquipmentBonuses, "model_copy", measured)
    scorer = EquipmentScorer({definition.id: definition for definition in definitions})
    full = prepare_equipment(definitions)
    prepared = scorer.prepare({definition.slot: definition.id for definition in definitions})
    assert prepared.bonuses == full.bonuses
    assert copies == []
    assert prepared.ranged_bonuses.ranged == 0
    assert prepared.ranged_bonuses.ranged_strength == 0
    assert prepared.ranged_bonuses.prayer == 2
    assert prepared.bonuses.ranged == 3
    assert prepared.bonuses.ranged_strength == 8
    assert copies


def test_caches_are_bounded_and_catalog_specific():
    items = {i: item(i, "weapon", stab=i) for i in range(1, 8200)}
    scorer = EquipmentScorer(items)
    for key in items:
        assert scorer.prepare({"weapon": key}).bonuses.stab == key
    assert scorer.cache_info().currsize == scorer.cache_info().maxsize == 8192
    other = EquipmentScorer({1: item(1, "weapon", stab=-100)})
    assert other.prepare({"weapon": 1}).bonuses.stab == -100
    assert scorer.prepare({"weapon": 1}).bonuses.stab == 1


@pytest.mark.parametrize("style", ["stab", "slash", "crush", "ranged", "magic", "special"])
@pytest.mark.parametrize("stance", ["accurate", "aggressive", "rapid", "longrange"])
def test_incremental_combat_matches_full_evaluation_for_styles_stances_and_failures(style, stance):
    equipment = (
        item(1, "weapon", stab=20, slash=30, crush=15, ranged=12, magic=10).model_copy(
            update={
                "attack_styles": ("stab", "slash", "crush", "ranged"),
                "ammo_for": ("arrow:test",),
            }
        ),
        item(2, "ammunition", ranged_strength=22, magic_damage=0.1).model_copy(
            update={"ammo_type": "arrow:test"}
        ),
        item(3, "body", melee_strength=30, magic_damage=0.2, defence_stab=12),
    )
    scorer = EquipmentScorer({definition.id: definition for definition in equipment})
    prepared = scorer.prepare({definition.slot: definition.id for definition in equipment})
    levels = dict.fromkeys(("attack", "strength", "ranged", "magic"), 80)
    for target in (
        CombatTarget(),
        CombatTarget(weakness_element="fire", weakness_percent=35),
        CombatTarget(damage_cap=1),
        CombatTarget(unsupported_mechanics=("Fixture mechanic",)),
    ):
        for skills in (levels, {}):
            expected = evaluate_loadout(
                equipment, style, skills, target, stance=stance, spell="fire_wave"
            )
            actual = evaluate_prepared_loadout(
                prepared, style, skills, target, stance=stance, spell="fire_wave"
            )
            assert actual.model_dump(mode="json") == expected.model_dump(mode="json")


def test_incremental_preserves_invalid_slots_effects_powered_and_ancient_diagnostics():
    base = item(1, "weapon", magic_damage=3.5).model_copy(
        update={
            "powered_attack": "fixture",
            "powered_attack_base_max_hit": 15,
            "powered_attack_stances": ("accurate",),
            "spell_compatibility": ("ice_barrage",),
            "two_handed": True,
        }
    )
    duplicate = item(2, "weapon", magic_damage=0.3).model_copy(
        update={"unsupported_effects": ("Fixture effect",)}
    )
    shield = item(3, "shield", magic=-5)
    levels = {"magic": 99}
    for equipped in ((base,), (base, shield), (base, duplicate, shield), ()):
        scorer = EquipmentScorer({definition.id: definition for definition in equipped})
        prepared = scorer.prepare({str(i): definition.id for i, definition in enumerate(equipped)})
        for spell in ("ice_barrage", "iban_blast", "unknown_spell"):
            for powered in (None, "fixture", "mismatch"):
                role = SimpleNamespace(
                    style="magic", stance="accurate", spell=spell, powered_attack=powered
                )
                assert evaluate_prepared_loadout(prepared, role, levels) == evaluate_loadout(
                    equipped, role, levels
                )
