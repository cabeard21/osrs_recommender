"""One-time immutable request preparation for native ordinary combat scoring."""

from __future__ import annotations

from array import array
from copy import copy
from math import isfinite
from types import MappingProxyType
from typing import Any

from tracker.gear.ammo import CAPE_RECOVERY
from tracker.gear.ammo_armour import COMPATIBLE_BODIES, INTERFERING_BODIES
from tracker.gear.combat_options import CombatOption, ancient_spell_problem
from tracker.gear.compact_states import SLOT_NAMES
from tracker.gear.models import CombatTarget, EquipmentBonuses
from tracker.gear.prayers import effects
from tracker.gear.prepared_combat import PreparedCombat

BONUS_FIELDS = tuple(EquipmentBonuses.model_fields)
STYLE_CODES = {"stab": 0, "slash": 1, "crush": 2, "ranged": 3, "magic": 4, "special": 5}
PRIORITIES = {
    "default": 0,
    "balanced_defence": 1,
    "magic_ranged_defence": 2,
    "accuracy": 3,
    **{
        name: 4 + BONUS_FIELDS.index(field)
        for name, field in {
            "stab_defence": "defence_stab",
            "slash_defence": "defence_slash",
            "crush_defence": "defence_crush",
            "ranged_defence": "defence_ranged",
            "magic_defence": "defence_magic",
            "prayer_bonus": "prayer",
            "melee_strength_bonus": "melee_strength",
            "ranged_strength_bonus": "ranged_strength",
            "magic_damage_bonus": "magic_damage",
        }.items()
    },
    **{
        name + "_defence_roll": 20 + index
        for index, name in enumerate(
            ("balanced", "magic_ranged", "stab", "slash", "crush", "ranged", "magic")
        )
    },
}
OPTION_WIDTH = 18


def support_reason(search: Any) -> str | None:
    if not 1 <= len(search.request.roles) <= 4:
        return "role_count"
    if search.request.secondary_priority not in PRIORITIES:
        return "secondary_priority"
    if any(role.style not in STYLE_CODES for role in search.request.roles):
        return "discipline"
    if any(getattr(role, "allowed_disciplines", None) for role in search.request.roles):
        return "unresolved_discipline"
    styles = {role.style for role in search.request.roles}
    # These effects depend on equipped neck/shield/ammunition, which the native
    # attack records do not encode. Fall back before packing or expanding states.
    candidates = [search.items[item_id] for item_id in search.eligible]
    if "magic" in styles and any(
        item.elemental_spell_bonus or item.tome_effect for item in candidates
    ):
        return "equipment_spell_effect"
    if "ranged" in styles:
        if any(item.bolt_effect or item.id == 32879 for item in candidates):
            return "equipment_ranged_effect"
        if any(item.id in CAPE_RECOVERY for item in candidates) and any(
            item.slot == "body" and item.id not in COMPATIBLE_BODIES | INTERFERING_BODIES
            for item in candidates
        ):
            return "unreviewed_body_recovery"
    needed = {
        key
        for role in search.request.roles
        if role.style != "special"
        for key in ((role.style,) if role.style in {"ranged", "magic"} else ("attack", "strength"))
    }
    if any(search.levels.get(key, 0) < 1 for key in needed):
        return "unknown_combat_levels"
    if any(abs(int(value)) > 10000 for value in search.levels.values()):
        return "level_range"
    for item_id, item in search.items.items():
        if item_id > 2**63 - 1 or item.slot not in SLOT_NAMES:
            return "catalog_identity"
        if any(
            not isfinite(getattr(item.bonuses, field))
            or abs(getattr(item.bonuses, field)) > 1000000
            for field in BONUS_FIELDS
        ):
            return "bonus_range"
        if item.attack_speed > 10000:
            return "attack_speed"
        if (
            item.powered_attack_base_max_hit is not None
            and item.powered_attack_base_max_hit > 10000
        ):
            return "powered_damage_range"
    for role in search.request.roles:
        target = role.target or CombatTarget()
        if target.damage_cap is not None and target.damage_cap > 2**63 - 1:
            return "damage_cap_range"
        if any(abs(value) > 1000000 for value in target.bonuses.model_dump().values()):
            return "target_bonus_range"
        if any(
            value is not None and abs(value) > 1000000
            for value in (target.ranged_light, target.ranged_standard, target.ranged_heavy)
        ):
            return "target_bonus_range"
    return None


def _legal(weapon: Any, role: Any, levels: Any, snapshot: Any = None) -> bool:
    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.scoring import prepare_equipment

    if role.style == "special":
        return False
    if (
        snapshot is not None
        and role.style == "magic"
        and role.powered_attack is None
        and ancient_spell_problem(weapon, snapshot, role.spell, role.stance, levels)
    ):
        return False
    # The outgoing legality checks depend only on the weapon/role. Suppress the
    # candidate-dependent cap while preparing; compiled scoring checks it later.
    target = (role.target or CombatTarget()).model_copy(update={"damage_cap": None})
    configured = role.model_copy(update={"target": target})
    # Required ranged ammunition is validated per candidate in the native loop.
    checked = weapon.model_copy(update={"ammo_for": ()}) if weapon else None
    return evaluate_prepared_score(
        prepare_equipment([checked] if checked else []), configured, levels
    ).supported


def pack(search: Any) -> dict[str, Any]:
    """Pack dense immutable contexts; no request-specific callbacks survive this step."""
    reason = support_reason(search)
    if reason:
        raise ValueError(f"native_search_unsupported: {reason}")
    dense_ids = (0, *sorted(search.items))
    dense_index = {item_id: index for index, item_id in enumerate(dense_ids)}
    names = sorted(
        {
            value
            for item in search.items.values()
            for value in (*item.ammo_for, item.ammo_type)
            if value is not None
        }
    )
    ammo_type = {name: index + 1 for index, name in enumerate(names)}
    integers: dict[str, array[int]] = {
        name: array("i", [initial])
        for name, initial in (
            ("item_slots", -1),
            ("two_handed", 0),
            ("eligible", 1),
            ("bad_items", 0),
            ("ammo_required", 0),
            ("ammo_types", 0),
        )
    }
    bonuses = array("q", [0] * 14)
    magic_damage = array("d", [0.0])
    ammo_offsets, ammo_codes = array("i", [0, 0]), array("i")
    for item_id in dense_ids[1:]:
        item = search.items[item_id]
        values = {
            "item_slots": SLOT_NAMES.index(item.slot),
            "two_handed": int(item.two_handed),
            "eligible": int(item_id in search.eligible),
            "bad_items": int(bool(item.unsupported_effects)),
            "ammo_required": int(bool(item.ammo_for)),
            "ammo_types": ammo_type.get(item.ammo_type, 0),
        }
        for name, value in values.items():
            integers[name].append(value)
        bonuses.extend(
            0 if field == "magic_damage" else getattr(item.bonuses, field) for field in BONUS_FIELDS
        )
        magic_damage.append(item.bonuses.magic_damage)
        ammo_codes.extend(ammo_type[name] for name in item.ammo_for)
        ammo_offsets.append(len(ammo_codes))

    role_count, item_count = len(search.request.roles), len(dense_ids)
    offsets, lengths = array("i"), array("i")
    options = array("q")
    option_records: list[tuple[Any, CombatOption]] = []
    option_weapons: list[int] = []
    context = PreparedCombat(0)
    fixed_roles = array(
        "i",
        [
            int(role.combat_options is None and role.prayers.mode == "disabled")
            for role in search.request.roles
        ],
    )
    for metric in (False, True):
        lane = copy(search)
        lane.metric_first = metric
        for role_index, role in enumerate(search.request.roles):
            for weapon_id in dense_ids:
                weapon = search.items.get(weapon_id)
                records: tuple[tuple[Any, CombatOption], ...] = ()
                if role.style != "special" and (weapon is None or weapon.slot == "weapon"):
                    records = (
                        (
                            (
                                role,
                                CombatOption(
                                    attack_type=role.style,
                                    stance=role.stance,
                                    spell=role.spell
                                    if role.style == "magic" and role.powered_attack is None
                                    else None,
                                    powered_attack=role.powered_attack,
                                ),
                            ),
                        )
                        if fixed_roles[role_index]
                        else lane.scoring_options(role, weapon)
                    )
                offsets.append(len(option_records))
                lengths.append(len(records))
                ties = [
                    (
                        option.attack_type,
                        option.stance,
                        option.spell or "",
                        -len(configured.active_prayer_ids),
                        tuple(reversed(configured.active_prayer_ids)),
                    )
                    for configured, option in records
                ]
                ranks = {tie: rank for rank, tie in enumerate(sorted(set(ties)))}
                for (configured, option), tie in zip(records, ties, strict=True):
                    option_weapons.append(weapon_id)
                    target = configured.target or CombatTarget()
                    legal = _legal(
                        weapon, configured, search.levels, getattr(search, "snapshot", None)
                    )
                    constants = (
                        context.prepare(
                            weapon,
                            configured.style,
                            search.levels,
                            target,
                            configured.stance,
                            configured.spell,
                            configured.powered_attack,
                            effects(configured.active_prayer_ids),
                        )
                        if legal
                        else None
                    )
                    if constants is None:
                        options.extend(
                            (
                                STYLE_CODES[configured.style],
                                0,
                                0,
                                0,
                                1,
                                0,
                                0,
                                -1,
                                ranks[tie],
                                0,
                                0,
                                0,
                                0,
                                0,
                                0,
                                0,
                                -1,
                                -1,
                            )
                        )
                        option_records.append((configured, option))
                        continue
                    options.extend(
                        (
                            STYLE_CODES[configured.style],
                            constants.attack_level,
                            constants.strength_level,
                            constants.defence_roll,
                            constants.speed,
                            {"single": 0, "independent_double": 1, "conditional_double": 2}[
                                constants.pattern
                            ],
                            constants.armour,
                            constants.damage_cap if constants.damage_cap is not None else -1,
                            ranks[tie],
                            int(legal),
                            constants.spell_base,
                            constants.magic_damage,
                            int(constants.shadow),
                            constants.weakness_percent if constants.weakness_applied else 0,
                            constants.weakness_hit,
                            int(constants.sanguinesti),
                            constants.player_defence.physical
                            if constants.player_defence.physical is not None
                            else -1,
                            constants.player_defence.magical
                            if constants.player_defence.magical is not None
                            else -1,
                        )
                    )
                    option_records.append((configured, option))
    return {
        **integers,
        "dense_ids": dense_ids,
        "dense_index": MappingProxyType(dense_index),
        "original_ids": array("q", dense_ids),
        "item_bonuses": bonuses,
        "item_magic_damage": magic_damage,
        "ammo_offsets": ammo_offsets,
        "ammo_codes": ammo_codes,
        "offsets": offsets,
        "lengths": lengths,
        "options": options,
        "option_records": tuple(option_records),
        "option_weapons": tuple(option_weapons),
        "fixed_roles": fixed_roles,
        "role_styles": array("i", [STYLE_CODES[role.style] for role in search.request.roles]),
        "priority": PRIORITIES[search.request.secondary_priority],
        "item_count": item_count,
        "role_count": role_count,
    }
