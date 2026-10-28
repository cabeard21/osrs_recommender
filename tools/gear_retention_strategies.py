"""Serial, process-local candidate experiments; never imported by production.

Pool replacements are heuristics. In particular, numeric Pareto superiority does
not prove cross-identity dominance under joint purchase/action constraints.
Only additive refinement preserves baseline incumbents by construction.
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from itertools import combinations, product
from time import perf_counter
from typing import Any

from tracker.gear import optimizer

STRATEGIES = ("baseline", "all", "pareto", "diversity", "shared", "refinement", "targeted")


def _signature(item: Any) -> tuple[Any, ...]:
    return (
        item.slot,
        item.attack_speed,
        item.two_handed,
        item.ammo_type,
        item.ammo_for,
        item.attack_styles,
        item.attack_profiles,
        item.unsupported_effects,
    )


def _front(search: Any, ids: list[int]) -> list[int]:
    """Strict numeric frontier, keeping exact-equal physical IDs distinct."""
    values = {i: (*search.items[i].bonuses.model_dump().values(), -search.cost({i})) for i in ids}
    return [
        i
        for i in ids
        if not any(
            _signature(search.items[i]) == _signature(search.items[j])
            and all(a >= b for a, b in zip(values[j], values[i], strict=True))
            and any(a > b for a, b in zip(values[j], values[i], strict=True))
            for j in ids
            if j != i
        )
    ]


def _shared(search: Any, ids: list[int]) -> list[int]:
    """Frontier of role scaffold DPS and price; ties retain concrete identities."""
    values = {
        i: (*(search.marginals.get((r.id, i), -1) for r in search.request.roles), -search.cost({i}))
        for i in ids
    }
    return [
        i
        for i in ids
        if not any(
            all(a >= b for a, b in zip(values[j], values[i], strict=True))
            and any(a > b for a, b in zip(values[j], values[i], strict=True))
            for j in ids
            if j != i
        )
    ]


@contextmanager
def _experiment(strategy: str, role_beam_width: int | None):
    """Patch only inside a serial research worker and always restore on failure."""
    original = optimizer._Search
    original_width = optimizer.BEAM_WIDTH
    captured: list[Any] = []

    class ResearchSearch(original):  # type: ignore[valid-type,misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.evaluations = 0
            self.stage_runs: list[dict[str, Any]] = []
            super().__init__(*args, **kwargs)
            captured.append(self)

        def performance(self, equipment: Any, role: Any) -> dict[str, Any]:
            key = (role.id, tuple(sorted(equipment.items())))
            if key not in self.performance_cache:
                self.evaluations += 1
            return super().performance(equipment, role)

        def loadouts(self, roles: Any) -> list[dict[str, int]]:
            before = self.nodes
            result = super().loadouts(roles)
            self.stage_runs.append(
                {
                    "stage": "role_or_common",
                    "roles": [r.id for r in roles],
                    "nodes": self.nodes - before,
                    "node_start": before,
                    "node_end": self.nodes,
                    "finalists": len(result),
                    "survivor_ids": sorted({i for equipment in result for i in equipment.values()}),
                }
            )
            return result

        def joint_loadouts(self, limit: int | None) -> list[dict[str, dict[str, int]]]:
            before = self.nodes
            branches: dict[str, dict[str, list[int | None]]] = {}
            for slot in optimizer.SLOTS:
                ids = [i for i in self.pools[slot] if i is not None]
                common = sorted(
                    ids,
                    key=lambda i: (
                        -sum(
                            self.marginals.get((r.id, i), -1) * r.weight for r in self.request.roles
                        ),
                        i,
                    ),
                )[:1]
                branches[slot] = {}
                for role in self.request.roles:
                    locks = {**self.request.locks, **role.locks}
                    ranked = sorted(ids, key=lambda i: (-self.marginals.get((role.id, i), -1), i))
                    branches[slot][role.id] = (
                        [locks[slot]]
                        if slot in locks
                        else list(dict.fromkeys([None, *ranked[:2], *common]))
                    )
            result = super().joint_loadouts(limit)
            self.stage_runs.append(
                {
                    "stage": "joint",
                    "limit": limit,
                    "nodes": self.nodes - before,
                    "node_start": before,
                    "node_end": self.nodes,
                    "finalists": len(result),
                    "survivor_ids": {
                        r.id: sorted({i for state in result for i in state[r.id].values()})
                        for r in self.request.roles
                    },
                    "branch_options": branches,
                }
            )
            return result

        def candidate_pools(self) -> dict[str, list[int | None]]:
            baseline = super().candidate_pools()
            self.baseline_pools = baseline
            if strategy in {"baseline", "refinement", "targeted"}:
                return baseline
            locks = {
                i
                for role in self.request.roles
                for i in {**self.request.locks, **role.locks}.values()
                if i is not None
            }
            pools: dict[str, list[int | None]] = {}
            for slot in optimizer.SLOTS:
                ids = sorted(i for i, item in self.eligible.items() if item.slot == slot)
                chosen = (
                    ids
                    if strategy == "all"
                    else (_shared(self, ids) if strategy == "shared" else _front(self, ids))
                )
                if strategy in {"diversity", "shared"}:
                    chosen = sorted(set(chosen) | {i for i in baseline[slot] if i is not None})
                pools[slot] = [None, *sorted(set(chosen) | (locks & set(ids)))]
            self.truncated = any(
                len(pools[s]) - 1 < sum(item.slot == s for item in self.eligible.values())
                for s in optimizer.SLOTS
            )
            return pools

    optimizer._Search = ResearchSearch  # type: ignore[misc]
    if role_beam_width is not None:
        optimizer.BEAM_WIDTH = role_beam_width
    try:
        yield captured
    finally:
        optimizer._Search = original  # type: ignore[misc]
        optimizer.BEAM_WIDTH = original_width


def _replace(equipment: dict[str, int], changes: dict[str, int | None]) -> dict[str, int]:
    return {s: i for s, i in {**equipment, **changes}.items() if i is not None}


def _assignments(search: Any, seed: dict[str, Any]):
    """Single, paired, and coordinated shared edits in stable physical-ID order."""
    equipment = {r: row["equipment"] for r, row in seed["loadouts"].items()}
    options = {
        s: [None, *sorted(i for i, item in search.eligible.items() if item.slot == s)]
        for s in optimizer.SLOTS
    }
    for role in search.request.roles:
        if role.style == "special":
            continue
        unlocked = [
            s
            for s in optimizer.SLOTS
            if s not in {**search.request.locks, **role.locks} and len(options[s]) > 1
        ]
        for width in (1, 2):
            for slots in combinations(unlocked, width):
                for ids in product(*(options[s] for s in slots)):
                    revised = _replace(equipment[role.id], dict(zip(slots, ids, strict=True)))
                    if revised != equipment[role.id]:
                        yield {**equipment, role.id: revised}
    if len(search.request.roles) > 1:
        for slot in optimizer.SLOTS:
            choices = [
                (
                    [equipment[r.id].get(slot)]
                    if r.style == "special" or slot in {**search.request.locks, **r.locks}
                    else options[slot]
                )
                for r in search.request.roles
            ]
            for ids in product(*choices):
                yield {
                    r.id: _replace(equipment[r.id], {slot: i})
                    for r, i in zip(search.request.roles, ids, strict=True)
                }


def _refine(search: Any, result: dict[str, Any], limit: int) -> tuple[dict[str, Any], int]:
    winners = [p["solution"] for p in result["curve"]]
    unrestricted = result["unrestricted"]
    seeds = {
        json.dumps(s["loadouts"], sort_keys=True): s
        for s in [*winners, unrestricted]
        if s is not None
    }
    seen: set[str] = set()
    attempts = 0
    for seed in seeds.values():
        for assignment in _assignments(search, seed):
            identity = json.dumps(assignment, sort_keys=True)
            if identity in seen:
                continue
            if attempts >= limit:
                break
            seen.add(identity)
            attempts += 1
            candidate = search.solution(assignment, None)
            if candidate is None:
                continue
            if unrestricted is None or optimizer._solution_key(candidate) < optimizer._solution_key(
                unrestricted
            ):
                unrestricted = candidate
            for index in range(candidate["maximum_actions"], len(winners)):
                previous = winners[index]
                if previous is None or optimizer._solution_key(candidate) < optimizer._solution_key(
                    previous
                ):
                    winners[index] = candidate
        if attempts >= limit:
            break
    denominator = unrestricted["score"] if unrestricted else 0
    curve = [
        {
            **point,
            "solution": solution,
            "status": "best_found" if solution else "no_feasible_solution_found",
            "relative_performance": solution["score"] / denominator
            if solution and denominator
            else None,
        }
        for point, solution in zip(result["curve"], winners, strict=True)
    ]
    referenced = {
        i
        for solution in [*winners, unrestricted]
        if solution
        for row in solution["loadouts"].values()
        for i in row["equipment"].values()
    }
    items = {row["item_id"]: row for row in result["items"]}
    items.update({i: search.facts[i] for i in referenced})
    return {
        **result,
        "curve": curve,
        "unrestricted": unrestricted,
        "selected_solution": winners[-1],
        "items": [items[i] for i in sorted(items)],
        "suggested_swap_limit": next(
            (
                p["swap_limit"]
                for p in curve
                if p["relative_performance"] is not None and p["relative_performance"] >= 0.95
            ),
            None,
        ),
        "alternatives": {},
    }, attempts


def run(
    case: Any, strategy: str, *, refinement_limit: int = 2000, role_beam_width: int | None = None
) -> dict[str, Any]:
    """Run one experiment, preserving production defaults and response diagnostics.

    Must run serially in a dedicated worker process; the scoped class patch is
    intentionally not a production extension point or thread-safe service API.
    Refinement's extra work is separate from baseline explored_nodes and search.
    """
    if (
        strategy not in STRATEGIES
        or refinement_limit < 0
        or (role_beam_width is not None and role_beam_width < 1)
    ):
        raise ValueError("unknown strategy or negative refinement limit")
    with _experiment(strategy, role_beam_width) as captured:
        options: dict[str, Any] = (
            {"targeted_head_refinement": True} if strategy == "targeted" else {}
        )
        result = optimizer.optimize(
            case.snapshot, case.request, case.catalog, case.content, case.prices, case.at, **options
        )
        search = captured[0]
        baseline_evaluations: int | None = search.evaluations
        attempts = 0
        refinement_duration = 0.0
        if strategy == "refinement":
            started = perf_counter()
            result, attempts = _refine(search, copy.deepcopy(result), refinement_limit)
            refinement_duration = perf_counter() - started
        targeted = result["search"].get("targeted_head_refinement", {})
        if strategy == "targeted":
            attempts = targeted["assignment_attempts"]
            refinement_duration = targeted["duration_seconds"]
            # Targeted work runs before normal alternatives are rebuilt, so this
            # run cannot infer the unrefined response's evaluation total.
            baseline_evaluations = None
        return {
            **result,
            "research": {
                "strategy": strategy,
                "role_beam_width_override": role_beam_width,
                "performance_evaluations": search.evaluations,
                "baseline_performance_evaluations": baseline_evaluations,
                "refinement_performance_evaluations": targeted.get("performance_cache_misses")
                if strategy == "targeted"
                else search.evaluations - (baseline_evaluations or 0),
                "refinement_assignments": attempts,
                "refinement_duration_seconds": refinement_duration,
                "refinement_limit": 2000 if strategy == "targeted" else refinement_limit,
                "refinement_limit_reached": targeted.get("work_budget_exhausted", False)
                if strategy == "targeted"
                else strategy == "refinement" and attempts >= refinement_limit,
                "pools": search.pools,
                "baseline_pools": search.baseline_pools,
                "marginals": {
                    f"{role}:{i}": value for (role, i), value in sorted(search.marginals.items())
                },
                "stage_runs": search.stage_runs,
            },
        }
