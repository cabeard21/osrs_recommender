"""Transparent secondary metrics for exact ordinary-attack DPS ties."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal, NamedTuple

SecondaryPriority = Literal[
    "stab_magic_defence_roll",
    "stab_ranged_defence_roll",
    "stab_magic_ranged_defence_roll",
    "slash_magic_defence_roll",
    "slash_ranged_defence_roll",
    "slash_magic_ranged_defence_roll",
    "crush_magic_defence_roll",
    "crush_ranged_defence_roll",
    "crush_magic_ranged_defence_roll",
    "melee_defence_roll",
    "melee_magic_defence_roll",
    "melee_ranged_defence_roll",
    "balanced_defence_roll",
    "magic_ranged_defence_roll",
    "stab_defence_roll",
    "slash_defence_roll",
    "crush_defence_roll",
    "ranged_defence_roll",
    "magic_defence_roll",
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


class RollMetric(NamedTuple):
    styles: tuple[str, ...]
    aggregation: Literal["mean", "minimum"]


ROLL_METRICS: Mapping[str, RollMetric] = MappingProxyType(
    {
        "balanced_defence_roll": RollMetric(("stab", "slash", "crush", "ranged", "magic"), "mean"),
        "magic_ranged_defence_roll": RollMetric(("magic", "ranged"), "minimum"),
        "melee_defence_roll": RollMetric(("stab", "slash", "crush"), "minimum"),
        "melee_magic_defence_roll": RollMetric(("stab", "slash", "crush", "magic"), "minimum"),
        "melee_ranged_defence_roll": RollMetric(("stab", "slash", "crush", "ranged"), "minimum"),
        **{
            melee + "_" + "_".join(others) + "_defence_roll": RollMetric(
                (melee, *others), "minimum"
            )
            for melee in ("stab", "slash", "crush")
            for others in (("magic",), ("ranged",), ("magic", "ranged"))
        },
        **{
            style + "_defence_roll": RollMetric((style,), "mean")
            for style in ("stab", "slash", "crush", "ranged", "magic")
        },
    }
)


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

# These metrics are constant across attacks/prayers for a fixed equipment set
# and concrete discipline. Their metric-first option rank has the same winner
# as DPS-first; accuracy and player defence rolls deliberately remain separate.
EQUIPMENT_BONUS_PRIORITIES = frozenset({"balanced_defence", "magic_ranged_defence", *_BONUSES})


def secondary_value(
    priority: SecondaryPriority,
    performance: Mapping[str, Any],
) -> float:
    """Use equipment bonuses or the evaluator's hit probability, without survival estimates."""
    if priority == "default":
        return 0.0
    if priority == "accuracy":
        return float(performance.get("accuracy") or 0)
    if priority.endswith("_defence_roll"):
        if performance.get("supported") is False:
            return 0.0  # Incomplete search beams may not yet have a legal weapon.
        rolls = performance.get("player_defence_rolls") or {}
        metric = ROLL_METRICS[priority]
        roll_fields = metric.styles
        if any(rolls.get(field) is None for field in roll_fields):
            raise ValueError(
                "Player defensive roll is unavailable: required combat levels are unknown"
            )
        values = [rolls[field] for field in roll_fields]
        return float(min(values) if metric.aggregation == "minimum" else sum(values) / len(values))
    bonuses = performance.get("bonuses", {})
    if priority == "magic_ranged_defence":
        return float(min(bonuses.get("defence_magic", 0), bonuses.get("defence_ranged", 0)))
    if priority == "balanced_defence":
        fields: tuple[str, ...] = _DEFENCES
    else:
        fields = (_BONUSES[priority],)
    return float(sum(bonuses.get(field, 0) for field in fields) / len(fields))
