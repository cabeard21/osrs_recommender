"""Original transition BFS with fixed slots and predecessor-only queue records."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Set
from typing import Any, NamedTuple

from tracker.gear.compact_states import SLOT_NAMES

SLOTS = tuple(sorted(SLOT_NAMES))
SLOT_SET = frozenset(SLOTS)
_Action = tuple[bool, int, int, tuple[int, ...], int]


class TransitionProblem(NamedTuple):
    """Complete structural input under one fixed item catalog."""

    slots: tuple[str, ...]
    start: tuple[int | None, ...]
    goal: tuple[int | None, ...]
    carried: frozenset[int]
    capacity: int


class _Node(NamedTuple):
    state: tuple[int | None, ...]
    parent: int
    action: _Action | None
    peak: int


def _report(nodes: list[_Node], index: int, changed: int, slots: tuple[str, ...]) -> dict[str, Any]:
    peak = nodes[index].peak
    actions = []
    while nodes[index].action is not None:
        node = nodes[index]
        assert node.action is not None
        equip, slot, item, removed, occupancy = node.action
        actions.append(
            {
                "operation": "equip" if equip else "unequip",
                "slot": slots[slot],
                "item_id": item,
                "automatically_removed": sorted(removed),
                "gear_inventory_slots": occupancy,
            }
        )
        index = node.parent
    actions.reverse()
    return {
        "actions": actions,
        "action_count": len(actions),
        "changed_slots": changed,
        "max_gear_inventory_slots": peak,
    }


def compact_transition(
    source: Mapping[str, int],
    destination: Mapping[str, int],
    items: Mapping[int, Any],
    *,
    carried: Set[int] | None = None,
    capacity: int = 28,
) -> dict[str, Any] | None:
    """Retain exactly the baseline FIFO expansion and sorted-slot action order.

    Callers dispatch only standard slots with concrete integer IDs; generic
    mappings remain on the baseline path. Physical IDs are never coalesced.
    """
    return solve_transition(
        prepare_transition(source, destination, carried=carried, capacity=capacity), items
    )


def prepare_transition(
    source: Mapping[str, int],
    destination: Mapping[str, int],
    *,
    carried: Set[int] | None = None,
    capacity: int = 28,
) -> TransitionProblem:
    """Factor only unchanging physical equipment, preserving ordered active slots."""
    union = frozenset(carried if carried is not None else (*source.values(), *destination.values()))
    hands = source.get("weapon") != destination.get("weapon") or source.get(
        "shield"
    ) != destination.get("shield")
    slots = tuple(
        slot
        for slot in SLOTS
        if source.get(slot) != destination.get(slot) or (hands and slot in ("weapon", "shield"))
    )
    active = frozenset(slots)
    # Unchanged non-hand gear is never an action target. Shared physical IDs
    # remain equipped even when another coordinate containing that ID changes.
    union = union.difference(item for slot, item in source.items() if slot not in active)
    start = tuple(source.get(slot) for slot in slots)
    goal = tuple(destination.get(slot) for slot in slots)
    return TransitionProblem(slots, start, goal, union, capacity)


def solve_transition(problem: TransitionProblem, items: Mapping[int, Any]) -> dict[str, Any] | None:
    """Run the unchanged FIFO policy using only the frozen structural problem."""
    slots, start, goal, union, capacity = problem
    weapon_slot = slots.index("weapon") if "weapon" in slots else -1
    shield_slot = slots.index("shield") if "shield" in slots else -1
    occupancy = len(union.difference(start))
    if occupancy > capacity:
        return None
    nodes = [_Node(start, -1, None, occupancy)]
    queue = deque((0,))
    visited = {start}
    target = tuple((i, item) for i, item in enumerate(goal) if item is not None)
    weapon_id = goal[weapon_slot] if weapon_slot >= 0 else None
    final_weapon = items.get(weapon_id if weapon_id is not None else -1)
    while queue:
        node_index = queue.popleft()
        state, _, _, peak = nodes[node_index]
        if state == goal:
            return _report(
                nodes, node_index, sum(a != b for a, b in zip(start, goal, strict=True)), slots
            )
        choices = [(True, i, item) for i, item in target if state[i] != item]
        for slot, item in enumerate(state):
            if item is None or goal[slot] is not None:
                continue
            if slot == shield_slot and final_weapon and final_weapon.two_handed:
                continue
            if slot == weapon_slot and items[item].two_handed and goal[shield_slot] is not None:
                continue
            choices.append((False, slot, item))
        for equip, slot, item in choices:
            updated = list(state)
            removed = []
            if not equip:
                updated[slot] = None
            else:
                if slot == weapon_slot and items[item].two_handed:
                    for hand in (weapon_slot, shield_slot):
                        previous = updated[hand]
                        if previous is not None:
                            removed.append(previous)
                            updated[hand] = None
                elif (
                    slot == shield_slot
                    and (weapon := updated[weapon_slot]) is not None
                    and items[weapon].two_handed
                ):
                    removed.append(weapon)
                    updated[weapon_slot] = None
                previous = updated[slot]
                if previous is not None:
                    removed.append(previous)
                updated[slot] = item
            key = tuple(updated)
            occupancy = len(union.difference(updated))
            if key in visited or occupancy > capacity:
                continue
            visited.add(key)
            action = (equip, slot, item, tuple(removed), occupancy)
            queue.append(len(nodes))
            nodes.append(_Node(key, node_index, action, max(peak, occupancy)))
    return None
