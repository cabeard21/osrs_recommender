"""Complete tier-dependent gear must survive weapon-first pruning."""

from dataclasses import replace

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tests.gear.test_scoring_options import context
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container
from tracker.gear import optimizer
from tracker.gear.facts import equipment_fact
from tracker.gear.models import CombatTarget, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig


def make_search(monkeypatch, tier, *, lock_ring=False, mixed=False):
    role = RoleConfig(
        id="vyre",
        style="slash",
        target=CombatTarget(traits=(f"vampyre{tier}",)),
        locks={"ring": None} if lock_ring else {},
    )
    ordinary = RoleConfig(id="ordinary", style="slash")
    snapshot, items, _, request = context(role)
    items = {
        **items,
        1000: weapon(1000, "slash", 250),
        33718: weapon(33718, "slash", 2),
        21140: EquipmentDefinition(
            id=21140, name="Efaritay's aid", slot="ring", requirements_complete=True
        ),
    }
    snapshot = replace(
        snapshot,
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in items
        },
    )
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in items.items()}
    request = request.model_copy(update={"roles": (role, ordinary) if mixed else (role,)})
    monkeypatch.setattr(optimizer, "CANDIDATES_PER_SLOT", 2)
    return optimizer._Search(snapshot, request, items, facts, None), role


def test_tier_two_scores_ordinary_weapon_with_ring_before_pruning(monkeypatch):
    search, role = make_search(monkeypatch, 2)
    assert {"weapon": 1, "ring": 21140} in search.baselines(role)
    assert {"weapon": 1} not in search.baselines(role)
    assert 33718 in search.pools["weapon"]
    assert 1000 in search.pools["weapon"]
    assert 21140 in search.pools["ring"]
    rows = search.loadouts((role,))
    best = max(rows, key=lambda row: search.performance(row, role)["dps"])
    assert (best.get("weapon"), best.get("ring")) == (1000, 21140)


@pytest.mark.parametrize("tier,lock_ring", [(2, True), (3, False)])
def test_seed_cannot_unlock_blocked_ring_or_tier_three(monkeypatch, tier, lock_ring):
    search, role = make_search(monkeypatch, tier, lock_ring=lock_ring)
    assert not any(e.get("weapon") == 1 for e in search.loadouts((role,)))


def test_mixed_roles_keep_feasible_ring_setup_at_zero_swaps(monkeypatch):
    search, _ = make_search(monkeypatch, 2, mixed=True)
    rows = search.joint_loadouts(0)
    assert any(
        r["vyre"].get("weapon") == 1000
        and r["vyre"].get("ring") == 21140
        and r["vyre"] == r["ordinary"]
        for r in rows
    )
