"""Normalize a reviewed, pinned Wiki equipment capture for offline use.

Usage: python tools/import_equipment.py --source capture.json --output content/equipment
The capture schema is the Wiki calculator's Bucket-derived equipment export. It
is data, not executable calculator code. No upcoming/manual source is fetched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import httpx

REVISION = "89c3e25b344aea90d0189746e4b5f73dde0f0383"
SOURCE = f"https://github.com/weirdgloop/osrs-dps-calc/blob/{REVISION}/cdn/json/equipment.json"
# This revision's manually appended file contains only Snail shell. Keep the
# exclusion pinned with the export rather than accidentally importing future gear.
MANUAL_IDS = {7800}

# Explicit ordinary-mechanics review. An unfamiliar item always remains inspectable
# but is not numerically ranked; adding an item requires effects review and tests.
REVIEWED = {
    1540,  # Anti-dragon shield: ordinary stats; dragonfire mitigation remains unscored.
    # Fixed Barrelchest anchor: ordinary attacks only; Sunder is not scored.
    # Exact wear/acquisition review: content/items/barrelchest_anchor.yaml.
    10887,
    # Iban Blast: fixed 25 base damage, five-tick casting, exact charged forms.
    # https://oldschool.runescape.wiki/w/Iban%27s_staff
    1409,
    12658,
    # Standard mystic elemental staves: ordinary Standard autocast, no damage
    # multiplier. Exact wear/acquisition sources: items/mystic_staves.yaml.
    1401,
    1403,
    1405,
    1407,
    # Exact high-impact review: docs/GEAR_HIGH_IMPACT_COVERAGE.md.
    7460,
    7459,
    7458,
    29280,
    29286,
    29289,
    2501,
    2495,
    6733,
    2577,
    # Phase 2 batch 1: each exact form independently reviewed, including the
    # Death Plateau wear gate on both boots. No approval for spiked boots.
    # Sources: docs/GEAR_CATALOG_COVERAGE_PHASE_2.md.
    33101,
    3105,
    23413,
    # Phase 2 batch 2: ordinary observed gloves, enchanted robes and tights.
    19994,
    21736,
    7398,
    7399,
    23249,
    # Phase 2 batch 3: purchasable hat and independently reviewed robe colours.
    7400,
    4101,
    4103,
    4111,
    4113,
    # Phase 1 exact ordinary forms; source revisions and field review are recorded
    # in docs/GEAR_CATALOG_COVERAGE_PHASE_1.md and the authored overlay comments.
    1077,
    1125,
    1165,
    1201,
    857,
    1017,
    2579,
    3753,
    3755,
    6809,
    10564,
    10589,
    21643,
    1323,
    1325,
    1329,
    1331,
    1333,
    4587,
    4151,
    22324,
    23997,
    1153,
    1157,
    1159,
    1161,
    1163,
    3751,
    10828,
    24271,
    26382,
    1115,
    1119,
    1121,
    1123,
    1127,
    10551,
    26384,
    1067,
    1069,
    1071,
    1073,
    1079,
    4087,
    4751,
    26386,
    1059,
    11126,
    7462,
    22981,
    1061,
    9006,
    4131,
    11840,
    13239,
    1019,
    13121,
    13122,
    6570,
    21295,
    1725,
    6585,
    19553,
    29801,
    13125,
    13126,
    13127,
    13128,
    6737,
    11773,
    28307,
    28316,
    12954,
    22322,
    # Exact wearable defender review: content/items/defenders.yaml.
    # Locked forms inherit this review through the catalog's equivalence map.
    8844,
    8845,
    8846,
    8847,
    8848,
    8849,
    8850,
    23230,
    19722,
    27550,
    27552,
    20226,
    841,
    843,
    849,
    853,
    861,
    12788,
    8880,
    9185,
    1167,
    1169,
    6326,
    3749,
    10382,
    27226,
    27235,
    1129,
    1133,
    1135,
    2499,
    2503,
    10378,
    27229,
    27238,
    1095,
    1097,
    1099,
    2493,
    2497,
    10380,
    27232,
    27241,
    1063,
    1065,
    26235,
    6328,
    19927,
    13237,
    10498,
    10499,
    22109,
    1731,
    1704,
    19547,
    25975,
    28310,
    22275,
    12610,
    11926,
    21000,
    882,
    884,
    886,
    888,
    890,
    892,
    21326,
    8882,
    9140,
    9141,
    9142,
    9143,
    9144,
    1381,
    1383,
    1385,
    1387,
    4675,
    579,
    13385,
    4089,
    4708,
    21018,
    577,
    13387,
    4091,
    4712,
    21021,
    1033,
    13389,
    4093,
    4714,
    21024,
    19544,
    4097,
    6920,
    13235,
    2412,
    21791,
    1727,
    12002,
    11770,
    28313,
    12612,
    11924,
    25985,
    27251,
    11832,
    11828,
}
PROFILES = {
    "Slash Sword": ("stab", "slash"),
    "Stab Sword": ("stab", "slash"),
    "Whip": ("slash",),
    "Blunt": ("crush",),
    "Staff": ("crush", "magic"),
    "Bow": ("ranged",),
    "Crossbow": ("ranged",),
    "Thrown": ("ranged",),
    "2h Sword": ("slash", "crush"),
    "Axe": ("slash", "crush"),
}
ARROW_LIMITS = {
    841: (882, 884),
    843: (882, 884, 886),
    849: (882, 884, 886, 888),
    853: (882, 884, 886, 888, 890),
    857: (882, 884, 886, 888, 890, 892),
    861: (882, 884, 886, 888, 890, 892, 21326),
    12788: (882, 884, 886, 888, 890, 892, 21326),
}


@lru_cache(maxsize=1)
def bulk_reviewed_rows() -> dict[int, str]:
    """Maintenance-time approvals only; never infer review from names/aliases."""
    reviewed = {}
    root = Path(__file__).resolve().parents[1] / "content/equipment/reviews/applied"
    for path in sorted(root.glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        approved = set(manifest["approved_effect_clearance"])
        for entry in manifest["entries"]:
            if entry["decision"] == "approved" and entry["item_id"] in approved:
                if entry["classification"] not in ("ordinary", "verified_variant"):
                    raise ValueError("Unsupported bulk review approval")
                payload = json.dumps(entry["physical"], sort_keys=True, separators=(",", ":"))
                fingerprint = hashlib.sha256(payload.encode()).hexdigest()
                if entry["item_id"] in reviewed and reviewed[entry["item_id"]] != fingerprint:
                    raise ValueError("Conflicting bulk review fingerprints")
                reviewed[entry["item_id"]] = fingerprint
    return reviewed


def normalize(row: dict, *, bulk_reviews: dict[int, str] | None = None) -> dict:
    item_id = int(row["id"])
    slot = "ammunition" if row["slot"] == "ammo" else row["slot"]
    supported = item_id in REVIEWED
    category = row["category"]
    ammo_for: tuple[str, ...] = ()
    if item_id in ARROW_LIMITS:
        ammo_for = tuple(f"arrow:{value}" for value in ARROW_LIMITS[item_id])
    elif item_id == 8880:
        ammo_for = ("bolt:8882",)
    elif item_id == 9185:
        ammo_for = tuple(f"bolt:{value}" for value in (9140, 9141, 9142, 9143, 9144))
    ammo_type = None
    if slot == "ammunition" and item_id in REVIEWED:
        ammo_type = f"{'arrow' if 'arrow' in row['name'].lower() else 'bolt'}:{item_id}"
    styles = PROFILES.get(category, ())
    profiles: list[tuple[str, str]] = []
    for style in styles:
        stances: tuple[str, ...]
        if style == "ranged":
            stances = ("accurate", "rapid", "longrange")
        elif category == "Slash Sword":
            stances = (
                ("controlled",) if style == "stab" else ("accurate", "aggressive", "defensive")
            )
        elif category == "Stab Sword":
            stances = (
                ("controlled",) if style == "slash" else ("accurate", "aggressive", "defensive")
            )
        elif category == "Whip":
            stances = ("accurate", "controlled", "defensive")
        else:
            stances = ("accurate", "aggressive", "defensive")
        profiles.extend((style, stance) for stance in stances)
    # Exact fixed form review. Do not bless broken/Bounty Hunter forms or
    # infer all Spiked weapons' compatibility from this one review.
    # https://oldschool.runescape.wiki/w/Barrelchest_anchor#Combat_stats
    if item_id == 10887:
        styles = ("crush", "stab")
        profiles = [
            ("crush", "accurate"),
            ("crush", "aggressive"),
            ("stab", "controlled"),
            ("crush", "defensive"),
        ]
    result = {
        "id": item_id,
        "name": row["name"],
        "slot": slot,
        "bonuses": {
            **row["offensive"],
            "melee_strength": row["bonuses"]["str"],
            "ranged_strength": row["bonuses"]["ranged_str"],
            # Calculator exports integer tenths of a percent, not percentages.
            "magic_damage": row["bonuses"]["magic_str"] / 10,
            **{"defence_" + key: value for key, value in row["defensive"].items()},
            "prayer": row["bonuses"]["prayer"],
        },
        "attack_speed": max(1, row["speed"]),
        "attack_styles": styles,
        "attack_profiles": profiles,
        "two_handed": row["isTwoHanded"],
        "ammo_type": ammo_type,
        "ammo_for": ammo_for,
        "stackable": slot == "ammunition" or category == "Thrown",
        "unsupported_effects": [] if supported else ["Offensive effects have not been validated."],
    }
    reviews = bulk_reviewed_rows() if bulk_reviews is None else bulk_reviews
    if item_id in reviews:
        physical = {k: v for k, v in result.items() if k != "unsupported_effects"}
        payload = json.dumps(physical, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(payload.encode()).hexdigest() != reviews[item_id]:
            raise ValueError(f"Bulk-reviewed physical item changed: {item_id}")
        result = {**result, "unsupported_effects": []}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source", type=Path)
    inputs.add_argument("--bucket", action="store_true", help="Capture directly from the Wiki")
    parser.add_argument("--output", type=Path, default=Path("content/equipment"))
    args = parser.parse_args()
    source = json.dumps(fetch_bucket()).encode() if args.bucket else args.source.read_bytes()
    rows = json.loads(source)
    by_id: dict[int, dict] = {}
    for row in rows:
        if row["id"] in MANUAL_IDS:
            continue
        if row["slot"] not in {
            "weapon",
            "shield",
            "head",
            "body",
            "legs",
            "hands",
            "feet",
            "cape",
            "neck",
            "ring",
            "ammo",
        }:
            continue
        normalized = normalize(row)
        if normalized["id"] in by_id and normalized != by_id[normalized["id"]]:
            # Same physical ID with multiple statistical contexts cannot be
            # confidently imported as one ordinary equipment definition.
            normalized["unsupported_effects"] = ["Ambiguous source equipment variant."]
        by_id[normalized["id"]] = normalized
    args.output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(list(by_id.values()), ensure_ascii=False, separators=(",", ":")) + "\n"
    (args.output / "catalog.json").write_bytes(payload.encode("utf-8"))
    manifest = {
        "schema_version": 1,
        "source": "https://oldschool.runescape.wiki/api.php?action=bucket"
        if args.bucket
        else SOURCE,
        "revision": None if args.bucket else REVISION,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "capture_sha256": hashlib.sha256(source).hexdigest(),
        "catalog_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "attribution": (
            "Old School RuneScape Wiki contributors; Weird Gloop calculator contributors"
        ),
        "source_license": "GPL-3.0 calculator export; Wiki-derived content CC BY-NC-SA 3.0",
        "license_urls": [
            "https://github.com/weirdgloop/osrs-dps-calc/blob/main/LICENSE",
            "https://meta.weirdgloop.org/w/Licensing",
        ],
        "notes": "Statistics only; no images or calculator implementation copied. "
        "Unreviewed effects and absent requirement overlays fail closed.",
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def fetch_bucket() -> list[dict]:
    """Explicit maintenance-time capture; no network dependency at runtime.

    Fail on API/schema errors rather than replacing the catalog with partial data.
    Only infobox-backed rows are queried; no manually supplied upcoming items.
    """
    bonus_fields = {
        "stab": "stab",
        "slash": "slash",
        "crush": "crush",
        "magic": "magic",
        "ranged": "range",
    }
    names = [
        "page_name",
        "item_id",
        "infobox_bonuses.equipment_slot",
        "infobox_bonuses.weapon_attack_speed",
        "infobox_bonuses.combat_style",
        "infobox_bonuses.strength_bonus",
        "infobox_bonuses.ranged_strength_bonus",
        "infobox_bonuses.magic_damage_bonus",
        "infobox_bonuses.prayer_bonus",
    ]
    names.extend(
        f"infobox_bonuses.{value}_{kind}_bonus"
        for value in bonus_fields.values()
        for kind in ("attack", "defence")
    )
    captured = []
    with httpx.Client(
        timeout=30,
        headers={
            "User-Agent": "osrs-account-companion catalog-import "
            "(https://github.com/cabeard21/osrs_recommender)"
        },
    ) as client:
        for offset in range(0, 100000, 500):
            query = (
                "bucket('infobox_item').select(" + ",".join(repr(n) for n in names) + ")"
                ".where('infobox_bonuses.equipment_slot', '!=', bucket.Null())"
                ".where('item_id', '!=', bucket.Null())"
                ".join('infobox_bonuses', 'infobox_bonuses.page_name_sub',"
                " 'infobox_item.page_name_sub').orderBy('page_name_sub', 'asc')"
                f".limit(500).offset({offset}).run()"
            )
            response = client.get(
                "https://oldschool.runescape.wiki/api.php",
                params={"action": "bucket", "format": "json", "query": query},
            )
            response.raise_for_status()
            rows = response.json()["bucket"]
            for row in rows:
                slot = row["infobox_bonuses.equipment_slot"]
                captured.append(
                    {
                        "id": int(row["item_id"][0]),
                        "name": row["page_name"],
                        "slot": "weapon" if slot == "2h" else slot,
                        "speed": row.get("infobox_bonuses.weapon_attack_speed") or 0,
                        "category": row.get("infobox_bonuses.combat_style") or "",
                        "isTwoHanded": slot == "2h",
                        "bonuses": {
                            "str": row.get("infobox_bonuses.strength_bonus") or 0,
                            "ranged_str": row.get("infobox_bonuses.ranged_strength_bonus") or 0,
                            "magic_str": 10 * (row.get("infobox_bonuses.magic_damage_bonus") or 0),
                            "prayer": row.get("infobox_bonuses.prayer_bonus") or 0,
                        },
                        **{
                            kind: {
                                key: row.get(f"infobox_bonuses.{value}_{suffix}_bonus") or 0
                                for key, value in bonus_fields.items()
                            }
                            for kind, suffix in (("offensive", "attack"), ("defensive", "defence"))
                        },
                    }
                )
            if len(rows) < 500:
                return captured
    raise ValueError("Wiki equipment capture exceeded safety limit")


if __name__ == "__main__":
    main()
