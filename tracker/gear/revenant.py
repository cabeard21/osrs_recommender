"""Reviewed normal-world revenant weapon physical forms and ordinary attack modes.

Sources: https://oldschool.runescape.wiki/w/Wilderness_weapons and the linked
weapon pages. IDs cross-checked against RuneLite gameval ItemID.WILD_CAVE_*
(especially CHAINMACE_UNCHARGED=22542 and BOW_UNCHARGED=22547).
The two sceptre settings can be swapped on the same physical item.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

MODEL_VERSION = "revenant-weapons-v1"
ETHER_ID = 21820
ACTIVATION_RESERVE = 1000
MAX_CHARGES = 16000


@dataclass(frozen=True, slots=True)
class RevenantWeapon:
    name: str
    kind: Literal["mace", "bow", "powered", "autocast"]
    level: int
    charged_id: int
    uncharged_id: int
    market_id: int  # Canonical GE base across settings of one reversible sceptre.

    @property
    def skill(self) -> str:
        return {"mace": "attack", "bow": "ranged"}.get(self.kind, "magic")


WEAPONS = (
    RevenantWeapon("Viggora's chainmace", "mace", 60, 22545, 22542, 22542),
    RevenantWeapon("Ursine chainmace", "mace", 70, 27660, 27657, 27657),
    RevenantWeapon("Craw's bow", "bow", 60, 22550, 22547, 22547),
    RevenantWeapon("Webweaver bow", "bow", 70, 27655, 27652, 27652),
    RevenantWeapon("Thammaron's sceptre", "powered", 60, 22555, 22552, 22552),
    RevenantWeapon("Accursed sceptre", "powered", 70, 27665, 27662, 27662),
    RevenantWeapon("Thammaron's sceptre (a)", "autocast", 60, 27788, 27785, 22552),
    RevenantWeapon("Accursed sceptre (a)", "autocast", 70, 27679, 27676, 27662),
)
FORMS = MappingProxyType(
    {i: weapon for weapon in WEAPONS for i in (weapon.charged_id, weapon.uncharged_id)}
)
CHARGED_MACES = frozenset(w.charged_id for w in WEAPONS if w.kind == "mace")
CHARGED_BOWS = frozenset(w.charged_id for w in WEAPONS if w.kind == "bow")
CHARGED_AUTOCAST = frozenset(w.charged_id for w in WEAPONS if w.kind == "autocast")
CHARGED_SCEPTRES = CHARGED_AUTOCAST | frozenset(
    w.charged_id for w in WEAPONS if w.kind == "powered"
)
MACE_PROFILES = (
    ("crush", "accurate"),
    ("crush", "aggressive"),
    ("stab", "controlled"),
    ("crush", "defensive"),
)
REVISION = repr(
    (MODEL_VERSION, WEAPONS, MACE_PROFILES, ETHER_ID, ACTIVATION_RESERVE, MAX_CHARGES)
).encode()


def passive_applies(item_id: int, style: str) -> bool:
    return (
        (item_id in CHARGED_MACES and style in {"stab", "crush", "melee"})
        or (item_id in CHARGED_BOWS and style in {"standard", "ranged"})
        or (item_id in CHARGED_SCEPTRES and style == "magic")
    )


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    weapon = FORMS.get(row["id"])
    if weapon is None:
        return row
    if row["name"] != weapon.name or row["slot"] != "weapon":
        raise ValueError(f"Reviewed revenant weapon physical form changed: {row['id']}")
    charged = row["id"] == weapon.charged_id
    effects = [
        e for e in row["unsupported_effects"] if e != "Offensive effects have not been validated."
    ]
    profiles: dict[str, Any] = {}
    if weapon.kind == "mace":
        profiles = {"attack_styles": ("crush", "stab"), "attack_profiles": MACE_PROFILES}
    elif not charged and weapon.kind in {"bow", "powered"}:
        profiles = {"attack_styles": (), "attack_profiles": ()}
        effects.append("This attack requires a weapon charged with revenant ether.")
    return {
        **row,
        **profiles,
        "name": f"{weapon.name} ({'charged' if charged else 'uncharged'})",
        "unsupported_effects": effects,
    }
