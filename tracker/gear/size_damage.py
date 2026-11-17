"""Reviewed ordinary melee max-hit bonuses based on target footprint.

https://oldschool.runescape.wiki/w/Colossal_blade
https://github.com/weirdgloop/osrs-dps-calc/blob/main/src/lib/PlayerVsNPCCalc.ts
Colossal blade adds 2 * min(size, 5) after other melee damage multipliers.
Size is the side length in tiles, not the footprint's area.
"""

from typing import Any

MODEL_VERSION = "target-size-max-hit-v1"
COLOSSAL_BLADE = 27021
PROFILES = (
    ("slash", "accurate"),
    ("slash", "aggressive"),
    ("crush", "aggressive"),
    ("slash", "defensive"),
)
REVISION = repr((MODEL_VERSION, COLOSSAL_BLADE, 2, 5, 60, PROFILES)).encode()


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    """Certify this exact physical weapon while preserving unrelated blockers."""
    if row["id"] != COLOSSAL_BLADE:
        return row
    if row["name"] != "Colossal blade" or row["slot"] != "weapon" or not row["two_handed"]:
        raise ValueError(f"Reviewed size-bonus physical form changed: {row['id']}")
    return {
        **row,
        "size_damage_bonus": {"damage_per_size": 2, "max_size": 5},
        "attack_profiles": PROFILES,
        "unsupported_effects": [
            effect
            for effect in row["unsupported_effects"]
            if effect != "Offensive effects have not been validated."
        ],
    }
