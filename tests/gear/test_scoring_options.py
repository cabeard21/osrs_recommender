"""Search-local option reuse must preserve account, role and physical validation."""

from collections import Counter

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear import optimizer
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.facts import equipment_fact
from tracker.gear.frontier import _combat_variants
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, _Search


def context(role):
    items = {
        1: weapon(1, "slash", 40, attack_profiles=(("slash", "accurate"), ("slash", "aggressive"))),
        2: EquipmentDefinition(
            id=2,
            name="Helmet",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(slash=20, melee_strength=10),
        ),
    }
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={key: SkillState(70, None, Source.MANUAL, NOW) for key in ("attack", "strength")},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in items
        },
    )
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in items.items()}
    return snapshot, items, facts, OptimizationRequest(roles=(role,), mode="owned")


@pytest.mark.parametrize("attack_types", [("slash",), ()])
def test_options_enumerated_once_per_weapon_and_search(monkeypatch, attack_types):
    role = RoleConfig(
        id="melee",
        style="slash",
        combat_options=CombatOptionFilters(
            attack_types=attack_types,
            stances=("accurate", "aggressive"),
            spells=(),
        ),
    )
    snapshot, items, facts, request = context(role)
    calls = Counter()
    original = optimizer.eligible_combat_options

    def measured(weapon, *args, **kwargs):
        calls[weapon.id if weapon else None] += 1
        return original(weapon, *args, **kwargs)

    monkeypatch.setattr(optimizer, "eligible_combat_options", measured)
    for _ in range(2):
        calls.clear()
        search = _Search(snapshot, request, items, facts, None)
        search.performance({"weapon": 1}, role)
        search.performance({"weapon": 1, "head": 2}, role)
        seed = search.solution({role.id: {"weapon": 1, "head": 2}}, None)
        if seed is not None:
            list(_combat_variants(search, seed, lambda: True))
        assert calls[1] == 1
        assert all(count == 1 for count in calls.values())


@pytest.mark.parametrize("equipment", [{"weapon": 999}, {"head": 1}, {"weapon": 1, "body": 2}])
def test_incremental_search_preserves_physical_errors(equipment):
    role = RoleConfig(id="melee", style="slash")
    snapshot, items, facts, request = context(role)
    search = _Search(snapshot, request, items, facts, None)
    assert search.performance(equipment, role) == evaluate_equipment(
        equipment,
        items,
        role,
        search.levels,
    ).model_dump(mode="json")


def test_same_weapon_keeps_distinct_role_filters_and_targets():
    accurate = RoleConfig(
        id="accurate",
        style="slash",
        target=CombatTarget(defence_level=200),
        combat_options=CombatOptionFilters(
            attack_types=("slash",),
            stances=("accurate",),
            spells=(),
        ),
    )
    aggressive = accurate.model_copy(
        update={
            "id": "aggressive",
            "target": CombatTarget(defence_level=1),
            "combat_options": CombatOptionFilters(
                attack_types=("slash",),
                stances=("aggressive",),
                spells=(),
            ),
        }
    )
    snapshot, items, facts, request = context(accurate)
    request = request.model_copy(update={"roles": (accurate, aggressive)})
    search = _Search(snapshot, request, items, facts, None)
    equipment = {"weapon": 1, "head": 2}
    for role, stance in ((accurate, "accurate"), (aggressive, "aggressive")):
        configured = role.model_copy(update={"stance": stance})
        assert search.performance(equipment, role) == evaluate_equipment(
            equipment,
            items,
            configured,
            search.levels,
        ).model_dump(mode="json")
        assert search.combat_option(equipment, role)["stance"] == stance


def test_option_variants_validate_and_prepare_one_physical_loadout(monkeypatch):
    role = RoleConfig(
        id="melee",
        style="slash",
        combat_options=CombatOptionFilters(
            attack_types=("slash",),
            stances=("accurate", "aggressive"),
            spells=(),
        ),
    )
    snapshot, items, facts, request = context(role)
    search = _Search(snapshot, request, items, facts, None)
    search.performance_cache = {}
    search.option_cache = {}
    calls = []
    original = optimizer.equipment_problems

    def measured(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(optimizer, "equipment_problems", measured)
    assert search.performance({"weapon": 1, "head": 2}, role)["supported"]
    assert len(calls) == 1
