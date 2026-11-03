"""Bounded, performance-neutral ammunition sharing for complete search finalists."""

from __future__ import annotations

from collections import ChainMap
from collections.abc import Callable
from copy import copy
from itertools import product
from typing import TYPE_CHECKING, Any

from tracker.gear.combat_options import CombatOption

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
                option = loadout.get("combat_option")
                if option is not None:
                    selected = CombatOption(**option)
                    configured = role.model_copy(
                        update={
                            "style": selected.style,
                            "stance": selected.stance,
                            "spell": selected.spell or role.spell,
                            "powered_attack": selected.powered_attack,
                        }
                    )
                    cache_key = (role.id, tuple(sorted(proposed.items())))
                    search.performance_cache[cache_key] = search.evaluate(
                        proposed, configured
                    ).model_dump(mode="json")
                    search.option_cache[cache_key] = option
                performance = search.performance(proposed, role)
                if performance["supported"] and _equivalent(loadout["performance"], performance):
                    choices.append(proposed)
        options.append(choices)
    return options


def _no_worse(original: dict[str, Any], proposed: dict[str, Any]) -> bool:
    return (
        original.get("running_cost") == proposed.get("running_cost")
        and all(
            loadout.get("running_cost") == proposed["loadouts"][role_id].get("running_cost")
            for role_id, loadout in original["loadouts"].items()
        )
        and all(
            proposed[k] <= original[k]
            for k in ("purchase_cost_gp", "gear_inventory_slots", "max_gear_inventory_slots")
        )
        and all(
            after["action_count"] <= before["action_count"]
            and after["max_gear_inventory_slots"] <= before["max_gear_inventory_slots"]
            for before, after in zip(original["transitions"], proposed["transitions"], strict=True)
        )
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

    # Frontier rows can intentionally use a slower stance or cheaper spell.
    # Keep their chosen attacks fixed, and isolate the overrides from the search.
    search = copy(search)
    search.performance_cache = ChainMap({}, search.performance_cache)
    search.option_cache = ChainMap({}, search.option_cache)
    for role_id, loadout in solution["loadouts"].items():
        cache_key = (role_id, tuple(sorted(loadout["equipment"].items())))
        search.performance_cache[cache_key] = loadout["performance"]
        search.option_cache[cache_key] = loadout.get("combat_option")

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


def refine_shared_slots(
    search: _Search,
    solution: dict[str, Any],
    solution_key: Callable[[dict[str, Any]], tuple[Any, ...]],
) -> dict[str, Any]:
    """Fill slots empty in every role with one shared eligible item.

    The complete validator retains action, inventory, purchase, and combat rules.
    Only pool candidates are tried, so this remains bounded with the main search.
    """
    best = solution
    for slot, choices in search.pools.items():
        if search.cancelled and search.cancelled():
            raise ValueError("optimization_cancelled")
        if any(
            slot in {**search.request.locks, **role.locks}
            or slot in best["loadouts"][role.id]["equipment"]
            for role in search.request.roles
        ):
            continue
        for item_id in choices:
            if item_id is None:
                continue
            bonuses = search.eligible[item_id].bonuses.model_dump().values()
            if not any(value > 0 for value in bonuses):
                continue
            proposed = {
                role.id: {**best["loadouts"][role.id]["equipment"], slot: item_id}
                for role in search.request.roles
            }
            candidate = search.solution(proposed, solution["maximum_actions"])
            if candidate is not None and solution_key(candidate) < solution_key(best):
                best = candidate
    return best


def refine_magic_staves(
    search: _Search,
    solution: dict[str, Any],
    solution_key: Callable[[dict[str, Any]], tuple[Any, ...]],
) -> dict[str, Any]:
    """Recheck eligible staves for magic finalists.

    Weapon pools and beams can omit a useful staff. Evaluate each physical
    candidate against the complete joint solution so directional action and
    inventory limits remain authoritative.
    """
    best = solution
    staves = [
        item_id
        for item_id, item in search.eligible.items()
        if item.slot == "weapon" and "magic" in item.attack_styles
    ]
    for role in search.request.roles:
        if role.style != "magic" or "weapon" in {**search.request.locks, **role.locks}:
            continue
        for item_id in staves:
            if search.cancelled and search.cancelled():
                raise ValueError("optimization_cancelled")
            if best["loadouts"][role.id]["equipment"].get("weapon") == item_id:
                continue
            proposed = {
                candidate_role.id: {
                    **best["loadouts"][candidate_role.id]["equipment"],
                    **({"weapon": item_id} if candidate_role.id == role.id else {}),
                }
                for candidate_role in search.request.roles
            }
            candidate = search.solution(proposed, solution["maximum_actions"])
            if candidate is not None and solution_key(candidate) < solution_key(best):
                best = candidate
    return best
