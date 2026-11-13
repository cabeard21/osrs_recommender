"""Pareto-safe local improvement of each completed frontier finalist."""

from __future__ import annotations

from collections import ChainMap, deque
from collections.abc import Iterator
from copy import copy
from typing import TYPE_CHECKING, Any

from tracker.gear.combat_options import CombatOption

if TYPE_CHECKING:
    from tracker.gear.optimizer import RoleConfig, _Search

ASSIGNMENT_LIMIT = 2048
Solution = dict[str, Any]


def _cancel(search: _Search) -> None:
    if search.cancelled and search.cancelled():
        raise ValueError("optimization_cancelled")


def _dominates(candidate: Solution, original: Solution) -> bool:
    return (
        candidate["score"] >= original["score"]
        and candidate["secondary_value"] >= original["secondary_value"]
        and (
            candidate["score"] > original["score"]
            or candidate["secondary_value"] > original["secondary_value"]
        )
        and all(
            candidate[k] <= original[k]
            for k in (
                "purchase_cost_gp",
                "gear_inventory_slots",
                "max_gear_inventory_slots",
                "maximum_actions",
            )
        )
        and all(
            a["action_count"] <= b["action_count"]
            for a, b in zip(candidate["transitions"], original["transitions"], strict=True)
        )
    )


def _trials(search: _Search, best: Solution) -> Iterator[tuple[RoleConfig, dict[str, int]]]:
    """Give empty coordinates first turn, and fairly visit roles and slots."""
    queues: dict[bool, deque[Any]] = {True: deque(), False: deque()}
    carried = set(best["carried_item_ids"])
    for role in search.request.roles:
        if role.style == "special":
            continue
        equipment = best["loadouts"][role.id]["equipment"]
        locked = set(search.request.locks) | set(role.locks)
        for slot in search.pools:
            if slot in locked:
                continue
            candidates = sorted(
                (
                    i
                    for i, item in search.eligible.items()
                    if item.slot == slot and i != equipment.get(slot)
                ),
                key=lambda i: (i not in carried, i),
            )
            queues[slot not in equipment].append((role, slot, iter(candidates)))
    for queue in queues.values():
        while queue:
            _cancel(search)
            role, slot, candidates = queue.popleft()
            try:
                item = next(candidates)
            except StopIteration:
                continue
            queue.append((role, slot, candidates))
            from tracker.gear.optimizer import _equipment_state

            equipment = _equipment_state(best["loadouts"][role.id]["equipment"])
            yield (
                role,
                equipment.with_slot(slot, item)
                if getattr(search, "compact_states", False)
                else {**equipment, slot: item},
            )


def _trial(
    search: _Search, best: Solution, role: RoleConfig, equipment: dict[str, int]
) -> Solution | None:
    """Score with the recorded attack, before paying for full transition validation."""
    loadout = best["loadouts"][role.id]
    option = loadout["combat_option"]
    configured = role
    if option is not None:
        selected = CombatOption(**option)
        configured = role.model_copy(
            update={
                "style": selected.style,
                "stance": selected.stance,
                "spell": selected.spell or role.spell,
                "powered_attack": selected.powered_attack,
                "active_prayer_ids": tuple(loadout.get("selected_prayer_ids", ())),
            }
        )
        if role.combat_options is not None and not any(
            all(
                getattr(candidate, key) == getattr(selected, key)
                for key in ("attack_type", "stance", "spell", "powered_attack")
            )
            for _, candidate in search.configured_options(
                role, search.items.get(equipment.get("weapon", -1))
            )
        ):
            return None
    performance = search.evaluate(equipment, configured).model_dump(mode="json")
    if not performance["supported"]:
        return None
    # A single changed role cannot lower DPS and dominate the incumbent.
    if (performance.get("dps") or 0) < (loadout["performance"].get("dps") or 0):
        return None
    key = (role.id, tuple(sorted(equipment.items())))
    search.performance_cache[key] = performance
    search.option_cache[key] = {
        **(option or {}),
        "__prayer_ids": loadout.get("selected_prayer_ids", []),
    }
    from tracker.gear.optimizer import _assignment_state

    assignment = _assignment_state({rid: row["equipment"] for rid, row in best["loadouts"].items()})
    assignment = (
        assignment.with_role(role.id, equipment)
        if getattr(search, "compact_states", False)
        else {**assignment, role.id: equipment}
    )
    # Use the search's objective: CostSearch uses negative GP/damage here.
    if search.secondary(assignment) < best["secondary_value"]:
        return None
    return search.solution(assignment, best["maximum_actions"])


def refine_finalist(
    search: _Search, solution: Solution, *, limit: int = ASSIGNMENT_LIMIT
) -> tuple[Solution, dict[str, Any]]:
    """Restart exact single-slot improvement until a plateau or this finalist's cap.

    Other finalists and the main beam cannot consume this allowance. Original
    attacks stay frozen; every accepted row passes the full joint validator.
    """
    if type(limit) is not int or not 0 <= limit <= ASSIGNMENT_LIMIT:
        raise ValueError(f"finalist limit must be an integer from 0 to {ASSIGNMENT_LIMIT}")
    search = copy(search)
    search.performance_cache = ChainMap({}, search.performance_cache)
    search.option_cache = ChainMap({}, search.option_cache)
    diagnostics: dict[str, Any] = {
        "evaluated_assignments": 0,
        "improvements": 0,
        "work_budget_exhausted": False,
    }
    best = solution
    seen = set()
    while True:
        _cancel(search)
        for rid, row in best["loadouts"].items():
            key = (rid, tuple(sorted(row["equipment"].items())))
            search.performance_cache[key] = row["performance"]
            search.option_cache[key] = {
                **(row["combat_option"] or {}),
                "__prayer_ids": row.get("selected_prayer_ids", []),
            }
        changed = False
        for role, equipment in _trials(search, best):
            identity = (
                tuple(
                    (rid, tuple(sorted(row["equipment"].items())))
                    for rid, row in sorted(best["loadouts"].items())
                ),
                role.id,
                tuple(sorted(equipment.items())),
            )
            if identity in seen:
                continue
            if diagnostics["evaluated_assignments"] >= limit:
                return best, {**diagnostics, "work_budget_exhausted": True}
            seen.add(identity)
            diagnostics["evaluated_assignments"] += 1
            candidate = _trial(search, best, role, equipment)
            _cancel(search)
            if candidate is not None and _dominates(candidate, best):
                best = candidate
                diagnostics["improvements"] += 1
                changed = True
                break
        if not changed:
            return best, diagnostics
