"""Shared exact physical-loadout validation and ordinary-attack evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tracker.gear.combat import evaluate_loadout
from tracker.gear.models import CombatPerformance, EquipmentDefinition


def equipment_problems(
    equipment: Mapping[str, int], items: Mapping[int, EquipmentDefinition]
) -> tuple[str, ...]:
    problems = []
    for slot, item_id in equipment.items():
        item = items.get(item_id)
        if item is None:
            problems.append(f"Unknown physical item ID: {item_id}.")
        elif item.slot != slot:
            problems.append(f"Physical item {item_id} does not occupy {slot}.")
    weapon = items.get(equipment.get("weapon", -1))
    if weapon and weapon.two_handed and "shield" in equipment:
        problems.append("Two-handed weapon cannot be equipped with a shield.")
    return tuple(problems)


def evaluate_equipment(
    equipment: Mapping[str, int],
    items: Mapping[int, EquipmentDefinition],
    role: Any,
    levels: Mapping[str, int],
) -> CombatPerformance:
    """Validate concrete slots and reuse the authoritative combat model unchanged."""
    problems = equipment_problems(equipment, items)
    if problems:
        return CombatPerformance(supported=False, limitations=problems)
    return evaluate_loadout({slot: items[i] for slot, i in equipment.items()}, role, levels)
