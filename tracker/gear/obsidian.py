"""Exact obsidian physical forms reviewed for ordinary base statistics only.

Wear/acquisition: content/items/obsidian.yaml. Stats: pinned catalog manifest.
https://oldschool.runescape.wiki/w/Obsidian_equipment
https://oldschool.runescape.wiki/w/Toktz-mej-tal#Combat_stats
Armour and Berserker necklace multipliers are deliberately not applied.
"""

import json
from types import MappingProxyType
from typing import Any

FORMS = MappingProxyType(
    {
        21298: ("Obsidian helmet", "head"),
        21301: ("Obsidian platebody", "body"),
        21304: ("Obsidian platelegs", "legs"),
        6568: ("Obsidian cape", "cape"),
        20050: ("Obsidian cape (r)", "cape"),
        6524: ("Toktz-ket-xil", "shield"),
        6523: ("Toktz-xil-ak", "weapon"),
        6525: ("Toktz-xil-ek", "weapon"),
        6526: ("Toktz-mej-tal", "weapon"),
        6522: ("Toktz-xil-ul", "weapon"),
        6527: ("Tzhaar-ket-em", "weapon"),
        6528: ("Tzhaar-ket-om", "weapon"),
        23235: ("Tzhaar-ket-om (t)", "weapon"),
    }
)
OMISSION = (
    "Obsidian equipment uses base stats only; obsidian armour set and Berserker "
    "necklace bonuses are not applied."
)
STAFF_PROFILES = (
    ("crush", "accurate"),
    ("crush", "aggressive"),
    ("crush", "defensive"),
    ("magic", "accurate"),
    ("magic", "defensive"),
)
REVISION = json.dumps(
    ["obsidian-base-stats-v1", dict(FORMS), OMISSION, STAFF_PROFILES], sort_keys=True
).encode()


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    """Approve exact forms without discarding unrelated blocking mechanics."""
    form = FORMS.get(row["id"])
    if form is None:
        return row
    if (row["name"], row["slot"]) != form:
        raise ValueError(f"Reviewed obsidian physical form changed: {row['id']}")
    return {
        **row,
        "unsupported_effects": [
            effect
            for effect in row["unsupported_effects"]
            if effect != "Offensive effects have not been validated."
        ],
        "omitted_set_effects": (OMISSION,)
        if row["slot"] in {"head", "body", "legs", "weapon"}
        else (),
        **({"attack_profiles": STAFF_PROFILES} if row["id"] == 6526 else {}),
    }
