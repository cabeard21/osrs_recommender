"""Exact physical demonbane reviews for ordinary outgoing attacks.

Sources: OSRS Wiki Silverlight, Darklight, Arclight, Emberlight, Burning claws,
Scorching bow, Purging staff, Holy water, Demonbane spells and Autocast.
Arithmetic/target review: weirdgloop/osrs-dps-calc at
74958b18f6559cf1bf58f7ac74e7a442a7ac8e2f (PlayerVsNPCCalc.ts / BaseCalc.ts).
Wear gates do not imply crafting access or an observed charge balance.
"""

import json
from types import MappingProxyType
from typing import Any

MODEL_VERSION = "demonbane-v1"
FORMS = MappingProxyType(
    {
        2402: ("Silverlight", "weapon"),
        6745: ("Silverlight", "weapon"),
        6746: ("Darklight", "weapon"),
        19675: ("Arclight", "weapon"),
        30305: ("Arclight", "weapon"),
        29589: ("Emberlight", "weapon"),
        29577: ("Burning claws", "weapon"),
        29591: ("Scorching bow", "weapon"),
        29594: ("Purging staff", "weapon"),
        732: ("Holy water", "weapon"),
    }
)
WEAPON_BONUSES = MappingProxyType(
    {2402: 60, 6745: 60, 6746: 60, 19675: 70, 30305: 60, 29589: 70, 29577: 5, 29591: 30, 732: 60}
)
SPELLS = MappingProxyType(
    {"inferior_demonbane": (44, 16), "superior_demonbane": (62, 23), "dark_demonbane": (82, 30)}
)
AUTOCAST_STAVES = frozenset({4170, 21255, 29594, 6914, 21006, 4710})
REQUIREMENTS = MappingProxyType(
    {
        i: MappingProxyType(gates)
        for i, gates in {
            2402: {},
            6745: {},
            6746: {},
            19675: {"attack": 75},
            30305: {"attack": 75},
            29589: {"attack": 77},
            29577: {"attack": 60},
            29591: {"ranged": 77},
            29594: {"attack": 50, "magic": 77},
            732: {},
        }.items()
    }
)
TRADEABLE = frozenset({29577})
MELEE_PROFILES = (
    ("slash", "accurate"),
    ("slash", "aggressive"),
    ("stab", "controlled"),
    ("slash", "defensive"),
)
# Dragon-tier arrows, including reviewed broad arrow forms. This does not enable
# unrelated ammunition effects or bless unreviewed arrow identities.
ARROWS = (882, 884, 886, 888, 890, 892, 11212, 21326, 4160, 33601)
NPC_EFFECTIVENESS = MappingProxyType(
    {
        12191: 70,
        12195: 70,
        14176: 120,
        100001: 120,
        16673: 80,
        16675: 80,
        16677: 80,
        16684: 80,
        16665: 25,
        16666: 25,
        14179: 200,
        7584: 115,
        7585: 115,
    }
)
HOLY_WATER_SPECIAL_TARGETS = frozenset({3962, 6318, 6379})
REVISION = json.dumps(
    [
        MODEL_VERSION,
        dict(FORMS),
        dict(WEAPON_BONUSES),
        dict(SPELLS),
        sorted(AUTOCAST_STAVES),
        {i: dict(g) for i, g in REQUIREMENTS.items()},
        sorted(TRADEABLE),
        MELEE_PROFILES,
        ARROWS,
        dict(NPC_EFFECTIVENESS),
        sorted(HOLY_WATER_SPECIAL_TARGETS),
    ],
    sort_keys=True,
).encode()


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    """Authorize only reviewed physical forms, retaining other effect blockers."""
    form = FORMS.get(row["id"])
    if form is None:
        return row
    if (row["name"], row["slot"]) != form:
        raise ValueError(f"Reviewed demonbane physical form changed: {row['id']}")
    result = {
        **row,
        "unsupported_effects": [
            e
            for e in row["unsupported_effects"]
            if e != "Offensive effects have not been validated."
        ],
    }
    if row["id"] == 29577:
        result = {**result, "attack_styles": ("slash", "stab"), "attack_profiles": MELEE_PROFILES}
    if row["id"] == 29591:
        result = {**result, "ammo_for": tuple(f"arrow:{i}" for i in ARROWS)}
    return result
