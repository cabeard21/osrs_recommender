"""Ordinary auto-attack model; unsupported mechanics fail closed.

No prayers, boosts, special attacks or set effects are approximated.
Accurate zero-damage rolls become one; target magic defence uses Magic level.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import floor
from typing import Any

from tracker.gear.models import (
    CombatPerformance,
    CombatTarget,
    ElementalWeakness,
    EquipmentBonuses,
    EquipmentDefinition,
)
from tracker.gear.scoring import PreparedEquipment, prepare_equipment

# Standard spell base damage and minimum level; elemental tier scaling is applied
# only when that tier's spell is unlocked. Spell choice is an explicit assumption.
ELEMENTAL_SPELLS = {
    "wind_strike": (1, 2),
    "water_strike": (5, 4),
    "earth_strike": (9, 6),
    "fire_strike": (13, 8),
    "wind_bolt": (17, 9),
    "water_bolt": (23, 10),
    "earth_bolt": (29, 11),
    "fire_bolt": (35, 12),
    "wind_blast": (41, 13),
    "water_blast": (47, 14),
    "earth_blast": (53, 15),
    "fire_blast": (59, 16),
    "wind_wave": (62, 17),
    "water_wave": (65, 18),
    "earth_wave": (70, 19),
    "fire_wave": (75, 20),
    "wind_surge": (81, 21),
    "water_surge": (85, 22),
    "earth_surge": (90, 23),
    "fire_surge": (95, 24),
}
# https://oldschool.runescape.wiki/w/Iban_Blast
IBAN_STAVES = frozenset({1409, 12658})
# Fixed direct damage, independent of elemental tier scaling and weaknesses.
# https://oldschool.runescape.wiki/w/Ancient_Magicks
ANCIENT_SPELLS = {
    "smoke_rush": (50, 13),
    "shadow_rush": (52, 14),
    "blood_rush": (56, 15),
    "ice_rush": (58, 16),
    "smoke_burst": (62, 17),
    "shadow_burst": (64, 18),
    "blood_burst": (68, 21),
    "ice_burst": (70, 22),
    "smoke_blitz": (74, 23),
    "shadow_blitz": (76, 24),
    "blood_blitz": (80, 25),
    "ice_blitz": (82, 26),
    "smoke_barrage": (86, 27),
    "shadow_barrage": (88, 28),
    "blood_barrage": (92, 29),
    "ice_barrage": (94, 30),
}
SPELLS = {**ELEMENTAL_SPELLS, "iban_blast": (50, 25), **ANCIENT_SPELLS}


def accuracy_probability(attack_roll: int, defence_roll: int) -> float:
    """Ordinary positive-roll accuracy, including roll equality."""
    attack_roll, defence_roll = max(0, attack_roll), max(0, defence_roll)
    if attack_roll > defence_roll:
        return 1 - (defence_roll + 2) / (2 * (attack_roll + 1))
    return attack_roll / (2 * (defence_roll + 1))


def evaluate_loadout(
    items: Mapping[str, EquipmentDefinition] | Sequence[EquipmentDefinition],
    role: Any,
    levels: Mapping[str, int],
    target: CombatTarget | None = None,
    stance: str = "accurate",
    spell: str = "fire_strike",
) -> CombatPerformance:
    """Calculate one legal ordinary attack, or return explicit limitations."""
    return evaluate_prepared_loadout(prepare_equipment(items), role, levels, target, stance, spell)


def evaluate_prepared_loadout(
    prepared: PreparedEquipment,
    role: Any,
    levels: Mapping[str, int],
    target: CombatTarget | None = None,
    stance: str = "accurate",
    spell: str = "fire_strike",
) -> CombatPerformance:
    """Reuse immutable bonus totals while retaining all ordinary attack checks."""
    equipment = prepared.equipment
    style = role if isinstance(role, str) else role.style
    stance = getattr(role, "stance", stance)
    spell = getattr(role, "spell", spell)
    powered_attack = getattr(role, "powered_attack", None)
    target = target or getattr(role, "target", None) or CombatTarget()
    weapon = prepared.weapon
    bonuses = prepared.ranged_bonuses if style == "ranged" else prepared.bonuses
    problems = list(target.unsupported_mechanics)
    problems.extend(effect for item in equipment for effect in item.unsupported_effects)
    if len({i.slot for i in equipment}) != len(equipment):
        problems.append("Multiple items occupy one equipment slot.")
    if style not in {"stab", "slash", "crush", "ranged", "magic"}:
        problems.append("Special attack utility is not scored.")
    if weapon and style != "magic" and style not in weapon.attack_styles:
        problems.append(f"{weapon.name} cannot use the selected {style} attack.")
    if (
        weapon
        and style != "magic"
        and weapon.attack_profiles
        and (style, stance) not in weapon.attack_profiles
    ):
        problems.append("Selected weapon attack type and stance are incompatible.")
    if not weapon and style in {"stab", "slash", "ranged"}:
        problems.append("The selected attack requires a compatible weapon.")
    if weapon and weapon.two_handed and any(i.slot == "shield" for i in equipment):
        problems.append("Two-handed weapon cannot be equipped with a shield.")
    ammo = prepared.ammunition
    if (
        style == "ranged"
        and weapon
        and weapon.ammo_for
        and (not ammo or ammo.ammo_type not in weapon.ammo_for)
    ):
        problems.append("Compatible ammunition is required.")
    if stance not in {"accurate", "aggressive", "controlled", "defensive", "rapid", "longrange"}:
        problems.append("Unsupported attack stance.")
    if style == "ranged" and stance not in {"accurate", "rapid", "longrange"}:
        problems.append("Illegal ranged stance.")
    if style in {"stab", "slash", "crush"} and stance in {"rapid", "longrange"}:
        problems.append("Illegal melee stance.")
    needed = ("attack", "strength") if style in {"stab", "slash", "crush"} else (style,)
    if any(levels.get(key, 0) < 1 for key in needed):
        problems.append("Required combat levels are unknown.")
    if (
        style == "magic"
        and powered_attack is not None
        and (
            weapon is None
            or weapon.powered_attack != powered_attack
            or weapon.powered_attack_base_max_hit is None
        )
    ):
        problems.append("Powered attack is not supported by this weapon.")
    if (
        style == "magic"
        and powered_attack is None
        and (spell not in SPELLS or levels.get("magic", 0) < SPELLS[spell][0])
    ):
        problems.append("Selected spell is unknown or its Magic level is unmet.")
    if style == "magic" and powered_attack is None and weapon and weapon.powered_attack:
        problems.append("Powered weapon cannot autocast the selected standard spell.")
    if (
        style == "magic"
        and powered_attack is None
        and spell in ANCIENT_SPELLS
        and (weapon is None or spell not in weapon.spell_compatibility)
    ):
        problems.append("Ancient Magicks requires a reviewed compatible autocast weapon.")
    if (
        style == "magic"
        and powered_attack is None
        and spell == "iban_blast"
        and (weapon is None or weapon.id not in IBAN_STAVES)
    ):
        problems.append("Iban Blast requires Iban's staff or Iban's staff (u).")
    if (
        style == "magic"
        and powered_attack is None
        and weapon
        and weapon.spell_compatibility
        and spell not in weapon.spell_compatibility
    ):
        problems.append("Weapon cannot autocast the selected standard spell.")
    if style == "magic" and powered_attack is None and stance not in {"accurate", "defensive"}:
        problems.append("Illegal standard-spell casting stance.")
    if (
        style == "magic"
        and powered_attack is not None
        and weapon
        and (stance not in weapon.powered_attack_stances)
    ):
        problems.append("Illegal powered-attack casting stance.")
    if problems:
        return CombatPerformance(
            supported=False, limitations=tuple(dict.fromkeys(problems)), bonuses=bonuses
        )
    return _calculate(weapon, style, levels, target, stance, spell, bonuses, powered_attack)


def _calculate(
    weapon: EquipmentDefinition | None,
    style: str,
    levels: Mapping[str, int],
    target: CombatTarget,
    stance: str,
    spell: str,
    bonuses: EquipmentBonuses,
    powered_attack: str | None,
) -> CombatPerformance:
    speed = weapon.attack_speed if weapon else 4
    weakness = None
    if style == "magic":
        if powered_attack is not None:
            # Powered attack metadata provides the base hit; all other rolls use
            # the same ordinary magic model as standard spells.
            if weapon is None or weapon.powered_attack_base_max_hit is None:
                raise ValueError("Powered attack requires reviewed weapon damage metadata")
            base = weapon.powered_attack_base_max_hit
        elif spell == "iban_blast" or spell in ANCIENT_SPELLS:
            base = SPELLS[spell][1]
        else:
            tier = spell.split("_")[1]
            base = max(
                damage
                for name, (level, damage) in ELEMENTAL_SPELLS.items()
                if name.endswith("_" + tier) and level <= levels["magic"]
            )
        max_hit = floor(base * (100 + bonuses.magic_damage) / 100)
        attack = (levels["magic"] + 9 + (2 if stance == "accurate" else 0)) * (bonuses.magic + 64)
        element = (
            spell.split("_")[0] if powered_attack is None and spell in ELEMENTAL_SPELLS else None
        )
        if element == "wind":
            element = "air"
        applied = (
            element is not None
            and element == target.weakness_element
            and target.weakness_percent > 0
        )
        hit_bonus = base * target.weakness_percent // 100 if applied else 0
        roll_bonus = attack * target.weakness_percent // 100 if applied else 0
        weakness = ElementalWeakness(
            element=target.weakness_element,
            percent=target.weakness_percent,
            applied=applied,
            reason=None
            if applied
            else (
                "Target has no active elemental weakness."
                if target.weakness_element is None or target.weakness_percent == 0
                else "Powered attacks do not receive elemental weakness bonuses."
                if powered_attack is not None
                else "Selected spell does not match the target's element."
            ),
            max_hit_bonus=hit_bonus,
            attack_roll_bonus=roll_bonus,
        )
        if applied:
            # Weakness adds a separately truncated fraction of the unmodified
            # spell damage and base accuracy roll; it does not multiply gear%.
            max_hit += hit_bonus
            attack += roll_bonus
        defence = (target.magic_level + 9) * (target.bonuses.magic + 64)
        speed = weapon.attack_speed if powered_attack is not None and weapon else 5
    else:
        is_ranged = style == "ranged"
        skill = "ranged" if is_ranged else "attack"
        attack_stance = 3 if stance == "accurate" else int(stance == "controlled")
        strength_stance = (
            0 if is_ranged else 3 if stance == "aggressive" else int(stance == "controlled")
        )
        if is_ranged and stance == "accurate":
            strength_stance = 3
        effective_strength = levels["ranged" if is_ranged else "strength"] + 8 + strength_stance
        strength_bonus = bonuses.ranged_strength if is_ranged else bonuses.melee_strength
        max_hit = floor(0.5 + effective_strength * (strength_bonus + 64) / 640)
        attack = (levels[skill] + 8 + attack_stance) * (getattr(bonuses, style) + 64)
        defence = (target.defence_level + 9) * (getattr(target.bonuses, style) + 64)
        if is_ranged:
            # Ordinary bows use standard defence; ordinary crossbows heavy,
            # thrown weapons light. Generic zero bonuses apply to every subtype.
            kind = (
                "heavy"
                if weapon and weapon.ammo_for and weapon.ammo_for[0].startswith("bolt:")
                else "standard"
                if weapon and weapon.ammo_for
                else "light"
            )
            value = getattr(target, "ranged_" + kind)
            if value is not None:
                defence = (target.defence_level + 9) * (value + 64)
        if is_ranged and stance == "rapid":
            speed = max(1, speed - 1)
    if target.damage_cap is not None and max_hit > target.damage_cap:
        return CombatPerformance(
            supported=False,
            bonuses=bonuses,
            limitations=(
                "Damage above the target cap requires an unsupported reroll distribution.",
            ),
        )
    max_hit = max(0, max_hit)
    accuracy = accuracy_probability(attack, defence)
    expected = max_hit / 2 + 1 / (max_hit + 1)
    interval = speed * 0.6
    return CombatPerformance(
        supported=True,
        elemental_weakness=weakness,
        accuracy=accuracy,
        max_hit=max(1, max_hit),
        attack_interval=interval,
        dps=accuracy * expected / interval,
        attack_roll=attack,
        defence_roll=defence,
        bonuses=bonuses,
        limitations=("No prayers, boosts, combat downtime or consumable endurance are modeled.",)
        + (
            (
                "Single-target direct damage only; Ancient healing, poison, stat drains, "
                "freezes and area damage are not modeled.",
            )
            if style == "magic" and powered_attack is None and spell in ANCIENT_SPELLS
            else ()
        ),
    )
