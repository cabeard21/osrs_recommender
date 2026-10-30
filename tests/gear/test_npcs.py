import pytest

from tracker.gear.npcs import npc_catalog, resolve_target
from tracker.gear.optimizer import RoleConfig


def test_reported_level_53_lizardman_ordinary_profile():
    catalog = npc_catalog()
    entry = catalog.detail("c4b35626ceb46d21a4dc6ee8")
    assert (entry["npc_id"], entry["name"], entry["variant"]) == (6914, "Lizardman", "Level 53")
    assert entry["support_status"] == "supported"
    target = entry["target"]
    assert target["defence_level"] == 43
    assert target["magic_level"] == 1
    assert target["bonuses"] == {"stab": -20, "slash": 25, "crush": 0, "ranged": 0, "magic": 0}
    assert target["ranged_light"] == -10
    assert target["unsupported_mechanics"] == []
    role = RoleConfig(
        id="role-1",
        style="slash",
        target=target,
        target_selection={"key": entry["key"], "catalog_revision": catalog.revision},
    )
    assert resolve_target(role).target == role.target
    assert any("Poison" in note for note in entry["limitations"])


def test_catalog_search_and_mapping():
    catalog = npc_catalog()
    assert len(catalog.entries) > 1000
    result = catalog.search("Dagannoth Rex")
    entry = catalog.detail(result["items"][0]["key"])
    assert entry["target"]["defence_level"] == 255
    assert entry["support_status"] == "supported"
    assert catalog.search(str(entry["npc_id"]))["items"]


def test_selection_blocks_stale_and_restrictions():
    catalog = npc_catalog()
    entry = catalog.detail(catalog.search("Dagannoth Rex")["items"][0]["key"])
    role = RoleConfig(
        id="a",
        style="magic",
        target=entry["target"],
        target_selection={"key": entry["key"], "catalog_revision": catalog.revision},
    )
    assert resolve_target(role).target == role.target
    with pytest.raises(ValueError, match="revision"):
        resolve_target(
            role.model_copy(
                update={
                    "target_selection": role.target_selection.model_copy(
                        update={"catalog_revision": "old"}
                    )
                }
            )
        )
    zulrah = catalog.detail(catalog.search("Zulrah")["items"][0]["key"])
    role = role.model_copy(
        update={
            "target_selection": role.target_selection.model_copy(update={"key": zulrah["key"]}),
            "target": role.target.model_copy(update={"damage_cap": None}),
        }
    )
    with pytest.raises(ValueError, match="mechanic"):
        resolve_target(role)


def test_known_special_cannot_be_scored_and_missing_not_zero():
    catalog = npc_catalog()
    entry = catalog.detail(catalog.search("Akkha")["items"][0]["key"])
    assert entry["support_status"] == "unsupported"
    role = RoleConfig(
        id="a",
        style="magic",
        target_selection={"key": entry["key"], "catalog_revision": catalog.revision},
    )
    with pytest.raises(ValueError, match="scaling"):
        resolve_target(role)
    manifest = {"source_url": "https://example.com"}
    missing = catalog._entry(
        "missing", {"id": 99999, "name": "Missing", "skills": {}, "defensive": {}}, manifest
    )
    assert missing["target"] is None
    assert missing["support_status"] == "unsupported"


def test_stable_catalog_and_duplicate_names():
    from tracker.gear.npcs import NpcCatalog

    first = npc_catalog()
    second = NpcCatalog()
    assert first.revision == second.revision
    cows = first.search("Cow")["items"]
    assert len({e["key"] for e in cows}) == len(cows)
    assert len(cows) > 1


def test_checksum_rejected(tmp_path):
    import json

    from tracker.gear.npcs import NpcCatalog

    (tmp_path / "manifest.json").write_text(json.dumps({"catalog_sha256": "bad"}))
    (tmp_path / "monsters.json").write_text("[]")
    with pytest.raises(ValueError, match="checksum"):
        NpcCatalog(tmp_path)


@pytest.mark.parametrize("name", ["Lizardman", "Vorkath", "Black dragon", "Skeleton", "Hellhound"])
def test_complete_ordinary_profiles_do_not_require_review(name):
    catalog = npc_catalog()
    entries = [e for e in catalog.entries.values() if e["name"] == name]
    assert entries
    assert all(e["support_status"] == "supported" for e in entries)


@pytest.mark.parametrize(
    "attributes, expected",
    [
        (["demon", "undead", "dragon"], "supported"),
        (["leafy"], "unsupported"),
        (["vampyre3"], "unsupported"),
        (["unknown_future_mechanic"], "not_reviewed"),
    ],
)
def test_attribute_classification(attributes, expected):
    catalog = npc_catalog()
    row = dict(catalog.detail("49faa2e0a60a37be29725d55")["source_record"])
    row["attributes"] = attributes
    entry = catalog._entry("synthetic", row, {"source_url": "https://example.com"})
    assert entry["support_status"] == expected
    assert bool(entry["target"]["unsupported_mechanics"]) == (expected != "supported")


def test_flat_armour_remains_blocked_without_review():
    catalog = npc_catalog()
    row = dict(catalog.detail("49faa2e0a60a37be29725d55")["source_record"])
    row["defensive"] = {**row["defensive"], "flat_armour": 5}
    entry = catalog._entry("armoured", row, {"source_url": "https://example.com"})
    assert entry["support_status"] == "unsupported"
    assert "Flat armour" in entry["reasons"][0]


@pytest.mark.parametrize("style", ["stab", "slash", "crush"])
def test_zulrah_melee_immunity_preserved_with_supported_cap_subset(style):
    catalog = npc_catalog()
    entry = catalog.detail(catalog.search("Zulrah")["items"][0]["key"])
    assert entry["target"]["damage_cap"] == 50
    role = RoleConfig(
        id="melee",
        style=style,
        target=entry["target"],
        target_selection={"key": entry["key"], "catalog_revision": catalog.revision},
    )
    with pytest.raises(ValueError, match="immune to melee"):
        resolve_target(role)
