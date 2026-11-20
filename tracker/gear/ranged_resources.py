"""Reviewed physical expendable ranged resources, separate from combat support.

Ava recovery: https://oldschool.runescape.wiki/w/Ava%27s_device
Hunter spear: https://oldschool.runescape.wiki/w/Hunter%27s_spear
Exact forms only: stackability also describes reusable ranged equipment.
"""

from tracker.gear.models import EquipmentDefinition
from tracker.gear.revenant import CHARGED_BOWS

HUNTER_SPEAR = 29305

DART_IDS = frozenset(
    {
        *range(806, 818),
        3093,
        3094,
        *range(5628, 5642),
        11230,
        11231,
        11233,
        11234,
        25849,
        25851,
        25855,
        25857,
    }
)


THROWN_IDS = frozenset(
    {
        732,
        *range(806, 812),
        *range(863, 870),
        *range(800, 806),
        *range(825, 831),
        6522,
        3093,
        25849,
        20849,
        HUNTER_SPEAR,
        22636,
        22634,
        11230,
        11233,
        22804,
        22806,
        22808,
        22810,
        22812,
        22814,
        22816,
    }
)


# Preserve historical dart budget exemptions, including poisoned variants.
CONSUMABLE_WEAPON_IDS = DART_IDS | THROWN_IDS


def ranged_damage_type(weapon: EquipmentDefinition | None) -> str:
    """Defence category also accounts for ether bows' internal standard arrows."""
    if weapon is not None and weapon.id in CHARGED_BOWS:
        return "standard"
    if weapon is None or not weapon.ammo_for:
        return "light"
    return "heavy" if weapon.ammo_for[0].startswith("bolt:") else "standard"
