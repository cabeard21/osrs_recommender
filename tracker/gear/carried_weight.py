"""Signed mass of a physical kit at each configured equipment switch."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, TypedDict

from tracker.gear.models import EquipmentDefinition

if TYPE_CHECKING:
    from tracker.gear.objectives import ObjectiveDescriptor

GearAssignment = Mapping[str, Mapping[str, int]]


def carried_weight_assumptions(objectives: Iterable[ObjectiveDescriptor] | None) -> dict[str, str]:
    if any(goal.kind == "carried_weight_kg" for goal in objectives or ()):
        return {"carried_weight_model": "heaviest-role-physical-kit-v1"}
    return {}


class UnknownGearWeight(ValueError):
    """An item has no verified mass for this calculation."""


class RoleWeight(TypedDict):
    worn_kg: float
    backpack_kg: float
    total_kg: float


class CarriedWeight(TypedDict):
    heaviest_kg: float
    roles: dict[str, RoleWeight]


def _role_grams(
    assignment: GearAssignment, items: Mapping[int, EquipmentDefinition]
) -> dict[str, tuple[int, int]]:
    """Start with the entire kit packed, then replace worn items in each role."""
    packed: dict[int, int] = {}
    equipped: dict[str, tuple[int, int]] = {}
    for role, equipment in assignment.items():
        worn_grams = replaced_grams = 0
        for item_id in equipment.values():
            item = items.get(item_id)
            if (
                item is None
                or item.worn_weight_grams is None
                or item.inventory_weight_grams is None
            ):
                raise UnknownGearWeight(
                    f"Carried gear weight unavailable for physical item {item_id}."
                )
            packed[item.inventory_form_id or item_id] = item.inventory_weight_grams
            worn_grams += item.worn_weight_grams
            replaced_grams += item.inventory_weight_grams
        equipped[role] = worn_grams, replaced_grams
    packed_grams = sum(packed.values())
    return {role: (worn, packed_grams - replaced) for role, (worn, replaced) in equipped.items()}


def heaviest_carried_weight_kg(
    assignment: GearAssignment, items: Mapping[int, EquipmentDefinition]
) -> float:
    masses = _role_grams(assignment, items)
    return max((worn + packed for worn, packed in masses.values()), default=0) / 1000


def measure_carried_weight(
    assignment: GearAssignment, items: Mapping[int, EquipmentDefinition]
) -> CarriedWeight:
    masses = _role_grams(assignment, items)
    roles = {
        role: RoleWeight(
            worn_kg=worn / 1000, backpack_kg=packed / 1000, total_kg=(worn + packed) / 1000
        )
        for role, (worn, packed) in masses.items()
    }
    return CarriedWeight(
        heaviest_kg=max((row["total_kg"] for row in roles.values()), default=0.0),
        roles=roles,
    )
