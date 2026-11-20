"""Reviewed ordinary PvM powered attacks, exact forms and charging recipes.

Sources reviewed 2026-11-05: https://oldschool.runescape.wiki/w/Powered_staff
and each linked weapon page. Formula cross-check:
weirdgloop/osrs-dps-calc PlayerVsNPCCalc.ts at
498bd2ae666c83b0af3ac2265076ed237a27d1aa (formulas and Sang distribution).
Individual pages: /w/Warped_sceptre, /w/Bone_staff, /w/Trident_of_the_seas,
/w/Trident_of_the_swamp, /w/Sanguinesti_staff, /w/Eye_of_Ayak,
/w/Tumeken%27s_shadow, /w/Thammaron%27s_sceptre, /w/Accursed_sceptre.
Physical charged/uncharged identities cross-checked 2026-11-06 against
https://github.com/runelite/runelite/blob/master/runelite-api/src/main/java/net/runelite/api/gameval/ItemID.java
Warped: WARPED_SCEPTRE_UNCHARGED=28583, WARPED_SCEPTRE=28585.
The Wilderness attack modifier is reviewed separately in tracker.gear.revenant.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class PoweredStaff:
    model: str
    name: str
    level: int
    charged_id: int
    uncharged_id: int
    recipes: tuple[tuple[tuple[int, int], ...], ...]
    speed: int = 4
    reserve: int = 0


_SEAS = (((554, 5), (562, 1), (560, 1), (995, 10)),)
_SWAMP = (((554, 5), (562, 1), (560, 1), (12934, 1)),)
MARKET_FORMS = frozenset({28583, 11908, 12900, 22481, 22552, 27662, 31115, 27277})
STAFFS = (
    PoweredStaff("warped", "Warped sceptre", 62, 28585, 28583, (((557, 5), (562, 2)),)),
    PoweredStaff("bone", "Bone staff", 50, 28796, 28796, (((562, 1),),)),
    PoweredStaff("seas", "Trident of the seas", 75, 11907, 11908, _SEAS),
    PoweredStaff("seas", "Trident of the seas (e)", 75, 22288, 22290, _SEAS),
    PoweredStaff("seas", "Trident of the seas (o)", 75, 33322, 33434, _SEAS),
    PoweredStaff("seas", "Trident of the seas (e) (o)", 75, 33326, 33328, _SEAS),
    PoweredStaff("swamp", "Trident of the swamp", 78, 12899, 12900, _SWAMP),
    PoweredStaff("swamp", "Trident of the swamp (e)", 78, 22292, 22294, _SWAMP),
    PoweredStaff("swamp", "Trident of the swamp (o)", 78, 33314, 33316, _SWAMP),
    PoweredStaff("swamp", "Trident of the swamp (e) (o)", 78, 33318, 33320, _SWAMP),
    PoweredStaff("sanguinesti", "Sanguinesti staff", 82, 22323, 22481, (((565, 2),),)),
    PoweredStaff("sanguinesti", "Holy sanguinesti staff", 82, 25731, 25733, (((565, 2),),)),
    PoweredStaff(
        "ayak", "Eye of Ayak", 83, 31113, 31115, (((31111, 1),), ((560, 2), (562, 1))), speed=3
    ),
    PoweredStaff("shadow", "Tumeken's shadow", 85, 27275, 27277, (((566, 2), (562, 5)),), speed=5),
    PoweredStaff(
        "thammaron", "Thammaron's sceptre", 60, 22555, 22552, (((21820, 1),),), reserve=1000
    ),
    PoweredStaff("accursed", "Accursed sceptre", 70, 27665, 27662, (((21820, 1),),), reserve=1000),
)
REVIEWS = MappingProxyType(
    {
        **{i: s for s in STAFFS for i in (s.charged_id, s.uncharged_id)},
        11905: STAFFS[2],
        # RuneLite gameval ItemID: TOTS_ORN is full, TOTS_UNCHARGED_ORN=33434.
        33323: STAFFS[4],
    }
)
REVISION = repr(STAFFS).encode("utf-8")


def review(item_id: int) -> PoweredStaff | None:
    return REVIEWS.get(item_id)


def base_hit(model: str, magic: int) -> int:
    if model == "warped":
        return max(1, (8 * magic + 96) // 37)
    if model == "bone":
        # Ratbane is part of this weapon's base, before equipment damage percent.
        return max(1, magic // 3 - 5) + 10
    offsets = {
        "seas": -5,
        "swamp": -2,
        "sanguinesti": 0,
        "shadow": 1,
        "ayak": -6,
        "thammaron": -8,
        "accursed": -6,
    }
    if model not in offsets:
        raise ValueError(f"Unreviewed powered damage model: {model}")
    return max(1, magic // 3 + offsets[model])


def supports_powered(item: Any) -> bool:
    return bool(
        item.powered_attack
        and item.powered_attack_stances
        and (item.powered_attack_base_max_hit is not None or item.powered_attack_model is not None)
    )
