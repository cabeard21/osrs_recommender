"""Dragonbane context survives complete optimizer entry points."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tests.gear.test_scoring_options import context
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import Content, load_content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear import optimizer
from tracker.gear.catalog import load_catalog
from tracker.gear.facts import equipment_fact
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import RoleConfig


def test_dragonbane_candidates_survive_small_mixed_target_slot_cap(monkeypatch):
    catalog = load_catalog(load_content(Path("content")))
    role = RoleConfig(id="dragon", style="slash", target=CombatTarget(traits=("dragon",)))
    snapshot, items, _, request = context(role)
    contextual = {22978, 21012, 25916, 25918, 30070}
    items = {
        **items,
        **{i: catalog.items[i].model_copy(update={"requires": None}) for i in contextual},
        **{i: weapon(i, "slash", 200) for i in range(100, 110)},
    }
    snapshot = replace(
        snapshot,
        skills={
            key: SkillState(99, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "magic", "ranged", "slayer")
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in items
        },
    )
    request = request.model_copy(update={"roles": (role, RoleConfig(id="ordinary", style="slash"))})
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in items.items()}
    monkeypatch.setattr(optimizer, "CANDIDATES_PER_SLOT", 2)
    pools = optimizer._Search(snapshot, request, items, facts, None).candidate_pools()
    # Only styles eligible for these roles need survive; ranged/magic are separate roles.
    assert {22978} <= set(pools["weapon"])


@pytest.mark.parametrize("npc_id", [817, 6118, 6349, 7940])
def test_canonical_dragonbane_exceptions_have_no_dragon_trait(npc_id):
    from tracker.gear.npcs import npc_catalog

    entries = [e for e in npc_catalog().entries.values() if e["npc_id"] == npc_id]
    assert entries
    assert all("dragon" not in e["target"]["traits"] for e in entries)


@pytest.mark.parametrize("name", ["Blue dragon", "Wyrm", "Hydra", "Skeletal Wyvern"])
def test_supported_draconic_families_preserve_their_affinity(name):
    from tracker.gear.npcs import npc_catalog

    entries = [
        e
        for e in npc_catalog().entries.values()
        if e["name"] == name and e["support_status"] == "supported"
    ]
    assert entries
    assert all("dragon" in e["target"]["traits"] for e in entries)
