"""Reviewed exact tome forms and ordinary PvM elemental effects.

Stats, wear gates and provision: https://oldschool.runescape.wiki/w/Tome_of_Fire
https://oldschool.runescape.wiki/w/Tome_of_Water
https://oldschool.runescape.wiki/w/Tome_of_Earth
Formula reference: weirdgloop/osrs-dps-calc, PlayerVsNPCCalc.ts at
74958b18f6559cf1bf58f7ac74e7a442a7ac8e2f. Its Water attack-roll factor is
6/5 (before the separate weakness addition); item-page prose instead says
10% accuracy. This version deliberately follows the pinned calculator.
Searing minimum uses the maximum before the tome damage multiplier.
"""

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from tracker.gear.models import EquipmentBonuses, EquipmentDefinition, TomeEffect


@dataclass(frozen=True)
class TomeReview:
    element: Literal["fire", "water", "earth"]
    charged_id: int
    uncharged_id: int
    rune_id: int


TOMES = (
    TomeReview("fire", 20714, 20716, 554),
    TomeReview("water", 25574, 25576, 555),
    TomeReview("earth", 30064, 30066, 557),
)
FORMS = MappingProxyType({i: t for t in TOMES for i in (t.charged_id, t.uncharged_id)})
MARKET_FORMS = frozenset(t.uncharged_id for t in TOMES)
MODEL_VERSION = "elemental-tomes-v1"
ASSUMPTION = "Tome page availability, consumption, and costs are excluded."
REVISION = json.dumps(
    [
        MODEL_VERSION,
        [(t.element, t.charged_id, t.uncharged_id, t.rune_id) for t in TOMES],
        10,
        20,
        50,
    ],
    sort_keys=True,
).encode()


def review(item_id: int) -> TomeReview | None:
    return FORMS.get(item_id)


def applied_tome(
    item: EquipmentDefinition | None, spell: str, powered_attack: str | None = None
) -> TomeEffect | None:
    if item is None or item.slot != "shield" or item.tome_effect is None or powered_attack:
        return None
    element, _, tier = spell.partition("_")
    return (
        item.tome_effect
        if element == item.tome_effect.element
        and tier in {"strike", "bolt", "blast", "wave", "surge"}
        else None
    )


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    tome = review(row["id"])
    if tome is None:
        return row
    if (
        row["name"] != f"Tome of {tome.element.title()}"
        or row["slot"] != "shield"
        or row["bonuses"] != EquipmentBonuses(magic=8, defence_magic=8).model_dump()
    ):
        raise ValueError(f"Reviewed tome physical form changed: {row['id']}")
    return {
        **row,
        "tome_effect": {"element": tome.element, "rune_id": tome.rune_id}
        if row["id"] == tome.charged_id
        else None,
        "unsupported_effects": [
            effect
            for effect in row["unsupported_effects"]
            if effect != "Offensive effects have not been validated."
        ],
    }
