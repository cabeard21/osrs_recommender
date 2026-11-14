"""Exact physical leafy equipment reviews, independent of imported defaults.

Sources: OSRS Wiki Leaf-bladed spear, Leaf-bladed sword, Leaf-bladed battleaxe,
Broad arrows, Seeking broad arrows, Broad bolts and Amethyst broad bolts.
Compatibility follows Weird Gloop Equipment.ts at
880ab3f324ebea2644681d835448ab9d45c04f5c: magic-tier arrows and rune-tier bolts.
Crafting and shop access are not wear requirements.
"""

import json
from types import MappingProxyType
from typing import Any

MODEL_VERSION = "leafy-v1"
FORMS = MappingProxyType(
    {
        4158: ("Leaf-bladed spear", "weapon"),
        11902: ("Leaf-bladed sword", "weapon"),
        20727: ("Leaf-bladed battleaxe", "weapon"),
        4160: ("Broad arrows", "ammunition"),
        33601: ("Seeking broad arrows", "ammunition"),
        11875: ("Broad bolts", "ammunition"),
        21316: ("Amethyst broad bolts", "ammunition"),
    }
)
LEAF_WEAPONS = frozenset({4158, 11902, 20727})
BROAD_AMMO = frozenset({4160, 33601, 11875, 21316})
REQUIREMENTS = MappingProxyType(
    {
        i: MappingProxyType(gates)
        for i, gates in {
            4158: {"attack": 50, "slayer": 55},
            11902: {"attack": 50, "slayer": 55},
            20727: {"attack": 65, "slayer": 55},
            4160: {"ranged": 50, "slayer": 55},
            33601: {"ranged": 50, "slayer": 55},
            11875: {"ranged": 61, "slayer": 55},
            21316: {"ranged": 61, "slayer": 65},
        }.items()
    }
)
TRADEABLE = frozenset({11902, 20727, 11875, 21316})
NPC_SLAYER = MappingProxyType(
    {427: 55, 428: 55, 429: 55, 430: 55, 10397: 55, 410: 70, 411: 70, 7405: 70}
)
PROFILES = MappingProxyType(
    {
        4158: (
            ("stab", "controlled"),
            ("slash", "controlled"),
            ("crush", "controlled"),
            ("stab", "defensive"),
        ),
        20727: (
            ("slash", "accurate"),
            ("slash", "aggressive"),
            ("crush", "aggressive"),
            ("slash", "defensive"),
        ),
    }
)
REVISION = json.dumps(
    [
        MODEL_VERSION,
        dict(FORMS),
        {i: dict(g) for i, g in REQUIREMENTS.items()},
        sorted(TRADEABLE),
        dict(NPC_SLAYER),
        dict(PROFILES),
    ],
    sort_keys=True,
).encode()


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    """Review exact forms while retaining unrelated explicit effect blockers."""
    form = FORMS.get(row["id"])
    if form is not None:
        if (row["name"], row["slot"]) != form:
            raise ValueError(f"Reviewed leafy physical form changed: {row['id']}")
        row = {
            **row,
            "unsupported_effects": [
                e
                for e in row["unsupported_effects"]
                if e != "Offensive effects have not been validated."
            ],
        }
        if row["id"] in BROAD_AMMO:
            prefix = "arrow" if row["id"] in {4160, 33601} else "bolt"
            row = {**row, "ammo_type": f"{prefix}:{row['id']}"}
        if row["id"] in PROFILES:
            profiles = PROFILES[row["id"]]
            row = {
                **row,
                "attack_profiles": profiles,
                "attack_styles": tuple(dict.fromkeys(p[0] for p in profiles)),
            }
    # Compatibility alone never blesses unsupported bow/crossbow effects.
    ammo_for = tuple(row["ammo_for"])
    added = (
        ("arrow:4160", "arrow:33601")
        if "arrow:21326" in ammo_for
        else ("bolt:11875", "bolt:21316")
        if "bolt:9144" in ammo_for
        else ()
    )
    return {**row, "ammo_for": tuple(dict.fromkeys((*ammo_for, *added)))} if added else row
