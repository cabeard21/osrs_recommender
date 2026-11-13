"""Directional equipment actions and capacity-aware inventory simulation.

Each equip or explicit unequip is one action. Automatically displaced hand items
do not add actions. The inventory is the union carried, less currently equipped.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Set
from typing import Any

from tracker.gear.compact_states import EquipmentState


def inventory_slots(
    equipment: Mapping[str, int], carried: Set[int], items: Mapping[int, Any]
) -> int:
    """One usable instance/stack per concrete item, reused between roles."""
    if isinstance(equipment, EquipmentState):
        return len(carried - equipment.physical_ids)
    return len(carried - set(equipment.values()))


def plan_transition(
    source: Mapping[str, int],
    destination: Mapping[str, int],
    items: Mapping[int, Any],
    *,
    carried: Set[int] | None = None,
    capacity: int = 28,
) -> dict[str, Any] | None:
    """Breadth-first shortest legal action sequence, including transient capacity.

    Equipping a shield removes an equipped two-handed weapon. Equipping a
    two-handed weapon removes both occupied hands. Only source/destination gear
    is needed: an intermediate third item cannot improve action count/capacity.
    """
    from tracker.gear.execution_profile import compact_states_active

    if compact_states_active():
        from tracker.gear.compact_transitions import SLOT_SET, compact_transition

        if (
            source.keys() <= SLOT_SET
            and destination.keys() <= SLOT_SET
            and all(type(item) is int for item in source.values())
            and all(type(item) is int for item in destination.values())
            and (carried is None or all(type(item) is int for item in carried))
        ):
            return compact_transition(
                source, destination, items, carried=carried, capacity=capacity
            )
    union = frozenset(carried if carried is not None else (*source.values(), *destination.values()))
    start = tuple(sorted(source.items()))
    goal = tuple(sorted(destination.items()))
    if inventory_slots(source, union, items) > capacity:
        return None
    queue: deque[tuple[tuple[tuple[str, int], ...], list[dict[str, Any]], int]] = deque(
        [(start, [], inventory_slots(source, union, items))]
    )
    visited = {start}
    while queue:
        state, actions, peak = queue.popleft()
        if state == goal:
            return {
                "actions": actions,
                "action_count": len(actions),
                "changed_slots": sum(
                    source.get(s) != destination.get(s) for s in source.keys() | destination.keys()
                ),
                "max_gear_inventory_slots": peak,
            }
        equipment = dict(state)
        choices: list[tuple[str, str, int]] = [
            ("equip", slot, item_id)
            for slot, item_id in sorted(destination.items())
            if equipment.get(slot) != item_id
        ]
        for slot, item_id in state:
            if slot in destination:
                continue
            final_weapon = items.get(destination.get("weapon", -1))
            if slot == "shield" and final_weapon and final_weapon.two_handed:
                continue
            if slot == "weapon" and items[item_id].two_handed and "shield" in destination:
                continue
            choices.append(("unequip", slot, item_id))
        for operation, slot, item_id in choices:
            updated = dict(equipment)
            removed: list[int] = []
            if operation == "unequip":
                del updated[slot]
            else:
                if slot == "weapon" and items[item_id].two_handed:
                    removed.extend(updated.pop(s) for s in ("weapon", "shield") if s in updated)
                elif (
                    slot == "shield" and "weapon" in updated and items[updated["weapon"]].two_handed
                ):
                    removed.append(updated.pop("weapon"))
                if slot in updated:
                    removed.append(updated[slot])
                updated[slot] = item_id
            key = tuple(sorted(updated.items()))
            occupancy = inventory_slots(updated, union, items)
            if key in visited or occupancy > capacity:
                continue
            visited.add(key)
            action = {
                "operation": operation,
                "slot": slot,
                "item_id": item_id,
                "automatically_removed": sorted(removed),
                "gear_inventory_slots": occupancy,
            }
            queue.append((key, [*actions, action], max(peak, occupancy)))
    return None
