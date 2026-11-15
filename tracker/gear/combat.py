"""Ordinary auto-attack model; unsupported mechanics fail closed.

Reviewed active stat prayers are supported; special attacks and set effects are not approximated.
Accurate zero-damage rolls become one; target magic defence uses Magic level.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import floor
from time import perf_counter
from typing import Any, Literal, NamedTuple

from tracker.gear import hopper
from tracker.gear.bolts import expected_bolt_damage
from tracker.gear.defensive_rolls import player_defence_rolls, raw_player_defence_rolls
from tracker.gear.demonbane import SPELLS as DEMONBANE_SPELLS
from tracker.gear.demonbane import WEAPON_BONUSES
from tracker.gear.elemental_amulets import applied_spell_bonus

__all__ = ["DEMONBANE_SPELLS"]
from tracker.gear.leafy import BROAD_AMMO, LEAF_WEAPONS
from tracker.gear.models import (
    BoltPerformance,
    CombatPerformance,
    CombatTarget,
    DemonbaneBonus,
    ElementalAmuletBonus,
    ElementalWeakness,
    EquipmentBonuses,
    EquipmentDefinition,
    HitsplatPerformance,
    HopperPerformance,
    LeafyBonus,
    SeekingArrowBonus,
    SlayerEffect,
    TomeBonus,
)
from tracker.gear.powered import base_hit, supports_powered
from tracker.gear.prayers import NO_PRAYERS, PrayerEffects, effects
from tracker.gear.prepared_combat import PreparedAttack
from tracker.gear.prepared_combat import current as prepared_combat_context
from tracker.gear.ranged_numerics import active as ranged_experiment_active
from tracker.gear.ranged_numerics import evaluate as evaluate_ranged
from tracker.gear.ranged_numerics import observer as ranged_observer
from tracker.gear.ranged_score_finalization import active as score_finalization_active
from tracker.gear.scoring import PreparedEquipment, prepare_equipment
from tracker.gear.slayer import MAGIC_DART_STAVES, dart_base, mask_factor
from tracker.gear.tomes import ASSUMPTION as TOME_ASSUMPTION
from tracker.gear.tomes import applied_tome

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
SPELLS = {
    **ELEMENTAL_SPELLS,
    "iban_blast": (50, 25),
    "magic_dart": (50, 15),
    **ANCIENT_SPELLS,
    **DEMONBANE_SPELLS,
}


MODEL_VERSION = "normal-attacks-v10-halberd-status-demonbane"

_DEFAULT_TARGET = CombatTarget()


class CombatScore(NamedTuple):
    """Immutable optimizer score, without public reporting model allocation."""

    supported: bool
    dps: float | None
    accuracy: float | None
    bonuses: EquipmentBonuses
    player_defence_rolls: Mapping[str, int | None] | None = None


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
    result = _evaluate_prepared(prepared, role, levels, target, stance, spell)
    assert isinstance(result, CombatPerformance)
    return result


def evaluate_prepared_score(
    prepared: PreparedEquipment,
    role: Any,
    levels: Mapping[str, int],
    *,
    include_defence: bool = False,
) -> CombatScore:
    """Score with identical legality/formulas, deferring rich reporting objects."""
    result = _evaluate_prepared(
        prepared, role, levels, score_only=True, include_defence=include_defence
    )
    assert isinstance(result, CombatScore)
    return result


def _evaluate_prepared(
    prepared: PreparedEquipment,
    role: Any,
    levels: Mapping[str, int],
    target: CombatTarget | None = None,
    stance: str = "accurate",
    spell: str = "fire_strike",
    *,
    score_only: bool = False,
    include_defence: bool = False,
) -> CombatPerformance | CombatScore:
    """Reuse immutable bonus totals while retaining all ordinary attack checks."""
    equipment = prepared.equipment
    style = role if isinstance(role, str) else role.style
    stance = getattr(role, "stance", stance)
    spell = getattr(role, "spell", spell)
    powered_attack = getattr(role, "powered_attack", None)
    target = target or getattr(role, "target", None) or _DEFAULT_TARGET
    weapon = prepared.weapon
    bonuses = prepared.ranged_bonuses if style == "ranged" else prepared.bonuses
    problems = list(target.unsupported_mechanics)
    from tracker.gear.status_damage import HALBERD_IDS, SERPENTINE_HEADS

    selected_head = next((item for item in equipment if item.slot == "head"), None)
    if (
        selected_head
        and selected_head.id in SERPENTINE_HEADS
        and (
            weapon is None
            or weapon.id not in HALBERD_IDS
            or style not in {"stab", "slash", "crush"}
        )
    ):
        problems.append(
            "Charged serpentine helm interactions are reviewed only with ordinary halberd attacks."
        )
    from tracker.gear.attack_reach import safe_spotting_problem

    reach_problem = safe_spotting_problem(weapon, role)
    if reach_problem:
        problems.append(reach_problem)
    bolt_family = (
        prepared.ammunition.bolt_effect
        if style == "ranged" and prepared.ammunition and weapon and weapon.ammo_for
        else None
    )
    if bolt_family == "ruby" and target.current_hitpoints is None and target.hitpoints is None:
        problems.append("Ruby bolts require target current or base hitpoints.")
    if (
        powered_attack is not None
        and not (weapon and weapon.powered_attack_model)
        and levels.get("_base_magic", levels.get("magic")) != levels.get("magic")
    ):
        problems.append("Potion-boosted powered-attack damage has not been reviewed.")
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
    if "demon" not in target.traits and (
        (style == "magic" and powered_attack is None and spell in DEMONBANE_SPELLS)
        or (style == "ranged" and weapon and weapon.id == 732)
    ):
        problems.append("This demonbane attack requires a demon target.")
    if weapon and weapon.id == 732 and "holy_water_special" in target.traits:
        problems.append("Holy water special target damage rules are unsupported.")
    if style == "magic" and powered_attack is None and spell in DEMONBANE_SPELLS:
        if weapon is None or spell not in weapon.spell_compatibility:
            problems.append("Demonbane spells require a reviewed compatible autocast weapon.")
        if getattr(role, "mark_of_darkness", False) and levels.get("magic", 0) < 59:
            problems.append("Maintained Mark of Darkness requires 59 Magic.")
    if "leafy" in target.traits:
        valid_leafy = (
            (
                style in {"stab", "slash", "crush"}
                and weapon is not None
                and weapon.id in LEAF_WEAPONS
            )
            or (
                style == "ranged"
                and weapon is not None
                and bool(weapon.ammo_for)
                and ammo is not None
                and ammo.id in BROAD_AMMO
                and ammo.ammo_type in weapon.ammo_for
            )
            or (style == "magic" and powered_attack is None and spell == "magic_dart")
        )
        if not valid_leafy:
            problems.append(
                "Leafy targets require leaf-bladed melee weapons, "
                "compatible broad ammunition, or Magic Dart."
            )
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
            or not supports_powered(weapon)
        )
    ):
        problems.append("Powered attack is not supported by this weapon.")
    if (
        powered_attack is not None
        and weapon
        and weapon.powered_attack_model == "bone"
        and "rat" not in target.traits
    ):
        problems.append("Bone staff requires a confirmed rat target.")
    if (
        style == "magic"
        and powered_attack is None
        and (spell not in SPELLS or levels.get("magic", 0) < SPELLS[spell][0])
    ):
        problems.append("Selected spell is unknown or its Magic level is unmet.")
    if style == "magic" and powered_attack is None and spell == "magic_dart":
        if weapon is None or weapon.id not in MAGIC_DART_STAVES:
            problems.append("Magic Dart requires a reviewed compatible staff.")
        if levels.get("slayer", 0) < 55:
            problems.append("Magic Dart requires 55 Slayer.")
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
        if score_only:
            return CombatScore(False, None, None, bonuses)
        return CombatPerformance(
            supported=False,
            limitations=tuple(
                dict.fromkeys(
                    [*problems, *(effect for i in equipment for effect in i.omitted_set_effects)]
                )
            ),
            bonuses=bonuses,
        )
    cached_ranged = style == "ranged" and powered_attack is None and ranged_experiment_active()
    # Cached ranged scores consume Outgoing directly. Preparing a second attack
    # record adds no numerical work reuse; full reports still reuse defence data.
    preparation = None if cached_ranged and score_only else prepared_combat_context()
    constants = (
        preparation.prepare_role(weapon, role, levels, target) if preparation is not None else None
    )
    result = _calculate(
        weapon,
        style,
        levels,
        target,
        stance,
        spell,
        bonuses,
        powered_attack,
        constants.prayers
        if constants is not None
        else effects(getattr(role, "active_prayer_ids", ())),
        score_only=score_only,
        include_defence=include_defence,
        _constants=constants,
        _cached_ranged=cached_ranged,
        amulet=next((item for item in equipment if item.slot == "neck"), None),
        tome=next((item for item in equipment if item.slot == "shield"), None),
        fire_tome_pages=getattr(role, "fire_tome_pages", "burnt"),
        hopper_active=(
            style == "ranged"
            and hopper.active(
                weapon, next((i for i in equipment if i.slot == "shield"), None), ammo
            )
        ),
        bolt_family=bolt_family,
        bolt_diary=bool(getattr(role, "bolt_diary_boost", False)),
        bolt_diary_known=bool(getattr(role, "bolt_diary_known", False)),
        mark_of_darkness=bool(getattr(role, "mark_of_darkness", False)),
        on_slayer_task=bool(getattr(role, "on_slayer_task", False)),
        status_duration=getattr(role, "fight_duration_seconds", 60),
        head=next((item for item in equipment if item.slot == "head"), None),
        seeking=bool(
            style == "ranged"
            and weapon
            and weapon.ammo_for
            and ammo
            and ammo.id == 33601
            and ammo.ammo_type in weapon.ammo_for
        ),
    )
    if not score_only and isinstance(result, CombatPerformance):
        omissions = tuple(dict.fromkeys(e for i in equipment for e in i.omitted_set_effects))
        if omissions:
            return result.model_copy(
                update={"limitations": tuple(dict.fromkeys((*result.limitations, *omissions)))}
            )
    return result


def _armoured_mean(maximum: int, armour: int, accurate_floor: int = 1) -> float:
    """Exact mean after raising accurate zeroes, subtracting armour and flooring.

    The zero roll contributes the same damage as a one roll; the remaining
    positive rolls form an arithmetic progression. No damage outcomes are
    enumerated in this optimizer hot path.
    """
    if accurate_floor == 1:
        first = max(1, armour + 1)
        count = max(0, maximum - first + 1)
        positive_sum = count * (first + maximum - 2 * armour) / 2
        return (max(0, 1 - armour) + positive_sum) / (maximum + 1)
    repeated = min(maximum, accurate_floor) + 1
    first = max(accurate_floor + 1, armour + 1)
    count = max(0, maximum - first + 1)
    return (
        repeated * max(0, accurate_floor - armour) + count * (first + maximum - 2 * armour) / 2
    ) / (maximum + 1)


def _linear_floor_sum(count: int, modulus: int, multiplier: int) -> int:
    """Sum floor(multiplier * i / modulus) for i in range(count)."""
    offset = 0
    result = 0
    while True:
        result += (count - 1) * count * (multiplier // modulus) // 2
        multiplier %= modulus
        result += count * (offset // modulus)
        offset %= modulus
        upper = multiplier * count + offset
        if upper < modulus:
            return result
        count, offset = divmod(upper, modulus)
        modulus, multiplier = multiplier, modulus


def _marked_damage_total(maximum: int, percent: int, vulnerability: int) -> int:
    """Exact post-roll Mark total, including accurate-zero promotion."""
    divisor = 100 // percent  # reviewed Mark bonuses are 25% or 50%
    quotient, remainder = divmod(maximum, divisor)
    bonus = divisor * _linear_floor_sum(quotient, 100, vulnerability)
    bonus += (remainder + 1) * (quotient * vulnerability // 100)
    return maximum * (maximum + 1) // 2 + 1 + bonus


def numeric_attack_interval(weapon: EquipmentDefinition | None, role: Any) -> float:
    """Attack interval for an already supported attack, without a rich report."""
    speed = weapon.attack_speed if weapon else 4
    if role.style == "magic" and getattr(role, "powered_attack", None) is None:
        speed = 5
    elif role.style == "ranged" and role.stance == "rapid":
        speed = max(1, speed - 1)
    return speed * 0.6


def _calculate(
    weapon: EquipmentDefinition | None,
    style: str,
    levels: Mapping[str, int],
    target: CombatTarget,
    stance: str,
    spell: str,
    bonuses: EquipmentBonuses,
    powered_attack: str | None,
    prayers: PrayerEffects = NO_PRAYERS,
    *,
    score_only: bool = False,
    include_defence: bool = False,
    _constants: PreparedAttack | None = None,
    _cached_ranged: bool | None = None,
    amulet: EquipmentDefinition | None = None,
    tome: EquipmentDefinition | None = None,
    fire_tome_pages: Literal["burnt", "searing"] = "burnt",
    hopper_active: bool = False,
    bolt_family: str | None = None,
    bolt_diary: bool = False,
    bolt_diary_known: bool = False,
    mark_of_darkness: bool = False,
    on_slayer_task: bool = False,
    head: EquipmentDefinition | None = None,
    seeking: bool = False,
    status_duration: int = 60,
) -> CombatPerformance | CombatScore:
    from tracker.gear.models import StatusDamage
    from tracker.gear.status_damage import application_chance, expected_damage, status_kind

    proc = application_chance(weapon.id if weapon else None, head.id if head else None, style)
    speed = weapon.attack_speed if weapon else 4
    leafy_axe = bool(
        weapon
        and weapon.id == 20727
        and style in {"stab", "slash", "crush"}
        and "leafy" in target.traits
    )
    demon = "demon" in target.traits
    demon_spell = (
        style == "magic" and powered_attack is None and spell in DEMONBANE_SPELLS and demon
    )
    weapon_percent = (
        WEAPON_BONUSES.get(weapon.id, 0) if weapon and demon and style != "magic" else 0
    )
    holy_water = bool(weapon and weapon.id == 732 and style == "ranged")
    vulnerability = target.demonbane_vulnerability_percent
    demon_accuracy = (
        ((40 if mark_of_darkness else 20) * (2 if weapon and weapon.id == 29594 else 1))
        if demon_spell
        else (0 if holy_water else weapon_percent)
    )
    demon_damage = (
        ((50 if weapon and weapon.id == 29594 else 25) if mark_of_darkness else 0)
        if demon_spell
        else weapon_percent
    )
    effective_accuracy = demon_accuracy * vulnerability // 100
    effective_damage = demon_damage * vulnerability // 100
    demon_report = (
        DemonbaneBonus(
            item_id=weapon.id if weapon else None,
            spell=spell if demon_spell else None,
            accuracy_percent=demon_accuracy,
            damage_percent=demon_damage,
            vulnerability_percent=vulnerability,
            mark_of_darkness=bool(demon_spell and mark_of_darkness),
        )
        if (weapon_percent or demon_spell) and not score_only
        else None
    )
    accurate_floor = 3 if seeking else 1
    weakness = None
    amulet_report = None
    tome_report = None
    minimum_hit = 0
    outgoing = None
    numerator, denominator = mask_factor(head.slayer_bonus if head else None, style, on_slayer_task)
    task_mask = numerator != denominator
    slayer_reports: tuple[SlayerEffect, ...] = ()
    if not score_only and task_mask and head is not None:
        slayer_reports = (
            SlayerEffect(
                item_id=head.id,
                kind="mask",
                accuracy_numerator=numerator,
                damage_numerator=numerator,
                denominator=denominator,
            ),
        )
    # Equipment-dependent spell effects are absent from the prepared attack key.
    # Keep their reviewed calculation until those dependencies are factored too.
    spell_effect = style == "magic" and (
        applied_spell_bonus(amulet, spell, powered_attack)
        or applied_tome(tome, spell, powered_attack)
    )
    spell_effect = (
        spell_effect
        or task_mask
        or leafy_axe
        or weapon_percent
        or demon_spell
        or holy_water
        or (style == "magic" and spell == "magic_dart")
    )
    constants = None if spell_effect else _constants
    cached_ranged = (
        style == "ranged" and powered_attack is None and ranged_experiment_active()
        if _cached_ranged is None
        else _cached_ranged
    )
    preparation = (
        prepared_combat_context()
        if constants is None and not cached_ranged and not spell_effect
        else None
    )
    cached_ranged = cached_ranged and not (weapon_percent or holy_water)
    if cached_ranged:
        observer = ranged_observer()
        key_started = perf_counter() if observer is not None else 0.0
        kind = (
            "heavy"
            if weapon and weapon.ammo_for and weapon.ammo_for[0].startswith("bolt:")
            else "standard"
            if weapon and weapon.ammo_for
            else "light"
        )
        subtype = getattr(target, "ranged_" + kind)
        ranged_key = (
            weapon.id if weapon else None,
            levels["ranged"],
            prayers.ranged_strength,
            prayers.ranged_accuracy,
            stance,
            bonuses.ranged_strength,
            bonuses.ranged,
            speed,
            weapon.attack_pattern if weapon else "single",
            target.defence_level,
            target.bonuses.ranged if subtype is None else subtype,
            target.flat_armour,
            target.damage_cap,
            numerator,
            denominator,
            accurate_floor,
        )
        if observer is not None:
            observer.key_seconds += perf_counter() - key_started
        outgoing = evaluate_ranged(ranged_key)
        if score_only and score_finalization_active() and not (bolt_family or hopper_active):
            if outgoing.capped:
                return CombatScore(False, None, None, bonuses)
            return CombatScore(
                True,
                outgoing.expected / (outgoing.speed * 0.6),
                outgoing.accuracy,
                bonuses,
                raw_player_defence_rolls(levels, bonuses, stance, prayers)
                if include_defence
                else None,
            )
        max_hit, attack, defence, speed = outgoing[:4]
    elif constants is not None or preparation is not None:
        if constants is None:
            assert preparation is not None
            constants = preparation.prepare(
                weapon, style, levels, target, stance, spell, powered_attack, prayers
            )
        max_hit, attack, roll_bonus = constants.rolls(bonuses)
        defence, speed = constants.defence_roll, constants.speed
        if style == "magic" and not score_only:
            weakness = ElementalWeakness(
                element=target.weakness_element,
                percent=target.weakness_percent,
                applied=constants.weakness_applied,
                reason=None
                if constants.weakness_applied
                else (
                    "Target has no active elemental weakness."
                    if target.weakness_element is None or target.weakness_percent == 0
                    else "Powered attacks do not receive elemental weakness bonuses."
                    if powered_attack is not None
                    else "Selected spell does not match the target's element."
                ),
                max_hit_bonus=constants.weakness_hit,
                attack_roll_bonus=roll_bonus,
            )
    elif style == "magic":
        if powered_attack is not None:
            # Powered attack metadata provides the base hit; all other rolls use
            # the same ordinary magic model as standard spells.
            if weapon is None or not supports_powered(weapon):
                raise ValueError("Powered attack requires reviewed weapon damage metadata")
            base = (
                base_hit(weapon.powered_attack_model, levels["magic"])
                if weapon.powered_attack_model
                else weapon.powered_attack_base_max_hit
            )
            assert base is not None
        elif spell == "magic_dart":
            base = dart_base(
                levels["magic"], bool(weapon and weapon.slayer_staff_enchanted), on_slayer_task
            )
            if not score_only and weapon and weapon.slayer_staff_enchanted and on_slayer_task:
                slayer_reports = (
                    *slayer_reports,
                    SlayerEffect(item_id=weapon.id, kind="magic_dart", base_max_hit=base),
                )
        elif spell == "iban_blast" or spell in ANCIENT_SPELLS or spell in DEMONBANE_SPELLS:
            base = SPELLS[spell][1]
        else:
            tier = spell.split("_")[1]
            base = max(
                damage
                for name, (level, damage) in ELEMENTAL_SPELLS.items()
                if name.endswith("_" + tier) and level <= levels["magic"]
            )
        amulet_bonus = applied_spell_bonus(amulet, spell, powered_attack)
        base += amulet_bonus
        if amulet_bonus and amulet is not None and not score_only:
            amulet_report = ElementalAmuletBonus(
                item_id=amulet.id,
                element=spell.split("_")[0].replace("wind", "air"),
                base_max_hit_bonus=amulet_bonus,
            )
        shadow = (
            powered_attack is not None
            and weapon is not None
            and weapon.powered_attack_model == "shadow"
        )
        damage_bonus = min(100, bonuses.magic_damage * 3) if shadow else bonuses.magic_damage
        magic_bonus = bonuses.magic * 3 if shadow else bonuses.magic
        max_hit = floor(base * (100 + damage_bonus + prayers.magic_damage) / 100)
        attack = (
            levels["magic"] * prayers.magic_accuracy // 100 + 9 + (2 if stance == "accurate" else 0)
        ) * (magic_bonus + 64)
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
        if not score_only:
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
        tome_effect = applied_tome(tome, spell, powered_attack)
        if task_mask:
            max_hit = max_hit * numerator // denominator
            attack = attack * numerator // denominator
        if tome_effect and tome_effect.element == "water":
            attack = attack * 120 // 100
        if applied:
            # Weakness adds a separately truncated fraction of the unmodified
            # spell damage and base accuracy roll; it does not multiply gear%.
            max_hit += hit_bonus
            attack += roll_bonus
        if tome_effect:
            minimum_hit = (
                max_hit // 10
                if tome_effect.element == "fire" and fire_tome_pages == "searing"
                else 0
            )
            max_hit = max_hit * 110 // 100
            if not score_only and tome is not None:
                tome_report = TomeBonus(
                    item_id=tome.id,
                    element=tome_effect.element,
                    damage_percent=10,
                    accuracy_percent=20 if tome_effect.element == "water" else 0,
                    fire_pages=fire_tome_pages if tome_effect.element == "fire" else None,
                    minimum_hit=max(1, minimum_hit),
                )
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
        effective_strength = (
            levels["ranged" if is_ranged else "strength"]
            * (prayers.ranged_strength if is_ranged else prayers.strength)
            // 100
            + 8
            + strength_stance
        )
        strength_bonus = bonuses.ranged_strength if is_ranged else bonuses.melee_strength
        max_hit = floor(0.5 + effective_strength * (strength_bonus + 64) / 640)
        attack = (
            levels[skill] * (prayers.ranged_accuracy if is_ranged else prayers.attack) // 100
            + 8
            + attack_stance
        ) * (getattr(bonuses, style) + 64)
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
    if holy_water:
        assert weapon is not None
        max_hit = floor(0.5 + (levels["ranged"] + 10) * (weapon.bonuses.ranged_strength + 64) / 640)
    if style != "magic" and not cached_ranged and task_mask:
        if not holy_water:
            max_hit = (
                max_hit * (100 + 15 + effective_damage) // 100
                if weapon and weapon.id == 29591 and demon
                else max_hit * numerator // denominator
            )
        attack = attack * numerator // denominator
    if weapon_percent and not (weapon and weapon.id == 29591 and task_mask):
        max_hit += max_hit * effective_damage // 100
    if effective_accuracy:
        attack += attack * effective_accuracy // 100
    if leafy_axe:
        max_hit = max_hit * 47 // 40
    max_hit = max(0, max_hit)
    if (
        constants is not None
        and score_only
        and constants.pattern == "single"
        and not (bolt_family or hopper_active or proc)
    ):
        if (
            constants.damage_cap is not None
            and max(accurate_floor, max_hit) + (8 if constants.sanguinesti else 0)
            > constants.damage_cap
        ):
            return CombatScore(False, None, None, bonuses)
        accuracy = accuracy_probability(attack, defence)
        # Preserve the one-term sum's initial zero and the proc's operation order.
        expected = 0 + accuracy * _armoured_mean(max_hit, constants.armour, accurate_floor)
        if constants.sanguinesti:
            expected += accuracy * 0.2 * 8
        return CombatScore(
            True,
            expected / (speed * 0.6),
            accuracy,
            bonuses,
            constants.player_defence.rolls(bonuses) if include_defence else None,
        )
    sang_proc = (
        constants.sanguinesti
        if constants is not None
        else (
            powered_attack is not None
            and weapon is not None
            and weapon.powered_attack_model == "sanguinesti"
        )
    )
    pattern = (
        constants.pattern
        if constants is not None
        else (weapon.attack_pattern if weapon and style != "magic" else "single")
    )
    maxima = (max_hit,) if pattern == "single" else (max_hit // 2, max_hit - max_hit // 2)
    if target.damage_cap is not None and any(
        max(accurate_floor, m)
        + (
            (max(accurate_floor, m) * demon_damage // 100) * vulnerability // 100
            if demon_spell and mark_of_darkness
            else 0
        )
        + (8 if sang_proc else 0)
        > target.damage_cap
        for m in maxima
    ):
        if score_only:
            return CombatScore(False, None, None, bonuses)
        return CombatPerformance(
            supported=False,
            bonuses=bonuses,
            limitations=(
                "Damage above the target cap requires an unsupported reroll distribution.",
            ),
        )
    accuracy = outgoing.accuracy if outgoing else accuracy_probability(attack, defence)
    probabilities = (
        (accuracy,)
        if pattern == "single"
        else (accuracy, accuracy**2 if pattern == "conditional_double" else accuracy)
    )
    armour = (
        constants.armour
        if constants is not None
        else (target.flat_armour if style != "magic" else 0)
    )
    expected = (
        outgoing.expected
        if outgoing
        else sum(
            p * _armoured_mean(m, armour, accurate_floor)
            for m, p in zip(maxima, probabilities, strict=True)
        )
    )
    if demon_spell and mark_of_darkness:
        expected = (
            accuracy * _marked_damage_total(max_hit, demon_damage, vulnerability) / (max_hit + 1)
        )
        max_hit += (max_hit * demon_damage // 100) * vulnerability // 100
        maxima = (max_hit,)
    if minimum_hit > 0:
        expected = accuracy * (minimum_hit + max_hit) / 2
    if sang_proc:
        expected += accuracy * 0.2 * 8
    bolt_report = None
    activation = 0.0
    if bolt_family:
        ordinary_expected = expected
        hp = target.current_hitpoints if target.current_hitpoints is not None else target.hitpoints
        expected, total_max, activation = expected_bolt_damage(
            bolt_family,
            levels["ranged"],
            max_hit,
            accuracy,
            hp,
            bolt_diary,
            bool(weapon and weapon.id == 26374),
            target.traits,
            target.flat_armour,
        )
        if target.damage_cap is not None and total_max > target.damage_cap:
            if score_only:
                return CombatScore(False, None, None, bonuses)
            return CombatPerformance(
                supported=False,
                bonuses=bonuses,
                limitations=(
                    "Bolt damage above the target cap requires an unsupported reroll distribution.",
                ),
            )
        if not score_only:
            bolt_report = BoltPerformance(
                family=bolt_family,
                proc_chance={
                    "opal": 0.05,
                    "pearl": 0.06,
                    "ruby": 0.06,
                    "diamond": 0.1,
                    "dragonstone": 0.06,
                    "onyx": 0.11,
                }[bolt_family]
                * (1.1 if bolt_diary else 1),
                activation_probability=activation,
                expected_damage_per_attack=expected,
                expected_damage_delta=expected - ordinary_expected,
                total_max_hit=total_max,
                normal_max_hit=max(0, max(1, max_hit) - target.flat_armour),
                target_hitpoints=hp,
                diary_boosted=bolt_diary,
            )
    hopper_report = None
    if hopper_active:
        secondary_accuracy = accuracy_probability(attack * 2 // 3, defence)
        secondary, secondary_max, _ = hopper.expected_secondary_damage(
            bolt_family,
            levels["ranged"],
            max_hit,
            secondary_accuracy,
            target.current_hitpoints if target.current_hitpoints is not None else target.hitpoints,
            bolt_diary,
            bool(weapon and weapon.id == 26374),
            target.traits,
            armour,
            activation,
        )
        delta = hopper.PROC_CHANCE * secondary
        expected += delta
        if not score_only:
            hopper_report = HopperPerformance(
                proc_chance=hopper.PROC_CHANCE,
                secondary_accuracy=secondary_accuracy,
                secondary_max_hit=secondary_max,
                expected_damage_delta=delta,
                expected_ammunition_per_attack=1 + hopper.PROC_CHANCE,
                assumptions=hopper.ASSUMPTIONS,
            )
    interval = speed * 0.6
    affliction = (
        status_kind(target.poison_susceptibility, target.venom_susceptibility) if proc else None
    )
    # Status requires nonzero damage. Accurate zero rolls become one before armour.
    positive = 1.0 if armour < 1 else max(0, max_hit - armour) / (max_hit + 1)
    status_expected = (
        expected_damage(proc * accuracy * positive, speed, status_duration, affliction)
        if affliction in {"venom", "poison"}
        else 0.0
    )
    status_dps = status_expected / status_duration
    status_notes = (
        ("Target poison/venom susceptibility is unknown; only direct DPS is scored.",)
        if affliction == "unknown"
        else ()
    )
    if score_only:
        return CombatScore(
            True,
            expected / interval + status_dps,
            accuracy,
            bonuses,
            (
                constants.player_defence.rolls(bonuses)
                if constants is not None
                else raw_player_defence_rolls(levels, bonuses, stance, prayers)
            )
            if include_defence
            else None,
        )
    hitsplats = tuple(
        HitsplatPerformance(
            accuracy=p, max_hit=max(0, max(accurate_floor, m) - armour) + (8 if sang_proc else 0)
        )
        for m, p in zip(maxima, probabilities, strict=True)
    )
    return CombatPerformance(
        supported=True,
        demonbane_bonus=demon_report,
        slayer_effects=slayer_reports,
        leafy_bonus=LeafyBonus(item_id=20727) if leafy_axe else None,
        seeking_arrow_bonus=SeekingArrowBonus(item_id=33601) if seeking else None,
        aquanite_hopper=hopper_report,
        bolt_effect=bolt_report,
        elemental_weakness=weakness,
        elemental_amulet_bonus=amulet_report,
        tome_bonus=tome_report,
        accuracy=accuracy,
        hitsplats=hitsplats,
        max_hit=sum(h.max_hit for h in hitsplats),
        attack_interval=interval,
        dps=expected / interval + status_dps,
        direct_dps=expected / interval if proc else None,
        status_damage=StatusDamage(
            kind=affliction,
            duration_seconds=status_duration,
            expected_damage=status_expected,
            dps=status_dps,
            application_chance=proc,
            limitations=status_notes,
        )
        if affliction
        else None,
        attack_roll=attack,
        defence_roll=defence,
        player_defence_rolls=constants.player_defence.report(bonuses)
        if constants is not None
        else player_defence_rolls(levels, bonuses, stance, prayers),
        bonuses=bonuses,
        limitations=status_notes
        + (
            ("Holy water Defence drain is not simulated; fixed target stats are used.",)
            if holy_water
            else ()
        )
        + (hopper.ASSUMPTIONS if hopper_active else ())
        + (
            "Fresh combat levels and sustained active stat prayers only; "
            "no boost decay, combat downtime "
            "or consumable endurance are modeled.",
        )
        + ((TOME_ASSUMPTION,) if tome is not None and tome.tome_effect else ())
        + (
            (
                "Static target HP and sufficient player HP assumed; ruby self-damage "
                "endurance, healing and crossbow specials are not simulated.",
            )
            if bolt_family
            else ()
        )
        + (
            ("Kandarin Hard Diary completion is unknown; base bolt proc rates used.",)
            if bolt_family and not bolt_diary_known
            else ()
        )
        + (
            (
                "Ordinary generic PvM only; healing, venom, special attacks and location "
                "bonuses are not modeled. Charge availability is unknown.",
            )
            if powered_attack is not None
            else ()
        )
        + (
            ("Generic PvM only; sceptre Wilderness bonuses and special attacks are not modeled.",)
            if weapon is not None and weapon.id in {27785, 27788, 27676, 27679}
            else ()
        )
        + (
            (
                "Single-target direct damage only; Ancient healing, poison, stat drains, "
                "freezes and area damage are not modeled.",
            )
            if style == "magic" and powered_attack is None and spell in ANCIENT_SPELLS
            else ()
        ),
    )
