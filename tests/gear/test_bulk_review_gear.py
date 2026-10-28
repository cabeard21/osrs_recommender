"""Bulk review CLI lifecycle: exact identities, fail-closed approval, and wear facts."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.bulk_review_gear import apply, main, propose, source_entry, validate, wear_requirements
from tools.import_equipment import normalize
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.catalog import load_catalog
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

FAMILY = Path("content/equipment/reviews/families/metal_chainbodies.json")
RULES = {1101: 1, 1103: 1, 1105: 5, 1107: 10, 1109: 20, 1111: 30, 1113: 40}
UNREVIEWED = ["Offensive effects have not been validated."]
NOW = datetime(2026, 10, 28, tzinfo=UTC)


@pytest.mark.parametrize(
    "change",
    (
        "checksum",
        "identity",
        "title",
        "revision_url",
        "statistics",
        "acquisition",
        "quote",
        "floor",
        "reason",
        "classification",
        "variant",
    ),
)
def test_source_review_rejects_inconsistent_exact_id_evidence(change):
    family = json.loads(FAMILY.read_text(encoding="utf-8"))
    sources = json.loads(Path(family["source_file"]).read_text(encoding="utf-8"))
    row = rows(Path("."))[1113]
    page = sources["pages"]["1113"]
    claim = family["items"]["1113"]
    if change == "checksum":
        page["sha256"] = "0" * 64
    elif change == "identity":
        row = {**row, "name": "Rune chainbody (different)"}
    elif change == "title":
        page["title"] = "Wrong title"
    elif change == "revision_url":
        page["url"] = "https://oldschool.runescape.wiki/w/Rune_chainbody"
    elif change == "statistics":
        row = {**row, "bonuses": {**row["bonuses"], "melee_strength": 100}}
    elif change == "acquisition":
        claim["acquisition"] = "untradeable"
    elif change == "quote":
        claim["wear_evidence"] = ["Unsubstantiated wear claim"]
    elif change == "floor":
        claim["requires"] = {"skill": {"defence": 1}}
    elif change == "reason":
        claim["review_reason"] = ""
    elif change == "classification":
        claim["classification"] = "approved_by_tier"
    else:
        claim["classification"] = "verified_variant"
        claim["variant_of"] = 1101
    with pytest.raises(ValueError):
        source_entry(row, family, sources)


def test_conservative_wear_grammar_handles_quests_and_rejects_ambiguity():
    family = {
        "wear_patterns": [{"skill": "defence", "pattern": r"requires (?P<level>\d+) Defence"}],
        "quest_patterns": [
            {"quest": "dragon_slayer_i", "pattern": r"must complete Dragon Slayer I"}
        ],
    }
    assert wear_requirements(
        family, ["requires 40 [[Defence]]; must complete Dragon Slayer I"]
    ) == {"all_of": [{"skill": {"defence": 40}}, {"quest": "dragon_slayer_i"}]}
    with pytest.raises(ValueError, match="Ambiguous"):
        wear_requirements(family, ["requires 40 Defence; requires 1 Defence"])
    with pytest.raises(ValueError, match="Missing or ambiguous"):
        wear_requirements(family, ["Smithing level 99 to make"])
    assert (
        wear_requirements({"ungated_pattern": "no wear requirements"}, ["no wear requirements"])
        is None
    )


def write_catalog(root, rows):
    payload = (json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    (root / "content/equipment/catalog.json").write_bytes(payload)
    path = root / "content/equipment/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps({**manifest, "catalog_sha256": hashlib.sha256(payload).hexdigest()}, indent=2)
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def root(tmp_path):
    shutil.copytree("content", tmp_path / "content")
    for relative in (
        "content/items/bulk_metal_chainbodies.yaml",
        "content/equipment/reviews/applied/metal_chainbodies.json",
    ):
        (tmp_path / relative).unlink(missing_ok=True)
    path = tmp_path / "content/equipment/catalog.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    write_catalog(
        tmp_path,
        [{**row, "unsupported_effects": UNREVIEWED} if row["id"] in RULES else row for row in rows],
    )
    return tmp_path


def approved(proposal, ids=tuple(RULES)):
    result = copy.deepcopy(proposal)
    result["entries"] = [
        {**entry, "decision": "approved", "review_reason": "Exact Wiki ID and ordinary stats read."}
        if entry["item_id"] in ids
        else entry
        for entry in result["entries"]
    ]
    result["approved_effect_clearance"] = sorted(ids)
    return result


def rows(root):
    return {
        row["id"]: row
        for row in json.loads((root / "content/equipment/catalog.json").read_text(encoding="utf-8"))
    }


def test_propose_is_deterministic_and_does_not_enable_items(root):
    before = rows(root)
    proposal = propose(root, root / FAMILY)
    assert proposal == propose(root, root / FAMILY)
    assert proposal["schema_version"] == 1
    ordinary = {e["item_id"] for e in proposal["entries"] if e["classification"] == "ordinary"}
    assert ordinary == set(RULES)
    assert set(proposal["proposed_effect_clearance"]) == set(RULES)
    assert proposal["approved_effect_clearance"] == []
    assert all(e["decision"] == "pending" for e in proposal["entries"])
    assert all(e["sources"] and e["reasons"] for e in proposal["entries"] if e["item_id"] in RULES)
    assert rows(root) == before
    catalog = load_catalog(load_content(root / "content"), root / "content/equipment")
    assert all(catalog.items[i].unsupported_effects for i in RULES)
    assert validate(root, root / FAMILY, proposal) == {}
    apply(root, root / FAMILY, proposal)
    assert rows(root) == before


def test_cli_propose_review_validate_apply_and_coverage(root, monkeypatch, capsys):
    manifest_path = root / "review.json"
    report_path = root / "report.md"

    def run(command):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "bulk_review_gear",
                command,
                "--root",
                str(root),
                "--family",
                str(root / FAMILY),
                "--manifest",
                str(manifest_path),
                "--report",
                str(report_path),
            ],
        )
        main()
        return capsys.readouterr().out

    assert "propose:" in run("propose")
    proposal = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "Discovery is not approval" in report_path.read_text(encoding="utf-8")
    manifest_path.write_text(json.dumps(approved(proposal)), encoding="utf-8")
    assert "validate:" in run("validate")
    assert "apply:" in run("apply")
    assert json.loads(run("coverage"))["physical_ids"] == len(rows(root))
    manifest_path.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        run("validate")
    assert failure.value.code == 1
    assert "Bulk review rejected:" in capsys.readouterr().err


def test_apply_only_approved_exact_ids_and_repeat_is_byte_identical(root):
    before = rows(root)
    manifest = approved(propose(root, root / FAMILY), (1101, 1113))
    outputs = validate(root, root / FAMILY, manifest)
    assert outputs
    assert rows(root) == before
    apply(root, root / FAMILY, manifest)
    after = rows(root)
    assert set(after) == set(before)
    for item_id, row in before.items():
        assert after[item_id] == (
            {**row, "unsupported_effects": []} if item_id in (1101, 1113) else row
        )
    content = load_content(root / "content")
    catalog = load_catalog(content, root / "content/equipment")
    assert catalog.items[1101].requirements_complete
    assert catalog.items[1113].requirements_complete
    assert not catalog.items[1103].requirements_complete
    snapshot = {
        str(path): path.read_bytes() for path in (root / "content").rglob("*") if path.is_file()
    }
    apply(root, root / FAMILY, manifest)
    assert snapshot == {
        str(path): path.read_bytes() for path in (root / "content").rglob("*") if path.is_file()
    }
    remaining = {entry["item_id"] for entry in propose(root, root / FAMILY)["entries"]}
    assert not remaining.intersection((1101, 1113))
    included = {entry["item_id"] for entry in propose(root, root / FAMILY, True)["entries"]}
    assert {1101, 1113} <= included


@pytest.mark.parametrize("collision", ("generated_id", "physical_id"))
def test_existing_authored_content_cannot_be_overwritten_or_combined(root, collision):
    existing = {
        "id": "bulk_metal_chainbodies_1113" if collision == "generated_id" else "other_rune_gate",
        "name": "Existing content must be preserved",
        "item_id": 99999 if collision == "generated_id" else 1113,
        "slot": "body",
        "requires": {"skill": {"defence": 99}},
    }
    path = root / "content/items/test_existing.yaml"
    path.write_text(json.dumps([existing]), encoding="utf-8")
    manifest = approved(propose(root, root / FAMILY))
    with pytest.raises(ValueError, match=r"collides|Conflicting"):
        apply(root, root / FAMILY, manifest)
    assert json.loads(path.read_text(encoding="utf-8")) == [existing]


def test_failed_replacement_restores_all_original_files(root, monkeypatch):
    manifest = approved(propose(root, root / FAMILY))
    before = {path: path.read_bytes() for path in (root / "content").rglob("*") if path.is_file()}
    replace = Path.replace

    def fail_manifest(path, target):
        if Path(target) == root / "content/equipment/manifest.json":
            raise OSError("simulated replacement failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_manifest)
    with pytest.raises(OSError, match="simulated replacement failure"):
        apply(root, root / FAMILY, manifest)
    assert before == {
        path: path.read_bytes() for path in (root / "content").rglob("*") if path.is_file()
    }


@pytest.mark.parametrize(
    "attack",
    (
        "physical",
        "overlay",
        "source",
        "duplicate",
        "effect_only",
        "metadata_only",
        "reason",
        "alias",
        "quest",
        "skill",
    ),
)
def test_manifest_tampering_rejected_without_writes(root, attack):
    manifest = approved(propose(root, root / FAMILY))
    index = next(i for i, entry in enumerate(manifest["entries"]) if entry["item_id"] == 1113)
    entry = manifest["entries"][index]
    if attack == "physical":
        entry["physical"]["bonuses"]["melee_strength"] = 99
    elif attack == "overlay":
        entry["overlay"]["requires"] = None
    elif attack == "source":
        entry["sources"] = []
    elif attack == "duplicate":
        manifest["entries"].append(copy.deepcopy(entry))
    elif attack == "effect_only":
        entry["decision"] = "pending"
    elif attack == "metadata_only":
        manifest["approved_effect_clearance"].remove(1113)
    elif attack == "alias":
        entry["overlay"]["variant_item_ids"] = [3140]
    elif attack == "quest":
        entry["overlay"]["requires"] = {"quest": "unverified_quest"}
    elif attack == "skill":
        entry["overlay"]["requires"] = {"skill": {"defence": 100}}
    else:
        entry["review_reason"] = ""
    before = rows(root)
    with pytest.raises(ValueError):
        apply(root, root / FAMILY, manifest)
    assert rows(root) == before


def test_changed_family_or_physical_capture_requires_new_proposal(root):
    manifest = approved(propose(root, root / FAMILY))
    family = root / FAMILY
    original = family.read_bytes()
    changed = {**json.loads(original), "test_changed_source_policy": True}
    family.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError):
        validate(root, family, manifest)
    family.write_bytes(original)
    current = rows(root)
    current[1113] = {**current[1113], "attack_speed": current[1113]["attack_speed"] + 1}
    write_catalog(root, list(current.values()))
    with pytest.raises(ValueError):
        validate(root, family, manifest)


def test_modified_source_capture_is_rejected(root):
    manifest = approved(propose(root, root / FAMILY))
    family = json.loads((root / FAMILY).read_text(encoding="utf-8"))
    source = root / family["source_file"]
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        validate(root, root / FAMILY, manifest)


def test_regeneration_requires_same_exact_physical_item(root):
    manifest = approved(propose(root, root / FAMILY), (1113,))
    entry = next(e for e in manifest["entries"] if e["item_id"] == 1113)
    family = json.loads((root / FAMILY).read_text(encoding="utf-8"))
    source = json.loads((root / family["source_file"]).read_text(encoding="utf-8"))
    raw = next(row for row in source["equipment_rows"] if row["id"] == 1113)
    fingerprint = hashlib.sha256(
        json.dumps(entry["physical"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert normalize(raw, bulk_reviews={})["unsupported_effects"] == UNREVIEWED
    assert normalize(raw, bulk_reviews={1113: fingerprint})["unsupported_effects"] == []
    altered = {**raw, "bonuses": {**raw["bonuses"], "str": 100}}
    with pytest.raises(ValueError, match="physical item changed"):
        normalize(altered, bulk_reviews={1113: fingerprint})
    other_id = {**raw, "id": 3140}
    assert (
        normalize(other_id, bulk_reviews={1113: fingerprint})["unsupported_effects"] == UNREVIEWED
    )


def test_manual_exceptions_and_non_generic_effects_cannot_be_cleared(root):
    manifest = propose(root, root / FAMILY)
    exception = next(
        e for e in manifest["entries"] if e["classification"] == "manual_review_exception"
    )
    bad = approved(manifest, (exception["item_id"],))
    with pytest.raises(ValueError):
        validate(root, root / FAMILY, bad)
    current = rows(root)
    current[1113] = {
        **current[1113],
        "unsupported_effects": ["Ambiguous source equipment variant."],
    }
    write_catalog(root, list(current.values()))
    with pytest.raises(ValueError):
        validate(root, root / FAMILY, approved(manifest))


def account(defence, *, owned=(), quests=None):
    levels = {"attack": 70, "strength": 70, "defence": defence, "ranged": 70, "magic": 70}
    return AccountSnapshot(
        1,
        "bulk-synthetic",
        skills={
            key: SkillState(value, None, Source.MANUAL, NOW)
            for key, value in levels.items()
            if value is not None
        },
        quests={} if quests is None else quests,
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in owned
        },
    )


@pytest.mark.parametrize("item_id,defence", RULES.items())
def test_applied_wear_boundaries_quest_use_and_ordinary_combat(root, item_id, defence):
    apply(root, root / FAMILY, approved(propose(root, root / FAMILY)))
    content = load_content(root / "content")
    catalog = load_catalog(content, root / "content/equipment")
    item = catalog.items[item_id]
    assert item.requirements_complete and not item.unsupported_effects
    assert item.tradeable is True
    overlay = [entry for entry in content.items.values() if entry.item_id == item_id]
    assert len(overlay) == 1
    assert overlay[0].variant_item_ids == ()
    assert overlay[0].tier is None
    for level in (defence, defence + 1):
        assert (
            equipment_fact(account(level), item, content, {}, NOW)["wear"]["status"] == "satisfied"
        )
    if defence > 1:
        assert (
            equipment_fact(account(defence - 1), item, content, {}, NOW)["wear"]["status"]
            == "unsatisfied"
        )
        assert equipment_fact(account(None), item, content, {}, NOW)["wear"]["status"] == "unknown"
    incomplete_quests = dict.fromkeys(
        ("dragon_slayer_i", "black_knights_fortress", "kings_ransom", "song_of_the_elves"),
        QuestStatus.NOT_STARTED,
    )
    assert (
        equipment_fact(account(40, quests=incomplete_quests), item, content, {}, NOW)["wear"][
            "status"
        ]
        == "satisfied"
    )
    equipment = {"weapon": 1333, "body": item_id}
    role = RoleConfig(id="one", style="slash")
    levels = {"attack": 70, "strength": 70, "defence": 70, "ranged": 70, "magic": 70}
    exact = evaluate_equipment(equipment, catalog.items, role, levels)
    assert exact.supported and exact.dps > 0
    request = OptimizationRequest(roles=(role,), mode="owned", locks=equipment, max_swaps=0)
    answer = optimize(account(70, owned=equipment.values()), request, catalog, content, {}, NOW)
    assert answer["search"]["quality"] == "best_found"
    assert answer["selected_solution"]["loadouts"]["one"]["equipment"] == equipment


def test_related_forms_keep_independent_metadata_ownership_and_effects(root):
    apply(root, root / FAMILY, approved(propose(root, root / FAMILY)))
    content = load_content(root / "content")
    catalog = load_catalog(content, root / "content/equipment")
    # Dragon, ornamented dragon, white and gilded rows receive no prefix/tier approval.
    for item_id in (3140, 12414, 28065, 6615, 20149):
        assert catalog.items[item_id].unsupported_effects
        assert not catalog.items[item_id].requirements_complete
    assert (
        equipment_fact(account(70, owned=(1101,)), catalog.items[1113], content, {}, NOW)[
            "ownership"
        ]["status"]
        == "unknown"
    )
