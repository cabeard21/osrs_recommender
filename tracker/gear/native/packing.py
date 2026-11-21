"""One-time immutable request preparation for native ordinary combat scoring."""

from __future__ import annotations

from array import array
from copy import copy
from math import isfinite
from types import MappingProxyType
from typing import Any

from tracker.gear.bolts_catalog import CROSSBOWS
from tracker.gear.combat import ELEMENTAL_SPELLS
from tracker.gear.combat_options import CombatOption, ancient_spell_problem
from tracker.gear.compact_states import SLOT_NAMES
from tracker.gear.demonbane import SPELLS as DEMONBANE_SPELLS
from tracker.gear.demonbane import WEAPON_BONUSES
from tracker.gear.dragonbane import BONUSES as DRAGONBANE_BONUSES
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.prayers import effects
from tracker.gear.prepared_combat import PreparedCombat
from tracker.gear.revenant import passive_applies
from tracker.gear.vampyre_combat import resolve as resolve_vampyre
from tracker.gear.vampyre_combat import target_tier
from tracker.gear.vampyres import EFARITAYS_AID, SILVER_BOLTS, SILVER_POISON_SEVERITY
from tracker.gear.void_ranged import ELITE_ROBES, ELITE_TOPS, RANGER_HELMS, VOID_GLOVES

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
            (
                "balanced",
                "magic_ranged",
                "stab",
                "slash",
                "crush",
                "ranged",
                "magic",
                "melee",
                "melee_magic",
                "melee_ranged",
                "stab_magic",
                "stab_ranged",
                "stab_magic_ranged",
                "slash_magic",
                "slash_ranged",
                "slash_magic_ranged",
                "crush_magic",
                "crush_ranged",
                "crush_magic_ranged",
            )
        )
    },
}
OPTION_WIDTH = 18
ELEMENT_CODES = {"air": 1, "water": 2, "earth": 3, "fire": 4}
BOLT_CODES = {
    name: index + 1
    for index, name in enumerate(("opal", "pearl", "ruby", "diamond", "dragonstone", "onyx"))
}


def support_reason(search: Any) -> str | None:
    if not 1 <= len(search.request.roles) <= 4:
        return "role_count"
    if search.request.secondary_priority not in PRIORITIES:
        return "secondary_priority"
    if any(role.style not in STYLE_CODES for role in search.request.roles):
        return "discipline"
    if any(getattr(role, "allowed_disciplines", None) for role in search.request.roles):
        return "unresolved_discipline"
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
        if item.elemental_spell_bonus and item.elemental_spell_bonus.base_max_hit_bonus > 10000:
            return "elemental_bonus_range"
        if item.size_damage_bonus and (
            not 1 <= item.size_damage_bonus.damage_per_size <= 100
            or not 1 <= item.size_damage_bonus.max_size <= 64
        ):
            return "size_bonus_range"
        if item.tome_effect and item.tome_effect.rune_id > 2**63 - 1:
            return "tome_rune_range"
        if item.attack_speed > 10000:
            return "attack_speed"
        if (
            item.powered_attack_base_max_hit is not None
            and item.powered_attack_base_max_hit > 10000
        ):
            return "powered_damage_range"
    for role in search.request.roles:
        target = role.target or CombatTarget()
        if not 0 <= target.size <= 64:
            return "target_size_range"
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
        and ancient_spell_problem(
            weapon,
            snapshot,
            role.spell,
            role.stance,
            levels,
            mark_of_darkness=getattr(role, "mark_of_darkness", False),
        )
    ):
        return False
    # The outgoing legality checks depend only on the weapon/role. Suppress the
    # candidate-dependent cap while preparing; compiled scoring checks it later.
    target = role.target or CombatTarget()
    target = target.model_copy(
        update={
            "damage_cap": None,
            # Tier legality depends on the actual ring and fired bolts.
            "traits": tuple(
                t for t in target.traits if t not in {"vampyre1", "vampyre2", "vampyre3"}
            ),
        }
    )
    configured = role.model_copy(update={"target": target})
    # Required ranged ammunition is validated per candidate in the native loop.
    if role.style == "ranged" and "leafy" in target.traits:
        if weapon is None:
            return False
        # Preserve actual compatibility while validating a representative attack.
        # The compiled loop checks the concrete candidate ammunition separately.
        broad_ids = (4160, 33601, 11875, 21316)
        for item_id in broad_ids:
            token = f"{'arrow' if item_id in (4160, 33601) else 'bolt'}:{item_id}"
            if token in weapon.ammo_for:
                ammo = EquipmentDefinition(
                    id=item_id, name="Broad ammunition scaffold", slot="ammunition", ammo_type=token
                )
                return evaluate_prepared_score(
                    prepare_equipment([weapon, ammo]), configured, levels
                ).supported
        return False
    checked = weapon.model_copy(update={"ammo_for": ()}) if weapon else None
    return evaluate_prepared_score(
        prepare_equipment([checked] if checked else []), configured, levels
    ).supported


def _vampyre_rule_rows(tier: int, style: str, weapon_id: int) -> list[int]:
    """Rows follow the V_WIDTH layout in _effects.pxd, indexed by silver and ring."""
    rows: list[int] = []
    for silver in (False, True):
        for ring in (False, True):
            rule = resolve_vampyre(tier, style, weapon_id, silver, ring)
            assert rule is not None
            rows.extend(
                (
                    int(rule.legal),
                    rule.weapon_accuracy_percent,
                    rule.ring_accuracy_percent,
                    rule.weapon_damage_percent,
                    rule.ring_damage_percent,
                    rule.damage_divisor,
                    rule.hit_cap or 0,
                )
            )
    return rows


def pack(search: Any) -> dict[str, Any]:
    """Pack dense immutable contexts; no request-specific callbacks survive this step."""
    reason = support_reason(search)
    if reason:
        raise ValueError(f"native_search_unsupported: {reason}")
    objectives = getattr(search.request, "objectives", None) or ()
    objective_ids = tuple(objective.id for objective in objectives)
    objective_kinds = array("i")
    objective_masks = array("i")
    objective_means = array("i")
    kinds = {
        "defence_roll": 0,
        "prayer_bonus": 1,
        "melee_strength_bonus": 2,
        "ranged_strength_bonus": 3,
        "magic_damage_bonus": 4,
        "accuracy": 5,
        "gp_per_damage": 6,
        "wilderness_loss_gp": 7,
    }
    if len(objectives) > 64:
        raise ValueError("Too many native objectives")
    for objective in objectives:
        objective_kinds.append(kinds[objective.kind])
        objective_masks.append(sum(1 << STYLE_CODES[style] for style in objective.styles))
        objective_means.append(int(objective.aggregation == "mean"))
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
            ("amulet_mask", 0),
            ("amulet_bonus", 0),
            ("tome_element", 0),
            ("bolt_family", 0),
            ("reviewed_crossbow", 0),
            ("zaryte", 0),
            ("hopper_shield", 0),
            ("slayer_bonus", 0),
            ("salve_bonus", 0),
            ("slayer_staff", 0),
            ("dragonbane_accuracy", 0),
            ("dragonbane_damage", 0),
            ("demonbane_weapon", 0),
            ("holy_water", 0),
            ("purging_staff", 0),
            ("scorching_bow", 0),
            ("leafy_weapon", 0),
            ("elite_void_piece", 0),
            ("broad_ammo", 0),
            ("seeking_ammo", 0),
            ("size_damage_per_size", 0),
            ("size_damage_max_size", 0),
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
            "dragonbane_accuracy": DRAGONBANE_BONUSES.get(item_id, (0, 0))[0],
            "dragonbane_damage": DRAGONBANE_BONUSES.get(item_id, (0, 0))[1],
            "demonbane_weapon": WEAPON_BONUSES.get(item_id, 0),
            "holy_water": int(item_id == 732),
            "purging_staff": int(item_id == 29594),
            "scorching_bow": int(item_id == 29591),
            "leafy_weapon": 2 if item_id == 20727 else int(item_id in {4158, 11902}),
            "elite_void_piece": int(
                (item.slot == "head" and item_id in RANGER_HELMS)
                or (item.slot == "body" and item_id in ELITE_TOPS)
                or (item.slot == "legs" and item_id in ELITE_ROBES)
                or (item.slot == "hands" and item_id in VOID_GLOVES)
            ),
            "broad_ammo": int(item_id in {4160, 33601, 11875, 21316}),
            "seeking_ammo": int(item_id == 33601),
            "size_damage_per_size": item.size_damage_bonus.damage_per_size
            if item.size_damage_bonus and item.slot == "weapon"
            else 0,
            "size_damage_max_size": item.size_damage_bonus.max_size
            if item.size_damage_bonus and item.slot == "weapon"
            else 0,
            "eligible": int(item_id in search.eligible),
            "bad_items": int(bool(item.unsupported_effects)),
            "ammo_required": int(bool(item.ammo_for)),
            "ammo_types": ammo_type.get(item.ammo_type, 0),
            "amulet_mask": sum(
                1 << ELEMENT_CODES[e] for e in set(item.elemental_spell_bonus.elements)
            )
            if item.elemental_spell_bonus and item.slot == "neck"
            else 0,
            "amulet_bonus": item.elemental_spell_bonus.base_max_hit_bonus
            if item.elemental_spell_bonus and item.slot == "neck"
            else 0,
            "tome_element": ELEMENT_CODES[item.tome_effect.element]
            if item.tome_effect and item.slot == "shield"
            else 0,
            "bolt_family": BOLT_CODES.get(item.bolt_effect, 0) if item.slot == "ammunition" else 0,
            "reviewed_crossbow": int(item_id in CROSSBOWS),
            "zaryte": int(item_id == 26374),
            "hopper_shield": int(item_id == 32879 and item.slot == "shield"),
            "slayer_bonus": (
                1 if item.slayer_bonus == "melee" else 2 if item.slayer_bonus == "all" else 0
            )
            if item.slot == "head"
            else 0,
            "salve_bonus": item.salve_bonus if item.slot == "neck" else 0,
            "slayer_staff": int(
                getattr(item, "slayer_staff_enchanted", False) and item.slot == "weapon"
            ),
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
    vampyre_rules = array("i")
    vampyre_offsets: dict[tuple[int, str, int], int] = {}
    offsets, lengths = array("i"), array("i")
    options = array("q")
    status_kinds, status_durations = array("i"), array("i")
    option_records: list[tuple[Any, CombatOption]] = []
    option_weapons: list[int] = []
    option_effects = {
        name: array("i")
        for name in (
            "spell_element",
            "searing",
            "ranged_level",
            "diary",
            "target_hp",
            "target_traits",
            "on_slayer_task",
            "wilderness_weapon",
            "magic_dart",
            "target_leafy",
            "target_poisonable",
            "vampyre_rule_offset",
            "target_size",
            "target_demon",
            "demonbane_vulnerability",
            "demonbane_spell",
            "mark_of_darkness",
            "magic_level",
        )
    }
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
            tier = target_tier(role.target.traits) if role.target else 0
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
                        else lane.configured_options(role, weapon)
                        if (objectives or role.style == "magic")
                        and hasattr(lane, "configured_options")
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
                    from tracker.gear.status_damage import status_kind

                    status_kinds.append(
                        {"venom": 1, "poison": 2}.get(
                            status_kind(target.poison_susceptibility, target.venom_susceptibility)
                            or "",
                            0,
                        )
                    )
                    status_durations.append(getattr(configured, "fight_duration_seconds", 60))
                    standard = (
                        configured.style == "magic"
                        and configured.powered_attack is None
                        and configured.spell in ELEMENTAL_SPELLS
                    )
                    element = (
                        configured.spell.split("_")[0].replace("wind", "air") if standard else None
                    )
                    metadata = {
                        "spell_element": ELEMENT_CODES.get(element or "", 0),
                        "searing": int(configured.fire_tome_pages == "searing"),
                        "on_slayer_task": int(getattr(configured, "on_slayer_task", False)),
                        "wilderness_weapon": int(
                            getattr(configured, "_in_wilderness", False)
                            and passive_applies(weapon_id, configured.style)
                        ),
                        "magic_dart": int(
                            configured.style == "magic"
                            and configured.spell == "magic_dart"
                            and configured.powered_attack is None
                        ),
                        "magic_level": search.levels.get("magic", 0),
                        "target_leafy": int("leafy" in target.traits),
                        "target_poisonable": int(target.poison_susceptibility == "susceptible"),
                        "vampyre_rule_offset": -1,
                        "target_size": target.size,
                        "target_demon": int("demon" in target.traits),
                        "demonbane_vulnerability": target.demonbane_vulnerability_percent,
                        "demonbane_spell": int(
                            configured.style == "magic"
                            and configured.powered_attack is None
                            and configured.spell in DEMONBANE_SPELLS
                        ),
                        "mark_of_darkness": int(getattr(configured, "mark_of_darkness", False)),
                        "ranged_level": search.levels.get("ranged", 0),
                        "diary": int(configured.bolt_diary_boost),
                        "target_hp": target.current_hitpoints
                        if target.current_hitpoints is not None
                        else target.hitpoints
                        if target.hitpoints is not None
                        else -1,
                        "target_traits": sum(
                            bit
                            for name, bit in (("fiery", 1), ("dragon", 2), ("undead", 4))
                            if name in target.traits
                        ),
                    }
                    if tier:
                        key = (tier, configured.style, weapon_id)
                        if key not in vampyre_offsets:
                            vampyre_offsets[key] = len(vampyre_rules)
                            vampyre_rules.extend(_vampyre_rule_rows(*key))
                        metadata["vampyre_rule_offset"] = vampyre_offsets[key]
                    for name, value in metadata.items():
                        option_effects[name].append(value)
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
    from tracker.gear.status_damage import HALBERD_IDS, SERPENTINE_HEADS

    return {
        "objective_ids": objective_ids,
        "objective_kinds": objective_kinds,
        "objective_masks": objective_masks,
        "objective_means": objective_means,
        "status_kind": status_kinds,
        "status_duration": status_durations,
        "halberd": array("i", [int(i in HALBERD_IDS) for i in dense_ids]),
        "vampyre_rules": vampyre_rules,
        "silver_bolts": array("i", (int(i in SILVER_BOLTS) for i in dense_ids)),
        "silver_poison": array("i", (SILVER_POISON_SEVERITY.get(i, 0) for i in dense_ids)),
        "efaritay": array("i", (int(i == EFARITAYS_AID) for i in dense_ids)),
        "serpentine": array("i", [int(i in SERPENTINE_HEADS) for i in dense_ids]),
        **integers,
        **option_effects,
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
