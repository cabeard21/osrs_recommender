"""Transparent secondary metrics for exact ordinary-attack DPS ties."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

SecondaryPriority = Literal[
    "default",
    "balanced_defence",
    "magic_ranged_defence",
    "stab_defence",
    "slash_defence",
    "crush_defence",
    "ranged_defence",
    "magic_defence",
    "prayer_bonus",
    "melee_strength_bonus",
    "ranged_strength_bonus",
    "magic_damage_bonus",
    "accuracy",
]

_DEFENCES = ("defence_stab", "defence_slash", "defence_crush", "defence_ranged", "defence_magic")
_BONUSES = {
    "stab_defence": "defence_stab",
    "slash_defence": "defence_slash",
    "crush_defence": "defence_crush",
    "ranged_defence": "defence_ranged",
    "magic_defence": "defence_magic",
    "prayer_bonus": "prayer",
    "melee_strength_bonus": "melee_strength",
    "ranged_strength_bonus": "ranged_strength",
    "magic_damage_bonus": "magic_damage",
}


def secondary_value(
    priority: SecondaryPriority,
    performance: Mapping[str, Any],
) -> float:
    """Use equipment bonuses or the evaluator's hit probability, without survival estimates."""
    if priority == "default":
        return 0.0
    if priority == "accuracy":
        return float(performance.get("accuracy") or 0)
    if priority == "balanced_defence":
        fields: tuple[str, ...] = _DEFENCES
    elif priority == "magic_ranged_defence":
        fields = ("defence_magic", "defence_ranged")
    else:
        fields = (_BONUSES[priority],)
    bonuses = performance.get("bonuses", {})
    return float(sum(bonuses.get(field, 0) for field in fields) / len(fields))
