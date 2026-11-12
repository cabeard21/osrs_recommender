"""Exact ordinary crossbow/enchanted-bolt reviews, independent of raw imports.

Compatibility: weirdgloop/osrs-dps-calc src/lib/Equipment.ts at
880ab3f324ebea2644681d835448ab9d45c04f5c. Wear gates refer to using the
equipment, never the Magic/Fletching requirements for making ammunition.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any

# Physical ID: name, effect, minimum Ranged. Dragon forms retain their own IDs.
BOLTS = MappingProxyType(
    {
        9236: ("Opal bolts (e)", "opal", 1),
        9238: ("Pearl bolts (e)", "pearl", 26),
        9242: ("Ruby bolts (e)", "ruby", 46),
        9243: ("Diamond bolts (e)", "diamond", 46),
        9244: ("Dragonstone bolts (e)", "dragonstone", 61),
        9245: ("Onyx bolts (e)", "onyx", 61),
        21932: ("Opal dragon bolts (e)", "opal", 64),
        21936: ("Pearl dragon bolts (e)", "pearl", 64),
        21944: ("Ruby dragon bolts (e)", "ruby", 64),
        21946: ("Diamond dragon bolts (e)", "diamond", 64),
        21948: ("Dragonstone dragon bolts (e)", "dragonstone", 64),
        21950: ("Onyx dragon bolts (e)", "onyx", 64),
    }
)
_OPAL = (9236,)
_PEARL = (*_OPAL, 9238)
_ADAMANT = (*_PEARL, 9242, 9243)
_RUNE = (*_ADAMANT, 9244, 9245)
_DRAGON = tuple(BOLTS)
_METAL = (877, 9139, 9140, 9141, 9142, 9143, 9144, 21905)
# ID: exact name, wear level, compatible ordinary metal bolts, enchanted IDs.
CROSSBOWS = MappingProxyType(
    {
        837: ("Crossbow", 1, _METAL[:1], _OPAL),
        767: ("Phoenix crossbow", 1, _METAL[:1], _OPAL),
        9174: ("Bronze crossbow", 1, _METAL[:1], _OPAL),
        9176: ("Blurite crossbow", 16, _METAL[:2], _OPAL),
        9177: ("Iron crossbow", 26, _METAL[:3], _PEARL),
        9179: ("Steel crossbow", 31, _METAL[:4], _PEARL),
        9181: ("Mithril crossbow", 36, _METAL[:5], _PEARL),
        9183: ("Adamant crossbow", 46, _METAL[:6], _ADAMANT),
        9185: ("Rune crossbow", 61, _METAL[:7], _RUNE),
        8880: ("Dorgeshuun crossbow", 28, (*_METAL[:3], 8882), _OPAL),
        21902: ("Dragon crossbow", 64, _METAL, _DRAGON),
        11785: ("Armadyl crossbow", 70, _METAL, _DRAGON),
        26374: ("Zaryte crossbow", 80, _METAL, _DRAGON),
    }
)
REQUIREMENTS = MappingProxyType(
    {
        **{item_id: row[2] for item_id, row in BOLTS.items()},
        **{item_id: row[1] for item_id, row in CROSSBOWS.items()},
    }
)
TRADEABLE = frozenset(REQUIREMENTS) - {9176}
REVISION = json.dumps(
    ["enchanted-bolt-catalog-v1", dict(BOLTS), dict(CROSSBOWS), sorted(TRADEABLE)],
    sort_keys=True,
).encode()


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    """Return reviewed exact forms without erasing unrelated explicit blockers."""
    bolt = BOLTS.get(row["id"])
    crossbow = CROSSBOWS.get(row["id"])
    if bolt is None and crossbow is None:
        return row
    if bolt is not None:
        expected_name, expected_slot = bolt[0], "ammunition"
    else:
        assert crossbow is not None
        expected_name, expected_slot = crossbow[0], "weapon"
    if (row["name"], row["slot"]) != (expected_name, expected_slot):
        raise ValueError(f"Reviewed bolt/crossbow physical form changed: {row['id']}")
    reviewed = {
        **row,
        "unsupported_effects": [
            effect
            for effect in row["unsupported_effects"]
            if effect != "Offensive effects have not been validated."
        ],
    }
    if bolt:
        return {**reviewed, "bolt_effect": bolt[1], "ammo_type": f"bolt:{row['id']}"}
    assert crossbow is not None
    return {
        **reviewed,
        "ammo_for": tuple(
            dict.fromkeys(
                (
                    *row["ammo_for"],
                    *(f"bolt:{i}" for i in (*crossbow[2], *crossbow[3])),
                )
            )
        ),
        "omitted_set_effects": tuple(
            dict.fromkeys(
                (
                    *row.get("omitted_set_effects", ()),
                    *(
                        ("Crossbow special attacks are not modeled.",)
                        if row["id"] in {8880, 21902, 11785, 26374}
                        else ()
                    ),
                )
            )
        ),
    }
