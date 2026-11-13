from datetime import UTC, datetime

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.domain.types import SkillState, Source, UnlockState
from tracker.gear.combat import ELEMENTAL_SPELLS, evaluate_prepared_loadout
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, _Search


def search_for(monkeypatch, *, target=None, spells=None, magic=99, unlocked=True):
    monkeypatch.setattr(_Search, "candidate_pools", lambda self: {})
    role = RoleConfig(
        id="mage",
        style="magic",
        target=target,
        combat_options=CombatOptionFilters(
            attack_types=("magic",),
            stances=("accurate", "defensive"),
            spells=tuple(ELEMENTAL_SPELLS if spells is None else spells),
        ),
    )
    snapshot = AccountSnapshot(
        1,
        "fixture",
        skills={"magic": SkillState(magic, None, Source.RUNELITE, datetime.now(UTC))},
        unlocks={"spellbook_standard": UnlockState.UNLOCKED if unlocked else UnlockState.LOCKED},
    )
    weapon = EquipmentDefinition(
        id=1,
        name="Staff",
        slot="weapon",
        spell_compatibility=tuple(ELEMENTAL_SPELLS),
    )
    body = EquipmentDefinition(
        id=2, name="Body", slot="body", bonuses=EquipmentBonuses(magic=12, magic_damage=3)
    )
    search = _Search(
        snapshot, OptimizationRequest(roles=(role,)), {1: weapon, 2: body}, {}, None, {}
    )
    return search, role


def reference(search, role, equipment):
    prepared = search.prepare(equipment)
    rows = [
        (
            evaluate_prepared_loadout(prepared, configured, search.levels).model_dump(mode="json"),
            option,
        )
        for configured, option in search.configured_options(
            role, search.items.get(equipment.get("weapon"))
        )
    ]
    valid = [(performance, option) for performance, option in rows if performance["supported"]]
    if not valid:
        return None
    performance, option = max(
        valid,
        key=lambda row: (
            row[0].get("dps") or 0,
            row[1].attack_type,
            row[1].stance,
            row[1].spell or "",
        ),
    )
    return performance, option.model_dump(
        mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
    )


def test_equivalent_elemental_attacks_are_scored_once_but_remain_available(monkeypatch):
    search, role = search_for(monkeypatch)
    import tracker.gear.optimizer as optimizer

    calls = []
    original = optimizer.evaluate_prepared_score

    def count(*args, **kwargs):
        calls.append(args[1].spell)
        return original(*args, **kwargs)

    monkeypatch.setattr(optimizer, "evaluate_prepared_score", count)
    assert len(search.configured_options(role, search.items[1])) == 40
    search.performance({"weapon": 1, "body": 2}, role)
    assert len(calls) == 10
    assert len(search.configured_options(role, search.items[1])) == 40


@pytest.mark.parametrize("weakness", [None, "air", "fire", "water", "earth"])
@pytest.mark.parametrize("magic", [1, 13, 59, 99])
@pytest.mark.parametrize("damage_cap", [None, 1, 16])
def test_scoring_dedup_matches_every_original_option(monkeypatch, weakness, magic, damage_cap):
    target = CombatTarget(weakness_element=weakness, weakness_percent=50, damage_cap=damage_cap)
    search, role = search_for(monkeypatch, target=target, magic=magic)
    for equipment in ({}, {"weapon": 1}, {"weapon": 1, "body": 2}):
        expected = reference(search, role, equipment)
        actual = search.performance(equipment, role)
        if expected is None:
            assert not actual["supported"]
        else:
            assert actual == expected[0]
            assert search.combat_option(equipment, role) == expected[1]


@pytest.mark.parametrize("spells", [("fire_strike",), ("fire_strike", "earth_bolt"), ()])
@pytest.mark.parametrize("unlocked", [False, True])
def test_dedup_preserves_spell_filters_and_account_access(monkeypatch, spells, unlocked):
    search, role = search_for(monkeypatch, spells=spells, unlocked=unlocked)
    equipment = {"weapon": 1}
    expected = reference(search, role, equipment)
    actual = search.performance(equipment, role)
    if expected is None:
        assert not actual["supported"]
    else:
        assert actual == expected[0]
        assert search.combat_option(equipment, role) == expected[1]


@pytest.mark.parametrize("weakness", [None, "air", "fire", "water", "earth"])
@pytest.mark.parametrize("cap", [None, 1, 16])
def test_amulet_spell_dedup_matches_exhaustive_across_necklaces(monkeypatch, weakness, cap):
    from tracker.gear.models import ElementalSpellBonus

    target = CombatTarget(weakness_element=weakness, weakness_percent=50, damage_cap=cap)
    search, role = search_for(monkeypatch, target=target)
    necklaces = {
        3 + index: EquipmentDefinition(
            id=3 + index,
            name="Amulet",
            slot="neck",
            bonuses=EquipmentBonuses(magic=10),
            elemental_spell_bonus=ElementalSpellBonus(elements=elements, base_max_hit_bonus=2),
        )
        for index, elements in enumerate(
            (("air",), ("water",), ("earth",), ("fire",), ("air", "water", "earth", "fire"))
        )
    }
    search.items = {**search.items, **necklaces}
    from tracker.gear.scoring import EquipmentScorer

    search.scorer = EquipmentScorer(search.items)
    for neck in (None, *necklaces, None):
        equipment = {"weapon": 1, "body": 2, **({"neck": neck} if neck else {})}
        expected = reference(search, role, equipment)
        actual = search.performance(equipment, role)
        if expected is None:
            assert not actual["supported"]
        else:
            assert actual == expected[0]
            assert search.combat_option(equipment, role) == expected[1]
