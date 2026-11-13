"""Exact physical elemental amulet review and Standard elemental spell effects.

https://oldschool.runescape.wiki/w/Elemental_amulet
https://oldschool.runescape.wiki/w/Amulet_of_air
https://oldschool.runescape.wiki/w/Amulet_of_water
https://oldschool.runescape.wiki/w/Amulet_of_earth
https://oldschool.runescape.wiki/w/Amulet_of_fire
"""

import json
from types import MappingProxyType
from typing import Any

from tracker.gear.models import EquipmentDefinition

FORMS = MappingProxyType(
    {
        34407: ("Amulet of air", ("air",)),
        34413: ("Amulet of water", ("water",)),
        34419: ("Amulet of earth", ("earth",)),
        34425: ("Amulet of fire", ("fire",)),
        34428: ("Elemental amulet", ("air", "water", "earth", "fire")),
    }
)
MODEL_VERSION = "elemental-amulets-v1"
REVISION = json.dumps([MODEL_VERSION, dict(FORMS), 2, 59], sort_keys=True).encode()


def applied_spell_bonus(
    item: EquipmentDefinition | None, spell: str, powered_attack: str | None = None
) -> int:
    """Only reviewed Standard elemental spells receive the equipped neck effect."""
    if item is None or item.slot != "neck" or not item.elemental_spell_bonus or powered_attack:
        return 0
    element, _, tier = spell.partition("_")
    element = "air" if element == "wind" else element
    effect = item.elemental_spell_bonus
    return (
        effect.base_max_hit_bonus
        if (element in effect.elements and tier in {"strike", "bolt", "blast", "wave", "surge"})
        else 0
    )


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    """Review known physical forms, retaining unrelated blockers."""
    form = FORMS.get(row["id"])
    if form is None:
        return row
    if row["name"] != form[0] or row["slot"] != "neck":
        raise ValueError(f"Reviewed elemental amulet physical form changed: {row['id']}")
    return {
        **row,
        "elemental_spell_bonus": {"elements": form[1], "base_max_hit_bonus": 2},
        "unsupported_effects": [
            e
            for e in row["unsupported_effects"]
            if e != "Offensive effects have not been validated."
        ],
    }
