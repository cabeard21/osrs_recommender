"""Ordinary player defence rolls at the current boosted-stat snapshot.

Reference: OSRS Wiki calculator src/lib/NPCVsPlayerCalc.ts,
getPlayerDefenceRoll (reviewed 2026-11-04). Reviewed active stat prayers; no special effects.
"""

from __future__ import annotations

from collections.abc import Mapping

from tracker.gear.models import EquipmentBonuses, PlayerDefenceRolls
from tracker.gear.prayers import NO_PRAYERS, PrayerEffects

MODEL_VERSION = "player-defence-roll-v2"
STYLES = ("stab", "slash", "crush", "ranged", "magic")


def required_defensive_skills(priority: str) -> frozenset[str]:
    if not priority.endswith("_defence_roll"):
        return frozenset()
    return frozenset(
        ("defence", "magic")
        if priority in {"balanced_defence_roll", "magic_ranged_defence_roll", "magic_defence_roll"}
        else ("defence",)
    )


def player_defence_rolls(
    levels: Mapping[str, int],
    bonuses: EquipmentBonuses,
    stance: str,
    prayers: PrayerEffects = NO_PRAYERS,
) -> PlayerDefenceRolls:
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
    return PlayerDefenceRolls(
        **{
            style: None
            if level is None
            else max(0, level * (getattr(bonuses, "defence_" + style) + 64))
            for style, level in effective.items()
        },
        limitations=tuple(
            f"Player {name} level is unknown."
            for name, level in (("Defence", defence), ("Magic", magic))
            if level < 1
        ),
    )
