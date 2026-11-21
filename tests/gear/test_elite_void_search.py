"""Individual raw-stat pruning must preserve a complete Elite Void ranged set."""

from dataclasses import replace

from tests.gear.test_optimizer import NOW, weapon
from tests.gear.test_scoring_options import context
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear import optimizer
from tracker.gear.facts import equipment_fact
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig


def test_complete_set_search_and_conflicting_lock(monkeypatch):
    role = RoleConfig(id="ranged", style="ranged")
    snapshot, _, _, request = context(role)
    pieces = {"body": 13072, "legs": 13073, "head": 11664, "hands": 8842}
    items = {
        1: weapon(1, "ranged", 100),
        **{
            i: EquipmentDefinition(id=i, name=str(i), slot=slot, requirements_complete=True)
            for slot, i in pieces.items()
        },
        **{
            i: EquipmentDefinition(
                id=i,
                name=str(i),
                slot=slot,
                requirements_complete=True,
                bonuses=EquipmentBonuses(ranged=1),
            )
            for i, slot in enumerate(pieces, 2)
        },
    }
    snapshot = replace(
        snapshot,
        skills={"ranged": SkillState(99, None, Source.MANUAL, NOW)},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "set", NOW) for i in items
        },
    )
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in items.items()}
    monkeypatch.setattr(optimizer, "CANDIDATES_PER_SLOT", 2)
    monkeypatch.setattr(optimizer, "BEAM_WIDTH", 2)
    search = optimizer._Search(snapshot, request, items, facts, None)
    assert any(all(e.get(s) == i for s, i in pieces.items()) for e in search.loadouts((role,)))
    for s, i in pieces.items():
        assert i in search.pools[s]
    locked = role.model_copy(update={"locks": {"hands": None}})
    assert all("hands" not in e for e in search.loadouts((locked,)))
