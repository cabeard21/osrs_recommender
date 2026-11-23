import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from tools import import_equipment_weights as importer
from tools.import_equipment_weights import build_weights, parse_form_pairs
from tracker.gear.catalog import load_catalog


def test_import_distinguishes_stackability_and_physical_state():
    ids = {1, 2, 3, 4, 5, 6}
    capture = [
        {"id": i, "weight": w}
        for i, w in [(1, 0.453), (2, 0.34), (3, -4.535), (4, 0.345), (5, 2.0), (6, 0)]
    ]
    items = {str(i): {"id": i, "weight": 0.34, "stackable": i == 4} for i in (1, 2, 3, 4, 6)}
    rows = build_weights(ids, capture, items, {3: 2})
    assert rows["worn_grams"] == {1: 453, 2: -4535, 3: -4535, 4: 0, 5: None, 6: 0}
    assert rows["inventory_forms"] == {3: {"id": 2, "grams": 340}}


def test_import_rejects_ambiguous_or_bad_weights():
    item = {"9": {"id": 9, "stackable": False}}
    for weight in [True, 0.0001, "2", float("inf"), None]:
        with pytest.raises(ValueError, match="weight"):
            build_weights({9}, [{"id": 9, "weight": weight}], item, {})
    with pytest.raises(ValueError, match="Conflicting"):
        build_weights({9}, [{"id": 9, "weight": 1}, {"id": 9, "weight": 2}], item, {})
    with pytest.raises(ValueError, match="inventory form"):
        build_weights({9}, [{"id": 9, "weight": -1}], item, {})


def test_form_parser_uses_only_top_level_runelite_gameval_ids():
    ids = "\tpublic static final int W = 89;\n\tpublic static final int I = 88;\n"
    ids += "\t\tpublic static final int I = 1000;\n"
    mapping = "WORN_ITEMS = ImmutableMap.builder().\nput(ItemID.W, ItemID.I).build();\n"
    assert parse_form_pairs(mapping, ids) == {89: 88}


def test_rebuild_weights_from_offline_sources_is_reproducible(tmp_path, monkeypatch):
    def write(name, value):
        data = (value if isinstance(value, str) else json.dumps(value)).encode()
        path = tmp_path / name
        path.write_bytes(data)
        return path, sha256(data).hexdigest()

    _, catalog_hash = write("catalog.json", [{"id": 89}])
    capture, capture_hash = write("source.json", [{"id": 89, "weight": -4.535}])
    items, items_hash = write(
        "external.json",
        {
            "88": {"id": 88, "stackable": False, "weight": 0.34},
            "89": {"id": 89, "stackable": False},
        },
    )
    manager, manager_hash = write("manager", "WORN_ITEMS = map.put(ItemID.W, ItemID.I).build()")
    gameval, id_hash = write(
        "ids", "\tpublic static final int W = 89;\n\tpublic static final int I = 88;"
    )
    write(
        "manifest.json",
        {"source": "test", "catalog_sha256": catalog_hash, "capture_sha256": capture_hash},
    )
    write("requirements.json", {"source": {"sha256": items_hash}})
    monkeypatch.setattr(
        importer, "RUNELITE_HASHES", {importer.MANAGER: manager_hash, importer.GAMEVAL: id_hash}
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_weights",
            "--root",
            str(tmp_path),
            "--capture",
            str(capture),
            "--items",
            str(items),
            "--item-manager",
            str(manager),
            "--gameval",
            str(gameval),
        ],
    )
    importer.main()
    artifact = tmp_path / "weights.json"
    expected = artifact.read_bytes()
    assert json.loads(expected)["inventory_forms"] == {"89": {"id": 88, "grams": 340}}
    importer.main()
    assert artifact.read_bytes() == expected
    capture.write_bytes(capture.read_bytes() + b" ")
    with pytest.raises(ValueError, match="capture checksum mismatch"):
        importer.main()
    assert artifact.read_bytes() == expected


def test_bundled_forms_have_signed_grams_and_stackable_equipment_is_weightless(make_content):
    catalog = load_catalog(make_content())
    normal = catalog.items[1127]
    assert (normal.worn_weight_grams, normal.inventory_weight_grams) == (9979, 9979)
    boots = catalog.items[89]
    assert (boots.inventory_form_id, boots.worn_weight_grams, boots.inventory_weight_grams) == (
        88,
        -4535,
        340,
    )
    for item_id in (9771, 13340):
        cape = catalog.items[item_id]
        assert (
            cape.inventory_form_id or cape.id,
            cape.worn_weight_grams,
            cape.inventory_weight_grams,
        ) == (9771, -4000, 453)
    assert catalog.items[33716].worn_weight_grams == 0
    assert catalog.items[22941].inventory_weight_grams == 453
    assert catalog.items[25493].worn_weight_grams is None
    assert sum(item.inventory_form_id is not None for item in catalog.items.values()) == 79


def test_legacy_catalog_omits_weight_and_checksum_binds_sidecar(make_content, tmp_path):
    content = make_content()
    root = Path("content/equipment")
    for name in ("catalog.json", "manifest.json"):
        shutil.copy(root / name, tmp_path / name)
    with pytest.raises(ValueError, match="missing equipment weights"):
        load_catalog(content, tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    legacy = {key: value for key, value in manifest.items() if key != "weights_sha256"}
    manifest_path.write_text(json.dumps(legacy))
    before = load_catalog(content, tmp_path)
    assert before.items[89].worn_weight_grams is None
    manifest_path.write_text(json.dumps(manifest))
    sidecar = tmp_path / "weights.json"
    shutil.copy(root / sidecar.name, sidecar)
    assert load_catalog(content, tmp_path).revision != before.revision
    sidecar.write_bytes(sidecar.read_bytes() + b" ")
    with pytest.raises(ValueError, match=r"weight.*checksum"):
        load_catalog(content, tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest.update(weights_sha256=sha256(sidecar.read_bytes()).hexdigest(), capture_sha256="other")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="capture"):
        load_catalog(content, tmp_path)
