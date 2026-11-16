"""Ordinary player defence rolls at the current boosted-stat snapshot.

Reference: OSRS Wiki calculator src/lib/NPCVsPlayerCalc.ts,
getPlayerDefenceRoll (reviewed 2026-11-04). Reviewed active stat prayers; no special effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from tracker.gear.models import EquipmentBonuses, PlayerDefenceRolls
from tracker.gear.prayers import NO_PRAYERS, PrayerEffects
from tracker.gear.priorities import ROLL_METRICS

MODEL_VERSION = "player-defence-roll-v2"
STYLES = ("stab", "slash", "crush", "ranged", "magic")


def required_defensive_skills(priority: str) -> frozenset[str]:
    metric = ROLL_METRICS.get(priority)
    if metric is None:
        return frozenset()
    return frozenset(("defence", "magic") if "magic" in metric.styles else ("defence",))


def raw_player_defence_rolls(
    levels: Mapping[str, int],
    bonuses: EquipmentBonuses,
    stance: str,
    prayers: PrayerEffects = NO_PRAYERS,
) -> Mapping[str, int | None]:
    """Floor weighted Magic and Defence separately before adding stance and eight."""
    defence = levels.get("defence", 0)
    magic = levels.get("magic", 0)
    defence = defence * prayers.defence // 100
    magic = magic * prayers.magic_defence // 100
    stance_bonus = 3 if stance in {"defensive", "longrange"} else int(stance == "controlled")
    physical = defence + stance_bonus + 8 if defence > 0 else None
    magical = (
        magic * 7 // 10 + defence * 3 // 10 + stance_bonus + 8
        if defence > 0 and magic > 0
        else None
    )
    effective = {style: magical if style == "magic" else physical for style in STYLES}
    return MappingProxyType(
        {
            style: None
            if level is None
            else max(0, level * (getattr(bonuses, "defence_" + style) + 64))
            for style, level in effective.items()
        }
    )


def player_defence_rolls(
    levels: Mapping[str, int],
    bonuses: EquipmentBonuses,
    stance: str,
    prayers: PrayerEffects = NO_PRAYERS,
) -> PlayerDefenceRolls:
    """Report the same raw rolls with explicit unknown-stat limitations."""
    return PlayerDefenceRolls(
        **raw_player_defence_rolls(levels, bonuses, stance, prayers),
        limitations=tuple(
            f"Player {name} level is unknown."
            for name, level in (
                ("Defence", levels.get("defence", 0)),
                ("Magic", levels.get("magic", 0)),
            )
            if level < 1
        ),
    )
