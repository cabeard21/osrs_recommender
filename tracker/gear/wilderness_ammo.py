"""Identify ammo-slot stacks used by the carried Wilderness loadouts."""

from collections.abc import Iterable, Mapping

from tracker.gear.facts import budget_exempt
from tracker.gear.models import EquipmentDefinition


def consumes_ammunition(
    equipment: Mapping[str, int], style: str, items: Mapping[int, EquipmentDefinition]
) -> bool:
    if style not in {"ranged", "special"}:
        return False
    weapon = items.get(equipment.get("weapon", 0))
    ammo = items.get(equipment.get("ammunition", 0))
    return bool(weapon and ammo and ammo.ammo_type in weapon.ammo_for)


def idle_ammunition(
    loadouts: Iterable[tuple[Mapping[str, int], str]], items: Mapping[int, EquipmentDefinition]
) -> set[int]:
    carried: set[int] = set()
    used: set[int] = set()
    for equipment, style in loadouts:
        ammo = items.get(equipment.get("ammunition", 0))
        if ammo is not None and ammo.slot == "ammunition" and ammo.stackable:
            carried.add(ammo.id)
            if consumes_ammunition(equipment, style, items):
                used.add(ammo.id)
    return carried - used


def only_ranged_ammunition(item: EquipmentDefinition) -> bool:
    """Equipping these stacks can only help an attack that consumes them."""
    return (
        item.slot == "ammunition"
        and item.stackable
        and budget_exempt(item)
        and item.bonuses.model_dump(exclude_defaults=True).keys() <= {"ranged", "ranged_strength"}
    )
