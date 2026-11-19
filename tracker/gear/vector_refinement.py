"""Bounded, vector-safe shared substitutions and complete finalist improvement."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from itertools import chain, combinations, product
from typing import Any

from tracker.gear.finalist_refinement import ASSIGNMENT_LIMIT
from tracker.gear.objectives import annotate_solution
from tracker.gear.vector_archive import dominates, solution_identity, solution_vector
from tracker.gear.vector_retention import retain

Assignment = dict[str, dict[str, int]]


def _cancel(engine: Any) -> None:
    if engine.search.cancelled and engine.search.cancelled():
        raise ValueError("optimization_cancelled")


def _assignment(solution: Mapping[str, Any]) -> Assignment:
    return {key: dict(row["equipment"]) for key, row in solution["loadouts"].items()}


def _seeds(engine: Any, supplied: Iterable[Mapping[str, Any]], limit: int) -> list[Any]:
    """Scan disk archives with a bounded reservoir plus all dimension extrema."""
    first: dict[str, Mapping[str, Any]] = {}
    extremes: dict[tuple[int, bool], tuple[float, Mapping[str, Any]]] = {}
    unique_archives = dict.fromkeys(engine.archives.values())
    rows = chain(supplied, *(archive.iter_solutions() for archive in unique_archives))
    for row in rows:
        _cancel(engine)
        if row is None:
            continue
        if "objective_values" not in row:
            row = annotate_solution(row, engine.objectives, engine.search.request.roles)
        if any(row["objective_values"].get(key) is None for key in engine.ids):
            continue
        identity = solution_identity(row)
        if len(first) < limit:
            first.setdefault(identity, row)
        for index, value in enumerate(solution_vector(row, engine.ids)):
            for maximum in (False, True):
                key = (index, maximum)
                previous = extremes.get(key)
                if previous is None or (value > previous[0] if maximum else value < previous[0]):
                    extremes[key] = (value, row)
    candidates = {**first, **{solution_identity(row): row for _, row in extremes.values()}}
    return retain(
        list(candidates.values()),
        lambda row: solution_vector(row, engine.ids),
        solution_identity,
        limit,
    )


def _choices(
    engine: Any, seed: Mapping[str, Any], *, complete: bool
) -> dict[str, list[int | None]]:
    if not complete:
        return {slot: list(values) for slot, values in engine.pools.items()}
    carried = set(seed["carried_item_ids"])
    return {
        slot: [
            None,
            *sorted(
                (
                    item
                    for item, definition in engine.search.eligible.items()
                    if definition.slot == slot
                ),
                key=lambda item: (item not in carried, item),
            ),
        ]
        for slot in engine.pools
    }


def _coordinates(engine: Any, seed: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [
        (role.id, slot)
        for role in engine.search.request.roles
        if role.style != "special"
        for slot in engine.pools
        if slot not in engine.search.request.locks and slot not in role.locks
    ]


def _replace(
    engine: Any, assignment: Assignment, coordinate: tuple[str, str], item: int | None
) -> Assignment:
    role_id, slot = coordinate
    equipment = {key: value for key, value in assignment[role_id].items() if key != slot}
    if item is not None:
        equipment = {**equipment, slot: item}
        if slot == "weapon" and engine.search.items[item].two_handed:
            role = next(role for role in engine.search.request.roles if role.id == role_id)
            if "shield" not in engine.search.request.locks and "shield" not in role.locks:
                equipment = {key: value for key, value in equipment.items() if key != "shield"}
    return {**assignment, role_id: equipment}


def _round_robin(iterators: Iterable[Iterator[Any]]) -> Iterator[Any]:
    queues = deque(iterators)
    while queues:
        iterator = queues.popleft()
        try:
            yield next(iterator)
            queues.append(iterator)
        except StopIteration:
            continue


def _single_trials(engine: Any, seed: Mapping[str, Any]) -> Iterator[Assignment]:
    assignment = _assignment(seed)
    choices = _choices(engine, seed, complete=True)

    def trials(coordinate: tuple[str, str]) -> Iterator[Assignment]:
        for item in choices[coordinate[1]]:
            if assignment[coordinate[0]].get(coordinate[1]) != item:
                yield _replace(engine, assignment, coordinate, item)

    return _round_robin(trials(coordinate) for coordinate in _coordinates(engine, seed))


def _shared_trials(engine: Any, seed: Mapping[str, Any]) -> Iterator[Assignment]:
    assignment = _assignment(seed)
    roles = tuple(role for role in engine.search.request.roles if role.style != "special")
    for slot, choices in engine.pools.items():
        for item in choices:
            if any(
                slot in {**engine.search.request.locks, **role.locks}
                and {**engine.search.request.locks, **role.locks}[slot] != item
                for role in roles
            ):
                continue
            changed = assignment
            for role in roles:
                changed = _replace(engine, changed, (role.id, slot), item)
            if changed != assignment:
                yield changed


def _pair_trials(engine: Any, seed: Mapping[str, Any]) -> Iterator[Assignment]:
    assignment = _assignment(seed)
    coordinates = _coordinates(engine, seed)

    def trials(left: tuple[str, str], right: tuple[str, str]) -> Iterator[Assignment]:
        for first, second in product(engine.pools[left[1]], engine.pools[right[1]]):
            if (
                assignment[left[0]].get(left[1]) == first
                or assignment[right[0]].get(right[1]) == second
            ):
                continue
            changed = _replace(engine, assignment, left, first)
            yield _replace(engine, changed, right, second)

    return _round_robin(trials(left, right) for left, right in combinations(coordinates, 2))


def _safe_improvement(
    candidate: Mapping[str, Any], seed: Mapping[str, Any], ids: tuple[str, ...]
) -> bool:
    return (
        all(candidate["objective_values"].get(key) is not None for key in ids)
        and dominates(solution_vector(candidate, ids), solution_vector(seed, ids))
        and all(
            candidate[key] <= seed[key]
            for key in (
                "purchase_cost_gp",
                "gear_inventory_slots",
                "max_gear_inventory_slots",
                "maximum_actions",
            )
        )
        and len(candidate["transitions"]) == len(seed["transitions"])
        and all(
            a["action_count"] <= b["action_count"]
            for a, b in zip(
                candidate["transitions"],
                seed["transitions"],
                strict=True,
            )
        )
    )


def _finalist(
    engine: Any,
    seed: Mapping[str, Any],
    limit: int = ASSIGNMENT_LIMIT,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    attempts = improvements = 0
    best = seed
    seen: set[str] = set()
    original_offer = engine.offer

    def offer(candidate: Any) -> None:
        nonlocal best, improvements
        original_offer(candidate)
        if candidate is not None and _safe_improvement(candidate, best, engine.ids):
            best = candidate
            improvements += 1

    engine.offer = offer
    try:
        while attempts < limit:
            improved = False
            for assignment in _single_trials(engine, best):
                _cancel(engine)
                identity = engine.identity(assignment)
                if identity in seen:
                    continue
                if attempts >= limit:
                    break
                seen.add(identity)
                attempts += 1
                if progress is not None:
                    progress(attempts / limit)
                previous = improvements
                engine.capture(assignment, charge=False)
                if improvements > previous:
                    improved = True
                    break
            if not improved:
                break
    finally:
        engine.offer = original_offer
    if progress is not None:
        progress(1.0)
    return {
        "evaluated_assignments": attempts,
        "improvements": improvements,
        "work_budget_exhausted": attempts >= limit,
    }


def refine(engine: Any, seeds: Iterable[Mapping[str, Any]], thorough: bool) -> dict[str, Any]:
    """Archive every feasible trial; never replace originals by an incomparable row."""
    count = len(engine.objectives)
    if not count:
        return {
            "shared_assignment_limit": 0,
            "shared_assignment_attempts": 0,
            "complete_assignment_limit": 0,
            "complete_assignment_attempts": 0,
            "finalist_seed_count": 0,
            "finalist_per_seed_limit": ASSIGNMENT_LIMIT,
            "finalist_evaluated_assignments": 0,
            "finalist_improvements": 0,
            "work_budget_exhausted": False,
        }
    pool = _seeds(engine, seeds, max(64, 2 * (len(engine.objectives) + 1)))
    shared_limit, complete_limit = 10000 * count, 10000 * count if thorough else 0
    shared = complete = 0
    report = getattr(engine, "report_refinement", lambda value: None)
    engine.phase_limit = engine.limit
    for assignment in _round_robin(_shared_trials(engine, seed) for seed in pool):
        _cancel(engine)
        if shared >= shared_limit or not engine.tick():
            break
        shared += 1
        engine.capture(assignment, charge=False)
        report(0.2 * shared / shared_limit)
    report(0.2)
    if thorough:
        for assignment in _round_robin(_pair_trials(engine, seed) for seed in pool):
            _cancel(engine)
            if complete >= complete_limit:
                break
            complete += 1
            engine.capture(assignment, charge=False)
            report(0.2 + 0.2 * complete / complete_limit)
    report(0.4)
    finalists = []
    for index, seed in enumerate(pool):

        def progress(value: float, index: int = index) -> None:
            report(0.4 + 0.6 * (index + value) / len(pool))

        finalists.append(_finalist(engine, seed, progress=progress))
    return {
        "shared_assignment_limit": shared_limit,
        "shared_assignment_attempts": shared,
        "complete_assignment_limit": complete_limit,
        "complete_assignment_attempts": complete,
        "finalist_seed_count": len(pool),
        "finalist_per_seed_limit": ASSIGNMENT_LIMIT,
        "finalist_evaluated_assignments": sum(row["evaluated_assignments"] for row in finalists),
        "finalist_improvements": sum(row["improvements"] for row in finalists),
        "work_budget_exhausted": shared >= shared_limit
        or (bool(complete_limit) and complete >= complete_limit)
        or any(row["work_budget_exhausted"] for row in finalists),
    }
