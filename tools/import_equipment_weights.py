"""Build the offline Gear weight sidecar from the same pinned physical and Reboxed captures.

python -m tools.import_equipment_weights --capture .tmp/gear-reference/cdn/json/equipment.json \
    --items .tmp/osrsreboxed/items-complete.json

The command downloads the two pinned RuneLite mapping files unless local copies are supplied.
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import httpx

RUNELITE_REVISION = "c11e54bb0588fe6e5d46ac49149409dc9c8abd02"
RUNELITE_BASE = f"https://raw.githubusercontent.com/runelite/runelite/{RUNELITE_REVISION}/"
MANAGER = "runelite-client/src/main/java/net/runelite/client/game/ItemManager.java"
GAMEVAL = "runelite-api/src/main/java/net/runelite/api/gameval/ItemID.java"
RUNELITE_HASHES = {
    MANAGER: "fd8bdf01b7a434f937ba3a250c6844239fe7d5ec03915e47125eb305d2907689",
    GAMEVAL: "1a8a6cda1ac152b3aabb7d20d0fb5fd1cb539c7f64df9516c7502ffffcbbfe70",
}


def parse_form_pairs(manager: str, gameval: str) -> dict[int, int]:
    """Restrict symbols to actual item IDs (the file also contains nested noted/placeholder IDs)."""
    section = manager.partition("WORN_ITEMS = ")[2].partition("build()")[0]
    symbols = dict(re.findall(r"^\tpublic static final int (\w+) = (\d+);", gameval, re.M))
    names = re.findall(r"put\(ItemID\.(\w+), ItemID\.(\w+)\)", section)
    pairs = {int(symbols[worn]): int(symbols[bag]) for worn, bag in names}
    if not pairs or len(pairs) != len(names) or len(set(pairs.values())) != len(pairs):
        raise ValueError("Missing or ambiguous RuneLite worn form mapping")
    return pairs


def grams(value: object) -> int:
    if type(value) not in (int, float, Decimal):
        raise ValueError(f"Invalid item weight: {value!r}")
    number = Decimal(str(value)) * 1000
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"Invalid gram precision for item weight: {value!r}")
    return int(number)


def build_weights(ids, capture, items, pairs):
    """Ordinary forms use the equipment capture, switches use their actual inventory form."""
    configured = {}
    for row in capture:
        item_id = row["id"]
        if item_id not in ids:
            continue
        value = grams(row.get("weight"))
        if item_id in configured and configured[item_id] != value:
            raise ValueError(f"Conflicting physical weights for {item_id}")
        configured[item_id] = value
    if ids != configured.keys():
        raise ValueError("Equipment capture missing a catalog weight")
    reverse = {inventory: worn for worn, inventory in pairs.items()}
    worn_grams, inventory_forms = {}, {}
    for item_id in sorted(ids):
        worn_id = reverse.get(item_id, item_id)
        if worn_id not in configured:
            raise ValueError(f"Missing worn weight for inventory form {item_id}")
        weight = configured[worn_id]
        if weight < 0 and worn_id not in pairs:
            raise ValueError(f"Missing reviewed inventory form for {worn_id}")
        item = items.get(str(worn_id))
        if item is None:
            # Reboxed omits five beta armours from this physical capture.
            worn_grams[item_id] = None
            continue
        if item.get("id") != worn_id or type(item.get("stackable")) is not bool:
            raise ValueError(f"Invalid physical stackability for {worn_id}")
        worn_grams[item_id] = 0 if item["stackable"] else weight
        if item_id not in pairs:
            continue
        inventory_id = pairs[item_id]
        inventory = items.get(str(inventory_id), {})
        if inventory.get("id") != inventory_id or inventory.get("stackable") is not False:
            raise ValueError(f"Invalid inventory form for {item_id}")
        inventory_forms[item_id] = {"id": inventory_id, "grams": grams(inventory.get("weight"))}
    return {"worn_grams": worn_grams, "inventory_forms": inventory_forms}


def verified(data: bytes, digest: str, description: str) -> bytes:
    if sha256(data).hexdigest() != digest:
        raise ValueError(f"{description} checksum mismatch")
    return data


def runelite_source(source: str, local: Path | None) -> str:
    if local is None:
        response = httpx.get(RUNELITE_BASE + source, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
        data = response.content
    else:
        data = local.read_bytes()
    return verified(data, RUNELITE_HASHES[source], source).decode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("content/equipment"))
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--item-manager", type=Path)
    parser.add_argument("--gameval", type=Path)
    args = parser.parse_args()
    manifest_path = args.root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    reboxed = json.loads((args.root / "requirements.json").read_bytes())["source"]
    capture = verified(args.capture.read_bytes(), manifest["capture_sha256"], "equipment capture")
    items = verified(args.items.read_bytes(), reboxed["sha256"], "Reboxed items")
    physical = verified(
        (args.root / "catalog.json").read_bytes(), manifest["catalog_sha256"], "equipment catalog"
    )
    pairs = parse_form_pairs(
        runelite_source(MANAGER, args.item_manager), runelite_source(GAMEVAL, args.gameval)
    )
    weights = build_weights(
        {r["id"] for r in json.loads(physical)},
        json.loads(capture, parse_float=Decimal),
        json.loads(items, parse_float=Decimal),
        pairs,
    )
    document = {
        "schema_version": 1,
        "provenance": {
            "capture_sha256": manifest["capture_sha256"],
            "equipment_source": manifest["source"],
            "stackability_inventory_source": reboxed,
            "runelite_sources": {RUNELITE_BASE + k: v for k, v in RUNELITE_HASHES.items()},
            "runelite_license": "BSD-2-Clause",
            "weight_rules": "https://oldschool.runescape.wiki/w/Weight",
        },
        **weights,
    }
    payload = (json.dumps(document, indent=2) + "\n").encode()
    (args.root / "weights.json").write_bytes(payload)
    manifest_path.write_text(
        json.dumps({**manifest, "weights_sha256": sha256(payload).hexdigest()}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
