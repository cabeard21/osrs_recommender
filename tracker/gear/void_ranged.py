"""Wearable Elite Void ranged pieces, plus ordinary armour in the Sentinel fixtures.

Sources: OSRS Wiki Elite Void Knight equipment, Blood Moon armour, Saradomin
blessed dragonhide boots. Physical forms checked against the game cache at
Joshua-F/osrs-dumps c4455dfa5ca75d4ecc0f309b36bce7097c695d69 config/dump.obj.
Broken variants have no Wear operation even when the imported names match.
"""

import json
from collections.abc import Iterable
from types import MappingProxyType
from typing import Any

from tracker.content.requirements import AllOf, SkillLeaf, UnlockLeaf

RANGER_HELMS = frozenset({11664, 24184, 26475, 27006})
ELITE_TOPS = frozenset({13072, 24178, 26469, 27003})
ELITE_ROBES = frozenset({13073, 24180, 26471, 27004})
VOID_GLOVES = frozenset({8842, 24182, 26467, 27002})
_GROUPS = (RANGER_HELMS, ELITE_TOPS, ELITE_ROBES, VOID_GLOVES)
_KIT = RANGER_HELMS | ELITE_TOPS | ELITE_ROBES | VOID_GLOVES
_ORNAMENTED = frozenset({26475, 27006, 26469, 27003, 26471, 27004, 26467, 27002})
_BLOOD_MOON = {
    29022: ("Blood moon chestplate", "body"),
    29025: ("Blood moon tassets", "legs"),
    29028: ("Blood moon helm", "head"),
}
FORMS = MappingProxyType(
    {
        **{
            i: (name + (" (or)" if i in _ORNAMENTED else ""), slot)
            for ids, name, slot in (
                (RANGER_HELMS, "Void ranger helm", "head"),
                (ELITE_TOPS, "Elite void top", "body"),
                (ELITE_ROBES, "Elite void robe", "legs"),
                (VOID_GLOVES, "Void knight gloves", "hands"),
            )
            for i in ids
        },
        **_BLOOD_MOON,
        19933: ("Saradomin d'hide boots", "feet"),
    }
)
BLOOD_MOON_ARMOUR = frozenset(_BLOOD_MOON)
TRADEABLE = BLOOD_MOON_ARMOUR | {19933}
ELITE_UPGRADE = UnlockLeaf(key="diary_western_hard")
BLOOD_MOON_OMISSION = (
    "Blood Moon armour's full-set attack-speed bonus with dual macuahuitl is not modeled."
)

_VOID_GATES = AllOf(
    children=(
        *(
            SkillLeaf(skill=s, level=42)
            for s in ("attack", "strength", "defence", "ranged", "magic", "hitpoints")
        ),
        SkillLeaf(skill="prayer", level=22),
    )
)
_BLOOD_GATES = AllOf(
    children=(SkillLeaf(skill="strength", level=75), SkillLeaf(skill="defence", level=50))
)
_BOOT_GATES = AllOf(
    children=(SkillLeaf(skill="defence", level=40), SkillLeaf(skill="ranged", level=70))
)
REVISION = json.dumps(
    [
        "elite-void-ranged-v1",
        dict(FORMS),
        sorted(TRADEABLE),
        sorted(ELITE_TOPS | ELITE_ROBES),
        _VOID_GATES.to_yaml(),
        _BLOOD_GATES.to_yaml(),
        _BOOT_GATES.to_yaml(),
        ELITE_UPGRADE.to_yaml(),
    ],
    sort_keys=True,
).encode()


def is_elite_ranged(ids: Iterable[int]) -> bool:
    equipped = frozenset(ids)
    return all(not group.isdisjoint(equipped) for group in _GROUPS)


def requirement(item_id: int) -> AllOf:
    if item_id in _KIT:
        return _VOID_GATES
    return _BLOOD_GATES if item_id in _BLOOD_MOON else _BOOT_GATES


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    item_id = row["id"]
    form = FORMS.get(item_id)
    if form is None:
        return row
    if (row["name"], row["slot"]) != form:
        raise ValueError(f"Reviewed armour physical form changed: {item_id}")
    return {
        **row,
        "unsupported_effects": [
            e
            for e in row["unsupported_effects"]
            if e != "Offensive effects have not been validated."
        ],
        **(
            {
                "omitted_set_effects": tuple(
                    dict.fromkeys((*row.get("omitted_set_effects", ()), BLOOD_MOON_OMISSION))
                )
            }
            if item_id in _BLOOD_MOON
            else {}
        ),
    }
