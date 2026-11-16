"""Reviewed exact dragonbane forms and ordinary attack affinities.

Sources: OSRS Wiki Dragon hunter lance/crossbow/wand and Autocast;
weirdgloop/osrs-dps-calc 74958b18f6559cf1bf58f7ac74e7a442a7ac8e2f.
Wear requirements do not imply crafting access or full miniquest completion.
"""

import json
from types import MappingProxyType
from typing import Any

from tracker.content.requirements import AllOf, SkillLeaf, UnlockLeaf

MODEL_VERSION = "dragonbane-v1"
FORMS = MappingProxyType(
    {
        22978: ("Dragon hunter lance", "weapon"),
        21012: ("Dragon hunter crossbow", "weapon"),
        25916: ("Dragon hunter crossbow (t)", "weapon"),
        25918: ("Dragon hunter crossbow (b)", "weapon"),
        30070: ("Dragon hunter wand", "weapon"),
    }
)
BONUSES = MappingProxyType(
    {22978: (20, 20), 21012: (30, 25), 25916: (30, 25), 25918: (30, 25), 30070: (75, 40)}
)
TRADEABLE = frozenset({22978, 21012, 30070})
LANCE_PROFILES = (
    ("stab", "controlled"),
    ("slash", "controlled"),
    ("crush", "controlled"),
    ("stab", "defensive"),
)
REVISION = json.dumps(
    [
        MODEL_VERSION,
        dict(FORMS),
        dict(BONUSES),
        sorted(TRADEABLE),
        LANCE_PROFILES,
        "attack78-barbarian_hasta_training-ranged70-magic65",
    ],
    sort_keys=True,
).encode()


def requirement(item_id: int) -> AllOf | SkillLeaf:
    if item_id == 22978:
        return AllOf(
            children=(
                SkillLeaf(skill="attack", level=78),
                UnlockLeaf(key="barbarian_hasta_training"),
            )
        )
    return SkillLeaf(
        skill="magic" if item_id == 30070 else "ranged", level=65 if item_id == 30070 else 70
    )


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    """Clear the generic blocker only for reviewed physical identities."""
    form = FORMS.get(row["id"])
    if form is None:
        return row
    if (row["name"], row["slot"]) != form:
        raise ValueError(f"Reviewed dragonbane physical form changed: {row['id']}")
    result = {
        **row,
        "unsupported_effects": [
            e
            for e in row["unsupported_effects"]
            if e != "Offensive effects have not been validated."
        ],
    }
    if row["id"] == 22978:
        result = {
            **result,
            "attack_styles": ("stab", "slash", "crush"),
            "attack_profiles": LANCE_PROFILES,
        }
    return result
