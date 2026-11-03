"""Deterministic bounded search and exact dominance of complete gear assignments."""

from __future__ import annotations

import json
from collections import ChainMap, deque
from collections.abc import Callable, Iterable, Iterator
from copy import copy
from hashlib import sha256
from itertools import combinations, product
from typing import TYPE_CHECKING, Any

from tracker.content.schema import ItemSlot

if TYPE_CHECKING:
    from tracker.gear.optimizer import _Search

Solution = dict[str, Any]


def pareto(rows: Iterable[Solution]) -> list[Solution]:
    """Return unrounded nondominated objective pairs with stable tie resolution."""
    from tracker.gear.optimizer import _solution_key

    best = None
    result = []
    for row in sorted(rows, key=_solution_key):
        secondary = row["secondary_value"]
        if best is None or secondary > best:
            result.append(row)
            best = secondary
    return result


def diverse[Row](
    rows: Iterable[Row], rank: Callable[[Row], tuple[Any, ...]], limit: int
) -> list[Row]:
    """Keep extremes and round-robin secondary leaders from eight DPS bands."""
    # Rank evaluation can include exact combat/resource scoring. Decorate once,
    # retaining stable sort order and the original row equality semantics.
    ordered = sorted(((rank(row), row) for row in rows), key=lambda entry: entry[0])
    if len(ordered) <= limit:
        return [row for _, row in ordered]
    scores = [-key[0] for key, _ in ordered]
    low, high = min(scores), max(scores)
    bands: list[list[tuple[tuple[Any, ...], Row]]] = [[] for _ in range(8)]
    for entry, score in zip(ordered, scores, strict=True):
        band = min(7, int(8 * (score - low) / (high - low))) if high > low else 0
        bands[band].append(entry)
    for bucket in bands:
        bucket.sort(key=lambda entry: (entry[0][1], *entry[0]))
    selected = [ordered[0][1]]
    extreme = min(ordered, key=lambda entry: (entry[0][1], *entry[0]))[1]
    if extreme != selected[0]:
        selected.append(extreme)
    queues = [deque(band) for band in bands]
    while len(selected) < limit and any(queues):
        for queue in queues:
            if queue:
                _, row = queue.popleft()
                if row not in selected:
                    selected.append(row)
                    if len(selected) == limit:
                        break
    return selected


def _identity(loadouts: dict[str, Any]) -> str:
    return json.dumps(loadouts, sort_keys=True, separators=(",", ":"))


def explore(
    original: _Search,
    winners: list[Solution | None],
    unrestricted: Solution | None,
    thorough: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[Solution | None], Solution | None]:
    """Preserve the DPS lane and independently explore secondary-diverse beams."""
    from tracker.gear.optimizer import SLOTS, _solution_key

    # This isolated search overrides its tick method for a separate work budget.
    search: Any = copy(original)
    search.frontier_search = True
    search.nodes = 0
    budget = 300_000 if thorough else 100_000
    phase_limit = budget - 5000
    diagnostics: dict[str, Any] = {
        "policy": "secondary-frontier-v1",
        "expansion_limit": budget,
        "explored_nodes": 0,
        "assignment_attempts": 0,
        "complete_assignment_limit": 2000 if thorough else 0,
        "work_budget_exhausted": False,
    }

    def tick() -> bool:
        if search.cancelled and search.cancelled():
            raise ValueError("optimization_cancelled")
        if search.nodes >= phase_limit:
            return False
        search.nodes += 1
        return True

    search.tick = tick
    # Marginals cover all eligible items, including those omitted by DPS pools.
    pools = {}
    for slot in SLOTS:
        candidates = [i for i, item in search.eligible.items() if item.slot == slot]
        lanes = [
            list(original.pools[slot]),
            sorted(candidates, key=lambda i: (search.cost({i}), i)),
        ]
        for role in search.request.roles:
            lanes.append(
                sorted(
                    candidates,
                    key=lambda i: (
                        -search.secondary_marginals.get((role.id, i), 0),
                        -search.marginals.get((role.id, i), -1),
                        i,
                    ),
                )
            )
        keep = list(dict.fromkeys(i for i in original.pools[slot] if i is not None))
        for candidate_row in zip(
            *[lane + [None] * max(0, len(candidates) - len(lane)) for lane in lanes], strict=False
        ):
            for item in candidate_row:
                if item is not None and item not in keep and len(keep) < 23:
                    keep.append(item)
        pools[slot] = [None, *keep]
    search.pools = pools
    archives: dict[int | None, list[Solution]] = {
        limit: [] for limit in [*range(search.request.max_swaps + 1), None]
    }
    seen = set()
    option_candidates = []

    def accept(solution: Solution | None) -> None:
        if solution is None:
            return
        identity = _identity(solution["loadouts"])
        if identity in seen:
            return
        seen.add(identity)
        if any(r.combat_options is not None for r in search.request.roles):
            option_candidates.append(solution)
            if len(option_candidates) > 256:
                option_candidates[:] = diverse(option_candidates, _solution_key, 128)
        for limit in archives:
            if limit is None or solution["maximum_actions"] <= limit:
                archives[limit] = pareto([*archives[limit], solution])

    for solution in [*winners, unrestricted]:
        accept(solution)
    roles = search.request.roles
    individual = {role.id: search.loadouts((role,)) for role in roles}
    # Shared and joint searches preserve constrained joint solutions.
    common = individual[roles[0].id] if len(roles) == 1 else search.loadouts(roles)
    for equipment in common:
        accept(search.solution({r.id: equipment for r in roles}, None))
    if len(roles) > 1:
        for limit in archives:
            for assignment in search.joint_loadouts(limit):
                accept(search.solution(assignment, None))
    if thorough:
        # Fair deterministic substitution schedule, shared across all frontier seeds.
        seeds = []
        identities = set()
        for archive in archives.values():
            for row in diverse(archive, _solution_key, 8):
                identity = _identity(row["loadouts"])
                if identity not in identities:
                    identities.add(identity)
                    seeds.append(row)
        schedules: deque[
            tuple[dict[str, Any], str, tuple[ItemSlot, ...], Iterator[tuple[Any, ...]]]
        ] = deque()
        for seed in seeds:
            assignment = {r: dict(row["equipment"]) for r, row in seed["loadouts"].items()}
            for role in roles:
                locked = set(search.request.locks) | set(role.locks)
                slots = [s for s in SLOTS if s not in locked]
                for group in [*((s,) for s in slots), *combinations(slots, 2)]:
                    schedules.append(
                        (assignment, role.id, group, iter(product(*(pools[s] for s in group))))
                    )
        while schedules and diagnostics["assignment_attempts"] < 2000:
            assignment, role, group, iterator = schedules.popleft()
            try:
                values = next(iterator)
            except StopIteration:
                continue
            schedules.append((assignment, role, group, iterator))
            if search.cancelled and search.cancelled():
                raise ValueError("optimization_cancelled")
            replacement = {s: i for s, i in assignment[role].items() if s not in group}
            replacement.update({s: i for s, i in zip(group, values, strict=True) if i is not None})
            diagnostics["assignment_attempts"] += 1
            accept(search.solution({**assignment, role: replacement}, None))
    # Reserve work for option tradeoffs even if equipment beam expansion exhausts its share.
    phase_limit = budget
    option_seeds = {
        _identity(row["loadouts"]): row
        for archive in [option_candidates, *archives.values()]
        for row in archive
    }
    for seed in option_seeds.values():
        for row in _combat_variants(search, seed, tick):
            accept(row)
    # Later equipment and combat-option searches can reintroduce inert ammo.
    # Normalize complete rows before ranking and hashing the published results.
    from tracker.gear.refinement import refine_ammunition

    cleanup = {"evaluated_assignments": 0, "improved_finalists": 0}
    cleaned = {_identity(row["loadouts"]): row for archive in archives.values() for row in archive}
    cleaned = {
        identity: refine_ammunition(search, row, _solution_key, cleanup)
        for identity, row in cleaned.items()
    }
    archives = {
        limit: pareto(
            row for row in cleaned.values() if limit is None or row["maximum_actions"] <= limit
        )
        for limit in archives
    }
    updated = [archives[i][0] if archives[i] else winners[i] for i in range(len(winners))]
    unlimited = archives[None][0] if archives[None] else unrestricted
    groups = []
    for limit, archive in archives.items():
        baseline = archive[0] if archive else None
        dps = baseline["score"] if baseline else None
        visible = [
            row
            for row in archive
            if getattr(search, "complete_frontiers", False)
            or not dps
            or 100 * (dps - row["score"]) / dps <= search.request.max_dps_loss_pct
        ]
        sampled = len(visible) > 64 and not getattr(search, "complete_frontiers", False)
        if sampled:
            visible = [visible[round(i * (len(visible) - 1) / 63)] for i in range(64)]
        points = []
        for row in visible:
            identity = sha256(_identity(row["loadouts"]).encode()).hexdigest()[:24]
            points.append(
                {
                    "id": f"frontier-{limit}-{identity}",
                    "solution": row,
                    "dps_loss": dps - row["score"],
                    "dps_loss_pct": 100 * (dps - row["score"]) / dps if dps else None,
                    "secondary_gain": row["secondary_value"] - archive[0]["secondary_value"],
                }
            )
        groups.append(
            {"swap_limit": limit, "baseline_dps": dps, "points": points, "sampled": sampled}
        )
    diagnostics.update(
        ammunition_refinement=cleanup,
        explored_nodes=search.nodes,
        valid_assignments=len(seen),
        work_budget_exhausted=search.nodes >= budget - 5000
        or (thorough and diagnostics["assignment_attempts"] >= 2000),
    )
    return groups, diagnostics, updated, unlimited


def _combat_variants(search: Any, seed: Solution, tick: Callable[[], bool]) -> Iterator[Solution]:
    """Enumerate legal option changes with isolated cache overrides and exact validation."""
    from tracker.gear.optimizer import _solution_key

    states = [seed]
    for role in search.request.roles:
        allowed = role.combat_options
        if allowed is None or role.style == "special":
            continue
        expanded = list(states)
        for state in states:
            equipment = state["loadouts"][role.id]["equipment"]
            weapon = search.items.get(equipment.get("weapon", -1))
            for configured, option in search.configured_options(role, weapon):
                if not tick():
                    return
                performance = search.evaluate(equipment, configured).model_dump(mode="json")
                if not performance["supported"]:
                    continue
                variant = copy(search)
                # Only the selected roles differ. Keep writes local while using
                # the shared immutable cached evaluations for other lookups.
                variant.performance_cache = ChainMap({}, search.performance_cache)
                variant.option_cache = ChainMap({}, search.option_cache)
                # Retain previously chosen options for all other roles in this state.
                for rid, loadout in state["loadouts"].items():
                    key = (rid, tuple(sorted(loadout["equipment"].items())))
                    variant.performance_cache[key] = loadout["performance"]
                    variant.option_cache[key] = loadout["combat_option"]
                key = (role.id, tuple(sorted(equipment.items())))
                variant.performance_cache[key] = performance
                variant.option_cache[key] = option.model_dump(
                    mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
                )
                assignment = {rid: row["equipment"] for rid, row in state["loadouts"].items()}
                solution = variant.solution(assignment, None)
                if solution is not None:
                    expanded.append(solution)
                    yield solution
        states = diverse(pareto(expanded), _solution_key, 128)
