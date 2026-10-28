"""Source-reviewed ordinary equipment batches retain exact identities and wear gates."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.bulk_review_gear import digest, physical
from tools.import_equipment import normalize
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import load_content
from tracker.domain.types import QuestStatus, SkillState, Source
from tracker.gear.catalog import load_catalog
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import RoleConfig

REVIEWS = Path("content/equipment/reviews")
FAMILIES = (
    "metal_platebodies",
    "metal_platelegs",
    "metal_full_helms",
    "metal_kiteshields",
    "conventional_scimitars",
    "standard_dragonhide",
)
NOW = datetime(2026, 10, 28, tzinfo=UTC)

# Independent exact-ID wear expectations, transcribed from captured item prose.
# A missing Defence requirement is distinct from an explicit level-one gate.
EXPECTED = {
    1067: ({}, ()),
    1069: ({"defence": 5}, ()),
    1071: ({"defence": 20}, ()),
    1073: ({"defence": 30}, ()),
    1075: ({"defence": 1}, ()),
    1079: ({"defence": 40}, ()),
    1115: ({}, ()),
    1117: ({}, ()),
    1119: ({"defence": 5}, ()),
    1121: ({"defence": 20}, ()),
    1123: ({"defence": 30}, ()),
    1127: ({"defence": 40}, ("dragon_slayer_i",)),
    1153: ({}, ()),
    1155: ({}, ()),
    1157: ({"defence": 5}, ()),
    1159: ({"defence": 20}, ()),
    1161: ({"defence": 30}, ()),
    1163: ({"defence": 40}, ()),
    1189: ({"defence": 1}, ()),
    1191: ({"defence": 1}, ()),
    1193: ({"defence": 5}, ()),
    1195: ({"defence": 10}, ()),
    1197: ({"defence": 20}, ()),
    1199: ({"defence": 30}, ()),
    1321: ({"attack": 1}, ()),
    1325: ({"attack": 5}, ()),
    1327: ({"attack": 10}, ()),
    1329: ({"attack": 20}, ()),
    1331: ({"attack": 30}, ()),
    6611: ({"attack": 10}, ("wanted",)),
    6617: ({"defence": 10}, ("wanted",)),
    6623: ({"defence": 10}, ("wanted",)),
    6625: ({"defence": 10}, ("wanted",)),
    6633: ({"defence": 10}, ("wanted",)),
    4087: ({"defence": 60}, ()),
    11335: ({"defence": 60}, ()),
    21892: ({"defence": 60}, ("dragon_slayer_i",)),
    21895: ({"defence": 60}, ()),
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


APPLIED = {
    path.stem: read(path)
    for path in sorted((REVIEWS / "applied").glob("*.json"))
    if path.stem.removesuffix("_extended") in FAMILIES
}
APPROVED = [
    pytest.param(family, entry, id=f"{family}-{entry['item_id']}")
    for family, manifest in APPLIED.items()
    for entry in manifest["entries"]
    if entry["decision"] == "approved"
]


@pytest.fixture(scope="module")
def live_catalog():
    content = load_content()
    return content, load_catalog(content)


@pytest.fixture(scope="module")
def physical_catalog():
    return {row["id"]: row for row in read(Path("content/equipment/catalog.json"))}


def snapshot(levels=None, quests=None):
    return AccountSnapshot(
        1,
        "bulk-expansion-synthetic",
        skills={
            key: SkillState(value, None, Source.MANUAL, NOW)
            for key, value in (levels or {}).items()
        },
        quests={} if quests is None else quests,
    )


@pytest.mark.parametrize("family", APPLIED)
def test_applied_artifacts_pin_sources_and_explicit_effect_approvals(family):
    definition = read(REVIEWS / "families" / f"{family}.json")
    source_path = Path(definition["source_file"])
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == definition["source_sha256"]
    manifest = APPLIED[family]
    assert manifest == read(REVIEWS / "approved" / f"{family}.json")
    proposal = read(REVIEWS / "proposed" / f"{family}.json")
    assert not proposal["approved_effect_clearance"]
    assert all(entry["decision"] == "pending" for entry in proposal["entries"])
    approved = [e for e in manifest["entries"] if e["decision"] == "approved"]
    assert manifest["approved_effect_clearance"] == [e["item_id"] for e in approved]
    assert len({e["item_id"] for e in manifest["entries"]}) == len(manifest["entries"])


@pytest.mark.parametrize("family,entry", APPROVED)
def test_exact_identity_source_statistics_and_ordinary_support(
    live_catalog, physical_catalog, family, entry
):
    content, catalog = live_catalog
    item_id = entry["item_id"]
    assert item_id in EXPECTED, "New exact ID needs an independent wear expectation"
    item = catalog.items[item_id]
    definition = read(REVIEWS / "families" / f"{family}.json")
    sources = read(Path(definition["source_file"]))
    source_row = next(row for row in sources["equipment_rows"] if row["id"] == item_id)
    assert digest(physical(normalize(source_row, bulk_reviews={}))) == digest(entry["physical"])
    assert physical(physical_catalog[item_id]) == entry["physical"]
    assert not normalize(source_row)["unsupported_effects"]
    page = sources["pages"][str(item_id)]
    text = page["wikitext"]
    assert hashlib.sha256(text.encode()).hexdigest() == page["sha256"]
    assert re.findall(r"^\|\s*id\s*=\s*(\d+)\s*$", text, re.M) == [str(item_id)]
    assert page["title"] == item.name == entry["physical"]["name"]
    assert page["url"] == (
        "https://oldschool.runescape.wiki/w/Special:PermanentLink/" + str(page["revision"])
    )
    assert {key: page[key] for key in ("url", "revision", "sha256")} in entry["sources"]
    claim = definition["items"][str(item_id)]
    assert all(quote in text for quote in claim["wear_evidence"])
    assert entry["classification"] == claim["classification"] == "ordinary"
    assert claim["mechanics"] == "ordinary"
    assert entry["review_reason"].strip()
    assert item.requirements_complete and not item.unsupported_effects
    assert item.tradeable is True
    authored = [value for value in content.items.values() if value.item_id == item_id]
    assert len(authored) == 1
    assert authored[0].variant_item_ids == ()
    assert authored[0].tier is None
    assert authored[0].price_mode == "live"


@pytest.mark.parametrize("family,entry", APPROVED)
def test_independent_wear_boundaries_and_quest_restrictions(live_catalog, family, entry):
    content, catalog = live_catalog
    item = catalog.items[entry["item_id"]]
    skills, quests = EXPECTED[item.id]
    completed = dict.fromkeys(quests, QuestStatus.COMPLETE)

    def status(levels, quest_values):
        return equipment_fact(snapshot(levels, quest_values), item, content, {}, NOW)["wear"][
            "status"
        ]

    assert status(skills, completed) == "satisfied"
    assert status({key: value + 1 for key, value in skills.items()}, completed) == "satisfied"
    for skill, floor in skills.items():
        if floor > 1:
            assert status({**skills, skill: floor - 1}, completed) == "unsatisfied"
        assert status({key: value for key, value in skills.items() if key != skill}, completed) == (
            "unknown"
        )
    for quest in quests:
        assert status(skills, {**completed, quest: QuestStatus.NOT_STARTED}) == "unsatisfied"
        assert status(skills, {key: value for key, value in completed.items() if key != quest}) == (
            "unknown"
        )
    unrelated = dict.fromkeys(
        (
            "dragon_slayer_i",
            "dragon_slayer_ii",
            "legends_quest",
            "wanted",
            "kings_ransom",
            "heroes_quest",
            "song_of_the_elves",
        ),
        QuestStatus.NOT_STARTED,
    )
    assert status(skills, {**unrelated, **completed}) == "satisfied"


@pytest.mark.parametrize("family,entry", APPROVED)
def test_ordinary_combat_compatibility(live_catalog, family, entry):
    _, catalog = live_catalog
    item = catalog.items[entry["item_id"]]
    if family == "standard_dragonhide":
        # A one-handed crossbow also permits independently reviewed hide shields.
        equipment = {"weapon": 9185, "ammunition": 9144, item.slot: item.id}
        style = "ranged"
    else:
        equipment = {"weapon": 1333, item.slot: item.id}
        style = "slash"
    result = evaluate_equipment(
        equipment,
        catalog.items,
        RoleConfig(id="ordinary", style=style),
        dict.fromkeys(("attack", "strength", "defence", "magic", "ranged"), 99),
    )
    assert result.supported, result.limitations
    assert result.dps > 0


@pytest.mark.parametrize("family", APPLIED)
def test_unapproved_forms_keep_independent_exclusions(live_catalog, family):
    _, catalog = live_catalog
    manifest = APPLIED[family]
    approved = {
        item_id
        for path in (REVIEWS / "applied").glob("*.json")
        for item_id in read(path)["approved_effect_clearance"]
    }
    for entry in manifest["entries"]:
        if entry["item_id"] not in approved:
            assert entry["decision"] != "approved"
            assert entry["overlay"] is None
            item = catalog.items[entry["item_id"]]
            assert item.unsupported_effects or not item.requirements_complete
