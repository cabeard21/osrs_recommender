"""Reviewed physical Salve amulet forms and their acquisition routes.

https://oldschool.runescape.wiki/w/Salve_amulet
https://oldschool.runescape.wiki/w/Salve_amulet_(e)
https://oldschool.runescape.wiki/w/Salve_amulet(i)
https://oldschool.runescape.wiki/w/Salve_amulet(ei)
"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from tracker.content.requirements import AllOf, QuestLeaf

if TYPE_CHECKING:
    from tracker.gear.models import EquipmentDefinition
    from tracker.gear.optimizer import RoleConfig

MODEL_VERSION = "salve-amulets-v1"
FORMS = MappingProxyType(
    {
        4081: ("Salve amulet", 1),
        10588: ("Salve amulet (e)", 2),
        12017: ("Salve amulet(i)", 3),
        25250: ("Salve amulet(i)", 3),
        26763: ("Salve amulet(i)", 3),
        12018: ("Salve amulet(ei)", 4),
        25278: ("Salve amulet(ei)", 4),
        26782: ("Salve amulet(ei)", 4),
    }
)
_IMBUES = MappingProxyType(
    {
        **dict.fromkeys(
            (12017, 12018),
            "Imbue at Nightmare Zone with 800,000 points "
            "(400,000 after the Hard Combat Achievements).",
        ),
        **dict.fromkeys((25250, 25278), "Imbue at Soul Wars with 320 Zeal Tokens."),
        **dict.fromkeys((26763, 26782), "Use an Emir’s Arena scroll of imbuing."),
    }
)
_HAUNTED_MINE = QuestLeaf(quest_id="haunted_mine")
_ENCHANTED_REQUIREMENTS = AllOf(
    children=(_HAUNTED_MINE, QuestLeaf(quest_id="lair_of_tarn_razorlor"))
)
REVISION = repr(
    (MODEL_VERSION, tuple(FORMS.items()), tuple(_IMBUES.items()), _ENCHANTED_REQUIREMENTS)
).encode()


def acquisition_requirement(item_id: int) -> AllOf | QuestLeaf:
    return _ENCHANTED_REQUIREMENTS if FORMS[item_id][1] in {2, 4} else _HAUNTED_MINE


def contextual_candidates(
    roles: Iterable["RoleConfig"], eligible: Mapping[int, "EquipmentDefinition"]
) -> tuple[int, ...]:
    """Preserve physical choices at each bounded pool stage for qualifying roles."""
    from tracker.gear.ranged_resources import HUNTER_SPEAR

    styles = {
        r.style for r in roles if r.target and "undead" in r.target.traits and r.style != "special"
    }
    if not styles:
        return ()
    spear = eligible.get(HUNTER_SPEAR) if "ranged" in styles else None
    melee = bool(styles & {"stab", "slash", "crush"}) or (
        spear is not None and not spear.unsupported_effects
    )
    minimum = 1 if melee else 3
    return tuple(i for i, (_, tier) in FORMS.items() if i in eligible and tier >= minimum)


def acquisition_description(item_id: int) -> str:
    steps = ["String a salve shard from the Haunted Mine with a ball of wool."]
    if FORMS[item_id][1] in {2, 4}:
        steps.append("Enchant with Tarn’s diary from the Lair of Tarn Razorlor miniquest.")
    if item_id in _IMBUES:
        steps.append(_IMBUES[item_id])
    return " ".join(steps)


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    form = FORMS.get(row["id"])
    if form is None:
        return row
    if row["name"] != form[0] or row["slot"] != "neck":
        raise ValueError(f"Reviewed Salve physical form changed: {row['id']}")
    return {
        **row,
        "salve_bonus": form[1],
        "unsupported_effects": [
            effect
            for effect in row["unsupported_effects"]
            if effect != "Offensive effects have not been validated."
        ],
    }
