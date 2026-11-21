from libc.stdint cimport uint32_t
from libcpp.unordered_set cimport unordered_set


# Each slot can only contain its starting item, its target item, or nothing.
# Two bits per slot suffice even when a hand is cleared automatically.
cdef struct TransitionLayout:
    int size
    int capacity
    int carried_count
    int weapon
    int shield
    bint two_handed[3]
    uint32_t carried_bit[11][3]
    uint32_t start
    uint32_t goal


cdef struct TransitionNode:
    uint32_t state
    int parent
    int slot
    int occupancy
    int peak


cdef inline int slot_code(uint32_t state, int slot) noexcept nogil:
    return (state >> (2 * slot)) & 3


cdef inline uint32_t clear_slot(uint32_t state, int slot) noexcept nogil:
    return state & ~(<uint32_t>3 << (2 * slot))


cdef int transition_occupancy(const TransitionLayout* layout, uint32_t state) noexcept nogil:
    cdef uint32_t equipped = 0
    cdef int slot, count = layout.carried_count
    for slot in range(layout.size):
        equipped |= layout.carried_bit[slot][slot_code(state, slot)]
    while equipped:
        equipped &= equipped - 1
        count -= 1
    return count


cdef int expand_transition(
    const TransitionLayout* layout, vector[TransitionNode]& nodes,
    unordered_set[uint32_t]& visited, int position
) except -1 nogil:
    # Copy before push_back, which may reallocate nodes.
    cdef TransitionNode parent = nodes[position], child
    cdef uint32_t state
    cdef int slot, target, current, unequip
    for unequip in range(2):
        for slot in range(layout.size):
            current = slot_code(parent.state, slot)
            target = slot_code(layout.goal, slot)
            if current == target or (target == 0) != unequip:
                continue
            state = clear_slot(parent.state, slot)
            if unequip:
                if (slot == layout.shield and layout.two_handed[slot_code(layout.goal, layout.weapon)]):
                    continue
                if (slot == layout.weapon and layout.two_handed[current] and
                        slot_code(layout.goal, layout.shield)):
                    continue
            else:
                if slot == layout.weapon and layout.two_handed[target]:
                    state = clear_slot(state, layout.shield)
                elif slot == layout.shield and layout.two_handed[slot_code(state, layout.weapon)]:
                    state = clear_slot(state, layout.weapon)
                state |= <uint32_t>target << (2 * slot)
            if visited.count(state):
                continue
            child.occupancy = transition_occupancy(layout, state)
            if child.occupancy <= layout.capacity:
                visited.insert(state)
                child.state = state
                child.parent = position
                child.slot = slot
                child.peak = max(parent.peak, child.occupancy)
                nodes.push_back(child)
    return 0


def solve_transition(problem, items, cancelled=None):
    """Solve the reduced FIFO problem, expanding rich actions only for the selected path."""
    slots, start, goal, carried, capacity = problem
    cdef TransitionLayout layout
    cdef vector[TransitionNode] nodes
    cdef unordered_set[uint32_t] visited
    cdef TransitionNode node, parent
    cdef int slot, code, position = 0, end, changed = 0
    cdef bint success = False
    memset(&layout, 0, sizeof(layout))
    if not (len(start) == len(goal) == len(slots) <= 11) or len(set(slots)) != len(slots):
        raise ValueError("Invalid reduced transition dimensions")
    layout.size = len(slots)
    layout.capacity = capacity
    layout.carried_count = len(carried)
    layout.weapon = slots.index("weapon") if "weapon" in slots else -1
    layout.shield = slots.index("shield") if "shield" in slots else -1
    if (layout.weapon == -1) != (layout.shield == -1):
        raise ValueError("Reduced hand transitions must include both hands")
    carried_bits = {}
    for slot in range(layout.size):
        if start[slot] is not None:
            layout.start |= <uint32_t>1 << (2 * slot)
        if goal[slot] is not None:
            code = 1 if goal[slot] == start[slot] else 2
            layout.goal |= <uint32_t>code << (2 * slot)
        changed += start[slot] != goal[slot]
        for code, item in ((1, start[slot]), (2, goal[slot])):
            if item is None:
                continue
            if item in carried:
                layout.carried_bit[slot][code] = carried_bits.setdefault(item, 1 << len(carried_bits))
            if slot == layout.weapon:
                layout.two_handed[code] = items[item].two_handed
    node.state = layout.start
    node.parent = -1
    node.slot = -1
    node.peak = node.occupancy = transition_occupancy(&layout, node.state)
    if node.occupancy > layout.capacity:
        return None
    nodes.push_back(node)
    visited.insert(node.state)
    while <size_t>position < nodes.size() and not success:
        if cancelled is not None and cancelled():
            raise ValueError("optimization_cancelled")
        end = position + 256
        with nogil:
            while <size_t>position < nodes.size() and position < end:
                if nodes[position].state == layout.goal:
                    success = True
                    break
                expand_transition(&layout, nodes, visited, position)
                position += 1
    if not success:
        return None
    actions = []
    peak = nodes[position].peak
    while nodes[position].parent >= 0:
        node = nodes[position]
        parent = nodes[node.parent]
        slot = node.slot
        equip = slot_code(node.state, slot) != 0
        # An equip reports each displaced item, including automatic hand removals.
        removed = []
        if equip:
            for i in range(layout.size):
                old = slot_code(parent.state, i)
                if old and old != slot_code(node.state, i):
                    removed.append(start[i] if old == 1 else goal[i])
        actions.append({
            "operation": "equip" if equip else "unequip",
            "slot": slots[slot],
            "item_id": goal[slot] if equip else start[slot],
            "automatically_removed": sorted(removed),
            "gear_inventory_slots": node.occupancy,
        })
        position = node.parent
    actions.reverse()
    return {"actions": actions, "action_count": len(actions), "changed_slots": changed,
            "max_gear_inventory_slots": peak}
