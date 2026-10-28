"""Community ordinary classification needs independent physical/source evidence."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tracker.gear.community import classify_ordinary


@pytest.fixture
def ordinary():
    physical = next(
        row
        for row in json.loads(Path("content/equipment/catalog.json").read_text())
        if row["id"] == 1319
    )
    external = {
        "id": 1319,
        "name": "Rune 2h sword",
        "incomplete": False,
        "equipable_by_player": True,
        "tradeable_on_ge": True,
        "tradeable": True,
        "noted": False,
        "placeholder": False,
        "duplicate": False,
        "quest_item": False,
        "examine": "A two handed sword.",
        "equipment": {"slot": "weapon", "requirements": {"attack": 40}},
        "weapon": {"weapon_type": "2h_sword", "attack_speed": 7},
    }
    capture = {
        "id": 1319,
        "version": "",
        "category": "2h Sword",
        "normalized": physical,
    }
    return physical, external, capture


def test_plain_weapon_is_ordinary_without_mutating_sources(ordinary):
    before = copy.deepcopy(ordinary)
    result, reason = classify_ordinary(*ordinary)
    assert result["classification"] == "ordinary"
    assert result["cosmetic_variant"] is False
    assert result["tradeable"] is True
    assert reason is None
    assert ordinary == before


@pytest.mark.parametrize(
    "patch",
    [
        {"id": 1320},
        {"incomplete": True},
        {"duplicate": True},
        {"noted": True},
        {"placeholder": True},
        {"quest_item": True},
        {"tradeable_on_ge": False},
        {"equipable_by_player": False},
        {"equipment": {"slot": "weapon", "requirements": None}},
        {"weapon": {"weapon_type": "powered_staff", "attack_speed": 7}},
        {"examine": "A charged sword."},
    ],
)
def test_name_never_sufficient_for_ordinary_classification(ordinary, patch):
    physical, external, capture = ordinary
    result, reason = classify_ordinary(physical, {**external, **patch}, capture)
    assert result is None
    assert reason


def test_reject_physical_stat_drift(ordinary):
    physical, external, capture = ordinary
    changed = {**capture, "normalized": {**physical, "attack_speed": 4}}
    assert classify_ordinary(physical, external, changed)[1] == "physical_capture_mismatch"


def test_reject_poison_variant_and_explicit_blocker(ordinary):
    physical, external, capture = ordinary
    assert classify_ordinary(physical, external, {**capture, "version": "Poison"})[0] is None
    assert (
        classify_ordinary(
            {**physical, "unsupported_effects": ["Known charged mechanic"]}, external, capture
        )[1]
        == "explicit_unsupported_mechanic"
    )


@pytest.mark.parametrize("item_id", [805, 3101])
def test_known_special_attack_exceptions_stay_blocked(ordinary, item_id):
    physical, external, capture = ordinary
    assert classify_ordinary({**physical, "id": item_id}, external, capture)[1] == (
        "known_special_attack_mechanic"
    )


def test_unfamiliar_equipment_not_declared_ordinary(ordinary):
    physical, external, capture = ordinary
    assert classify_ordinary(physical, {**external, "name": "Strange blade"}, capture)[0] is None


@pytest.mark.parametrize(
    ("part", "patch", "reason"),
    [
        (
            "external",
            {"equipment": {"slot": "head", "requirements": {"attack": 40}}},
            "slot_mismatch",
        ),
        ("capture", {"category": "Powered Staff"}, "weapon_category_mismatch"),
        (
            "external",
            {"weapon": {"weapon_type": "2h_sword", "attack_speed": 4}},
            "weapon_speed_mismatch",
        ),
        ("physical", {"attack_profiles": []}, "missing_weapon_compatibility"),
        ("external", {"examine": ""}, "missing_category_evidence"),
    ],
)
def test_explicit_compatibility_evidence(ordinary, part, patch, reason):
    physical, external, capture = ordinary
    values = {"physical": physical, "external": external, "capture": capture}
    values[part] = {**values[part], **patch}
    if part == "physical":
        values["capture"] = {**capture, "normalized": values["physical"]}
    assert classify_ordinary(**values)[1] == reason


def test_two_handed_source_slot_requires_two_handed_physical(ordinary):
    physical, external, capture = ordinary
    external = {**external, "equipment": {**external["equipment"], "slot": "2h"}}
    assert classify_ordinary(physical, external, capture)[0]
    physical = {**physical, "two_handed": False}
    assert classify_ordinary(physical, external, capture)[1] == "slot_mismatch"


def test_missing_identity_capture_and_cosmetic_evidence(ordinary):
    physical, external, capture = ordinary
    assert classify_ordinary(physical, None, capture)[1] == "missing_source_identity"
    assert classify_ordinary(physical, external, None)[1] == "missing_physical_capture"
    armor = {**physical, "slot": "body"}
    external = {
        **external,
        "name": "Rune platebody (t)",
        "equipment": {"slot": "body", "requirements": {"defence": 40}},
        "weapon": None,
    }
    result, _ = classify_ordinary(armor, external, {**capture, "normalized": armor})
    assert result["cosmetic_variant"]


def test_ranged_weapons_need_ammunition_compatibility(ordinary):
    physical, external, capture = ordinary
    physical = {**physical, "attack_styles": ["ranged"], "ammo_for": []}
    external = {
        **external,
        "name": "Magic longbow",
        "weapon": {"weapon_type": "bow", "attack_speed": 7},
    }
    capture = {**capture, "category": "Bow", "normalized": physical}
    assert classify_ordinary(physical, external, capture)[1] == "missing_ammunition_compatibility"


def test_zero_bonus_cosmetics_do_not_qualify(ordinary):
    physical, external, capture = ordinary
    physical = {**physical, "bonuses": dict.fromkeys(physical["bonuses"], 0)}
    assert (
        classify_ordinary(physical, external, {**capture, "normalized": physical})[1]
        == "no_combat_benefit"
    )


def test_build_preserves_authored_and_missing_evidence(ordinary, monkeypatch):
    from tools import build_community_equipment as tool

    physical, external, capture = ordinary
    monkeypatch.setattr(tool, "normalize", lambda *args, **kwargs: physical)
    catalog = SimpleNamespace(items={1319: SimpleNamespace(content_ids=())})
    source = {"1319": external}
    maps = {"1319": {"attack": 40}}
    items, exceptions = tool.build(source, [physical], [capture], catalog, maps)
    assert len(items) == 1 and not exceptions
    catalog.items[1319] = SimpleNamespace(content_ids=("reviewed-unknown",))
    assert tool.build(source, [physical], [capture], catalog, maps)[1] == {
        "1319": "authored_metadata_preserved"
    }
    catalog.items[1319] = SimpleNamespace(content_ids=())
    assert (
        tool.build(source, [physical], [capture], catalog, {})[1]["1319"]
        == "missing_valid_requirement_map"
    )
    assert (
        tool.build(source, [physical], [], catalog, maps)[1]["1319"]
        == "missing_or_ambiguous_physical_capture"
    )
    assert tool.build(source, [physical], [capture, capture], catalog, maps)[0] == {}
    assert (
        tool.build(
            {"1319": {**external, "incomplete": True}}, [physical], [capture], catalog, maps
        )[0]
        == {}
    )


def test_generator_binds_pinned_inputs_and_is_deterministic(ordinary, monkeypatch, tmp_path):
    import hashlib

    from tools import build_community_equipment as tool

    physical, external, capture = ordinary
    root = tmp_path / "equipment"
    root.mkdir()
    source, raw_capture = tmp_path / "source.json", tmp_path / "capture.json"
    source.write_text(json.dumps({"1319": external}))
    raw_capture.write_text(json.dumps([capture]))
    (root / "catalog.json").write_text(json.dumps([physical]))
    (root / "requirements.json").write_text(
        json.dumps(
            {
                "source": {"sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
                "items": {"1319": {"attack": 40}},
            }
        )
    )
    (root / "manifest.json").write_text(
        json.dumps({"capture_sha256": hashlib.sha256(raw_capture.read_bytes()).hexdigest()})
    )
    monkeypatch.setattr(tool, "normalize", lambda *args, **kwargs: physical)
    monkeypatch.setattr(tool, "load_content", lambda *args: None)
    monkeypatch.setattr(
        tool,
        "load_catalog",
        lambda *args: SimpleNamespace(items={1319: SimpleNamespace(content_ids=())}),
    )
    output = root / "community.json"
    argv = [
        "--source",
        str(source),
        "--capture",
        str(raw_capture),
        "--content",
        str(tmp_path),
        "--output",
        str(output),
    ]
    tool.main(argv)
    before = output.read_bytes()
    tool.main(argv)
    assert before == output.read_bytes()
    data = json.loads(before)
    assert data["summary"]["noncosmetic_ids"] == 1
    assert (
        data["provenance"]["catalog_sha256"]
        == hashlib.sha256((root / "catalog.json").read_bytes()).hexdigest()
    )
    assert (
        data["provenance"]["requirements_sha256"]
        == hashlib.sha256((root / "requirements.json").read_bytes()).hexdigest()
    )
    with pytest.raises(SystemExit):
        tool.main([*argv[:-2], "--output", str(source)])
    source.write_text("{}")
    with pytest.raises(SystemExit):
        tool.main(argv)
