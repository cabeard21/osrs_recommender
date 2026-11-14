from pathlib import Path

import pytest

from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.npcs import npc_catalog, resolve_target
from tracker.gear.optimizer import RoleConfig


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(load_content(Path("content")))


@pytest.mark.parametrize("item_id", [4158, 11902, 20727, 4160, 33601, 11875, 21316])
def test_leafy_equipment_has_exact_review(catalog, item_id):
    item = catalog.items[item_id]
    assert item.requirements_complete
    assert not item.unsupported_effects
    assert item.requires is not None
    assert item.tradeable is (item_id in {11902, 20727, 11875, 21316})


def test_leafy_profiles_and_ammunition(catalog):
    assert catalog.items[4158].attack_profiles == (
        ("stab", "controlled"),
        ("slash", "controlled"),
        ("crush", "controlled"),
        ("stab", "defensive"),
    )
    assert catalog.items[20727].attack_profiles == (
        ("slash", "accurate"),
        ("slash", "aggressive"),
        ("crush", "aggressive"),
        ("slash", "defensive"),
    )
    for item_id in (4160, 33601):
        assert catalog.items[item_id].ammo_type == f"arrow:{item_id}"
        assert f"arrow:{item_id}" in catalog.items[861].ammo_for
        assert f"arrow:{item_id}" not in catalog.items[857].ammo_for
    for item_id in (11875, 21316):
        assert catalog.items[item_id].ammo_type == f"bolt:{item_id}"
        assert f"bolt:{item_id}" in catalog.items[9185].ammo_for
        assert f"bolt:{item_id}" not in catalog.items[9183].ammo_for


@pytest.mark.parametrize("npc_id", [427, 428, 429, 430, 10397, 410, 411, 7405])
def test_leafy_profiles_preserve_canonical_trait(npc_id):
    catalog = npc_catalog()
    entry = next(e for e in catalog.entries.values() if e["npc_id"] == npc_id)
    assert entry["support_status"] == "supported"
    assert "leafy" in entry["target"]["traits"]
    role = RoleConfig(
        id="leafy",
        style="stab",
        target=entry["target"],
        target_selection={"key": entry["key"], "catalog_revision": catalog.revision},
    )
    assert resolve_target(role) == role
    with pytest.raises(ValueError, match="restrictions"):
        resolve_target(
            role.model_copy(update={"target": role.target.model_copy(update={"traits": ()})})
        )


@pytest.mark.parametrize("npc_id,minimum", [(427, 55), (10397, 55), (410, 70), (7405, 70)])
@pytest.mark.parametrize("level_offset", [-1, 0])
def test_target_slayer_boundary(catalog, npc_id, minimum, level_offset):
    from types import SimpleNamespace

    from tracker.gear.evaluation import validate_request_context
    from tracker.gear.optimizer import OptimizationRequest

    npcs = npc_catalog()
    entry = next(e for e in npcs.entries.values() if e["npc_id"] == npc_id)
    request = OptimizationRequest(
        roles=(
            RoleConfig(
                id="leafy",
                style="stab",
                target_selection={"key": entry["key"], "catalog_revision": npcs.revision},
            ),
        )
    )
    snapshot = SimpleNamespace(skills={"slayer": SimpleNamespace(level=minimum + level_offset)})
    if level_offset < 0:
        with pytest.raises(ValueError, match=f"requires {minimum} Slayer"):
            validate_request_context(
                request, snapshot, catalog.items, load_content(Path("content"))
            )
    else:
        validate_request_context(request, snapshot, catalog.items, load_content(Path("content")))


def test_target_slayer_unknown_and_future_override(catalog):
    from types import SimpleNamespace

    from tracker.gear.evaluation import validate_request_context
    from tracker.gear.optimizer import OptimizationRequest

    npcs = npc_catalog()
    entry = next(e for e in npcs.entries.values() if e["npc_id"] == 410)
    role = RoleConfig(
        id="leafy",
        style="stab",
        target_selection={"key": entry["key"], "catalog_revision": npcs.revision},
    )
    snapshot = SimpleNamespace(skills={})
    content = load_content(Path("content"))
    with pytest.raises(ValueError, match="unknown or unmet"):
        validate_request_context(
            OptimizationRequest(roles=(role,)), snapshot, catalog.items, content
        )
    validate_request_context(
        OptimizationRequest(roles=(role,), mode="future", skill_overrides={"slayer": 70}),
        snapshot,
        catalog.items,
        content,
    )


def test_review_rejects_changed_identity_and_preserves_unrelated_blockers(catalog):
    from tracker.gear.leafy import apply_review

    row = catalog.items[4158].model_dump()
    row = {**row, "name": "Unexpected spear", "unsupported_effects": []}
    with pytest.raises(ValueError, match="physical form changed"):
        apply_review(row)
    row = {
        **row,
        "name": "Leaf-bladed spear",
        "unsupported_effects": ["Offensive effects have not been validated.", "Unrelated blocker"],
    }
    assert apply_review(row)["unsupported_effects"] == ["Unrelated blocker"]


def test_reviewed_slayer_equipment_gates(catalog):
    from tracker.gear.leafy import REQUIREMENTS

    for item_id, expected in REQUIREMENTS.items():
        assert catalog.items[item_id].requires.to_yaml() == {
            "all_of": [{"skill": {k: v}} for k, v in sorted(expected.items())]
        }


def test_leafy_candidates_survive_small_mixed_target_slot_cap(catalog, monkeypatch):
    from dataclasses import replace

    from tests.gear.test_optimizer import NOW, weapon
    from tests.gear.test_scoring_options import context
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.content.loader import Content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear import optimizer
    from tracker.gear.facts import equipment_fact
    from tracker.gear.leafy import BROAD_AMMO, LEAF_WEAPONS
    from tracker.gear.models import CombatTarget, EquipmentDefinition
    from tracker.gear.slayer import MAGIC_DART_STAVES

    role = RoleConfig(id="leafy", style="slash", target=CombatTarget(traits=("leafy",)))
    snapshot, items, _, request = context(role)
    contextual = BROAD_AMMO | LEAF_WEAPONS | MAGIC_DART_STAVES
    items = {
        **items,
        **{i: catalog.items[i].model_copy(update={"requires": None}) for i in contextual},
        **{i: weapon(i, "slash", 200) for i in range(100, 110)},
        **{
            i: EquipmentDefinition(
                id=i, name=f"Ammo {i}", slot="ammunition", requirements_complete=True
            )
            for i in range(200, 210)
        },
    }
    snapshot = replace(
        snapshot,
        skills={
            key: SkillState(90, None, Source.MANUAL, NOW)
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
    assert LEAF_WEAPONS | MAGIC_DART_STAVES <= set(pools["weapon"])
    assert BROAD_AMMO <= set(pools["ammunition"])
