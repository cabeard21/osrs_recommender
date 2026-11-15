from pathlib import Path

import pytest

from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.npcs import NpcCatalog, resolve_target
from tracker.gear.optimizer import RoleConfig


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(load_content(Path("content")))


@pytest.mark.parametrize(
    "item_id", [2402, 6745, 6746, 19675, 30305, 29589, 29577, 29591, 29594, 732]
)
def test_reviewed_forms(catalog, item_id):
    item = catalog.items[item_id]
    assert item.requirements_complete
    assert not item.unsupported_effects
    assert item.tradeable is (item_id == 29577)


def test_profiles_and_physical_forms(catalog):
    from tracker.gear.demonbane import SPELLS, WEAPON_BONUSES

    assert WEAPON_BONUSES[30305] == 60
    assert WEAPON_BONUSES[19675] == 70
    assert catalog.items[30305].attack_speed == 5
    assert catalog.items[19675].attack_speed == 4
    assert ("stab", "controlled") in catalog.items[29577].attack_profiles
    assert "arrow:11212" in catalog.items[29591].ammo_for
    assert "arrow:4160" in catalog.items[29591].ammo_for
    assert not catalog.items[732].ammo_for
    for item_id in (4170, 21255, 29594):
        assert set(SPELLS) <= set(catalog.items[item_id].spell_compatibility)
    assert "fire_strike" in catalog.items[29594].spell_compatibility
    assert "ice_barrage" not in catalog.items[29594].spell_compatibility


def test_wear_gates_are_not_crafting_requirements(catalog):
    from tracker.gear.demonbane import REQUIREMENTS

    for item_id, gates in REQUIREMENTS.items():
        requirement = catalog.items[item_id].requires
        if not gates:
            assert requirement is None
        elif len(gates) == 1:
            assert requirement.to_yaml() == {"skill": dict(gates)}
        else:
            assert requirement.to_yaml() == {
                "all_of": [{"skill": {k: v}} for k, v in sorted(gates.items())]
            }


def test_exact_identity_and_unrelated_blockers(catalog):
    from tracker.gear.demonbane import apply_review

    row = catalog.items[29589].model_dump()
    with pytest.raises(ValueError, match="physical form"):
        apply_review({**row, "name": "Wrong"})
    assert apply_review(
        {**row, "unsupported_effects": ["Offensive effects have not been validated.", "Other"]}
    )["unsupported_effects"] == ["Other"]


@pytest.mark.parametrize(
    "npc_id,pct",
    [
        (12191, 70),
        (12195, 70),
        (14176, 120),
        (100001, 120),
        (16673, 80),
        (16677, 80),
        (16684, 80),
        (16665, 25),
        (16666, 25),
        (415, 100),
    ],
)
def test_target_effectiveness_is_canonical(npc_id, pct):
    npcs = NpcCatalog()
    entry = next(e for e in npcs.entries.values() if e["npc_id"] == npc_id)
    assert entry["target"]["demonbane_vulnerability_percent"] == pct
    role = RoleConfig(
        id="demon",
        style="slash",
        target=entry["target"],
        target_selection={"key": entry["key"], "catalog_revision": npcs.revision},
    )
    assert resolve_target(role) == role
    changed = role.target.model_copy(update={"demonbane_vulnerability_percent": pct + 1})
    with pytest.raises(ValueError, match="restrictions"):
        resolve_target(role.model_copy(update={"target": changed}))


def test_special_hit_profiles_stay_blocked():
    npcs = NpcCatalog()
    for npc_id in (5914, 13599, 14179, 7584):
        entry = next(e for e in npcs.entries.values() if e["npc_id"] == npc_id)
        assert entry["support_status"] == "unsupported"
    for npc_id in (3962, 6318, 6379):
        entry = next(e for e in npcs.entries.values() if e["npc_id"] == npc_id)
        assert "holy_water_special" in entry["target"]["traits"]
