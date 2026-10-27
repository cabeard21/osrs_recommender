"""Bounded, performance-neutral ammunition sharing for complete search finalists."""

from __future__ import annotations

from collections.abc import Callable
from itertools import product
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tracker.gear.optimizer import _Search

_PERFORMANCE = (
    "supported",
    "dps",
    "max_hit",
    "accuracy",
    "attack_interval",
    "attack_roll",
    "defence_roll",
    "limitations",
)
_PROTECTED_BONUSES = (
    "defence_stab",
    "defence_slash",
    "defence_crush",
    "defence_ranged",
    "defence_magic",
    "prayer",
)


def _equivalent(original: dict[str, Any], proposed: dict[str, Any]) -> bool:
    """Keep exact attacks and avoid discarding unscored defensive/prayer bonuses."""
    return all(original.get(k) == proposed.get(k) for k in _PERFORMANCE) and all(
        proposed.get("bonuses", {}).get(k, 0) >= original.get("bonuses", {}).get(k, 0)
        for k in _PROTECTED_BONUSES
    )


def _role_options(
    search: _Search, solution: dict[str, Any], ammunition: list[int | None]
) -> list[list[dict[str, int]]]:
    options = []
    for role in search.request.roles:
        loadout = solution["loadouts"][role.id]
        equipment = loadout["equipment"]
        choices = [equipment]
        # Utility benefit is intentionally unscored; do not reinterpret its gear.
        if role.style != "special" and "ammunition" not in {**search.request.locks, **role.locks}:
            for item_id in ammunition:
                if item_id == equipment.get("ammunition"):
                    continue
                proposed = {s: i for s, i in equipment.items() if s != "ammunition"}
                if item_id is not None:
                    proposed["ammunition"] = item_id
                performance = search.performance(proposed, role)
                if performance["supported"] and _equivalent(loadout["performance"], performance):
                    choices.append(proposed)
        options.append(choices)
    return options


def _no_worse(original: dict[str, Any], proposed: dict[str, Any]) -> bool:
    return all(
        proposed[k] <= original[k]
        for k in ("purchase_cost_gp", "gear_inventory_slots", "max_gear_inventory_slots")
    ) and all(
        after["action_count"] <= before["action_count"]
        and after["max_gear_inventory_slots"] <= before["max_gear_inventory_slots"]
        for before, after in zip(original["transitions"], proposed["transitions"], strict=True)
    )


def refine_ammunition(
    search: _Search,
    solution: dict[str, Any],
    solution_key: Callable[[dict[str, Any]], tuple[Any, ...]],
    diagnostics: dict[str, int],
) -> dict[str, Any]:
    """Try only required ammunition IDs and empty, at most 5**4 assignments.

    No new purchases or catalog candidates are introduced. The complete validator
    recomputes purchases, directional actions and transient inventory occupancy.
    Core role performance stays exact, including zero-weight roles. Among otherwise
    tied ammunition assignments, prefer fewer required items before physical IDs.
    """
    ammunition = [
        None,
        *sorted(
            {
                row["equipment"]["ammunition"]
                for row in solution["loadouts"].values()
                if "ammunition" in row["equipment"]
            }
        ),
    ]
    if len(ammunition) == 1:
        return solution

    def key(row: dict[str, Any]) -> tuple[Any, ...]:
        existing = solution_key(row)
        return (*existing[:-1], row["distinct_items"], existing[-1])

    best = solution
    original = {r: row["equipment"] for r, row in solution["loadouts"].items()}
    for assignments in product(*_role_options(search, solution, ammunition)):
        if search.cancelled and search.cancelled():
            raise ValueError("optimization_cancelled")
        proposed = {r.id: e for r, e in zip(search.request.roles, assignments, strict=True)}
        if proposed == original:
            continue
        diagnostics["evaluated_assignments"] += 1
        candidate = search.solution(proposed, None)
        if candidate is not None and _no_worse(solution, candidate) and key(candidate) < key(best):
            best = candidate
    if best is not solution:
        diagnostics["improved_finalists"] += 1
    return best
