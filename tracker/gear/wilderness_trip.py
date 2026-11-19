"""Starting ammunition and loaded charges for a fixed Wilderness trip."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from tracker.gear.ammo import recovery_rate
from tracker.gear.hopper import PROC_CHANCE
from tracker.gear.hopper import active as hopper_active
from tracker.gear.models import EquipmentDefinition
from tracker.gear.ranged_resources import THROWN_IDS

if TYPE_CHECKING:
    from tracker.gear.wilderness import DeathItem


def trip_resources(
    loadouts: Mapping[str, Mapping[str, int]],
    options: Mapping[str, Mapping[str, Any] | None],
    styles: Mapping[str, str],
    items: Mapping[int, EquipmentDefinition],
    rules: Mapping[int, DeathItem],
    attacks: int,
) -> dict[int, int] | None:
    # Rates use integer basis points so rounding happens exactly once for a shared stack.
    ammo_demand: Counter[int] = Counter()
    charges: Counter[int] = Counter()
    for role, gear in loadouts.items():
        special = styles[role] == "special"
        count = 1 if special else attacks
        weapon_id = gear.get("weapon", 0)
        weapon = items.get(weapon_id)
        rule = rules.get(weapon_id)
        option = options.get(role) or {}
        attack_type = "special" if special else option.get("attack_type") or styles[role]
        if rule and rule.charge:
            # Keep a charged physical form usable even when it is only a switch.
            # A conventional staff consumes its internal charges on powered attacks.
            uses_charge = (
                special
                or option.get("powered_attack")
                or (weapon_id in {22542, 27660} and attack_type in {"stab", "slash", "crush"})
                or (
                    weapon_id in {22547, 27655}
                    and attack_type in {"ranged", "light", "standard", "heavy"}
                )
                or (weapon_id in {27788, 27679} and attack_type == "magic" and option.get("spell"))
            )
            charges[weapon_id] += count if uses_charge else 0
            continue
        if attack_type not in {"ranged", "light", "standard", "heavy", "special"}:
            continue
        if not weapon:
            return None
        if weapon.ammo_for:
            ammo = items.get(gear.get("ammunition", 0))
            if not ammo or ammo.ammo_type not in weapon.ammo_for:
                return None
            if not ammo.ammo_type or not ammo.ammo_type.startswith(("arrow:", "bolt:")):
                return None
        elif weapon.id in THROWN_IDS:
            ammo = weapon
        else:
            if special:
                continue
            # A supported ranged attack need not have a reviewed resource recipe.
            return None
        if ammo.id not in rules or not rules[ammo.id].ammo:
            return None
        recovery, _ = recovery_rate(gear.get("cape"), gear.get("body"))
        if ammo.id == 732 or special:
            recovery = 0.0
        if recovery is None:
            return None
        shots_percent = 100
        if not special and hopper_active(weapon, items.get(gear.get("shield", 0)), ammo):
            shots_percent += round(PROC_CHANCE * 100)
        ammo_demand[ammo.id] += count * shots_percent * (100 - round(recovery * 100))
    quantities = {i: max(1, (demand + 9999) // 10000) for i, demand in ammo_demand.items()}
    for item_id, used in charges.items():
        rule = rules[item_id]
        units = rule.minimum_quantity - 1 + max(1, used)
        if units > rule.maximum_quantity:
            return None
        quantities[item_id] = units
    return quantities
