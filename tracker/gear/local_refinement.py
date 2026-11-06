"""Opt-in bounded exact improvement of completed, fully validated incumbents."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from copy import deepcopy
from itertools import combinations, product
from time import perf_counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tracker.gear.optimizer import _Search

Solution = dict[str, Any]
Assignment = dict[str, dict[str, int]]
_MAX_ASSIGNMENTS = 10000
_MAX_HISTORY_SEEDS = 8
_SLOTS = (
    "weapon",
    "shield",
    "ammunition",
    "head",
    "cape",
    "neck",
    "body",
    "legs",
    "hands",
    "feet",
    "ring",
)


def _cancel(search: _Search) -> None:
    if search.cancelled and search.cancelled():
        raise ValueError("optimization_cancelled")


def _assignments(solution: Solution) -> Assignment:
    return {role: dict(row["equipment"]) for role, row in solution["loadouts"].items()}


def _identity(assignment: Assignment) -> tuple[Any, ...]:
    return tuple((role, tuple(sorted(e.items()))) for role, e in sorted(assignment.items()))


def _seeds(winners: list[Solution | None], unrestricted: Solution | None) -> list[Solution]:
    # Give the requested action limit first turn, then unrestricted and lower limits.
    distinct: dict[tuple[Any, ...], Solution] = {}
    for solution in [winners[-1] if winners else None, unrestricted, *winners]:
        if solution is not None:
            distinct.setdefault(_identity(_assignments(solution)), solution)
    return list(distinct.values())


def _group(
    original: Assignment,
    role_id: str,
    slots: tuple[str, ...],
    options: dict[str, tuple[int | None, ...]],
) -> Iterator[Assignment]:
    equipment = original[role_id]
    for selected in product(*(options[slot] for slot in slots)):
        # Pair trials must change both coordinates; single changes have their own phase.
        if any(equipment.get(slot) == item for slot, item in zip(slots, selected, strict=True)):
            continue
        proposed = {slot: item for slot, item in equipment.items() if slot not in slots}
        proposed = {
            **proposed,
            **{slot: item for slot, item in zip(slots, selected, strict=True) if item is not None},
        }
        yield {**original, role_id: proposed}


def _scheduled(
    search: _Search, seeds: list[Solution], options: dict[str, tuple[int | None, ...]], pair: bool
) -> Iterator[Assignment]:
    groups: deque[Iterator[Assignment]] = deque()
    for seed in seeds:
        _cancel(search)
        original = _assignments(seed)
        for role in search.request.roles:
            _cancel(search)
            if role.style == "special":
                continue
            locked = set(search.request.locks) | set(role.locks)
            slots = [s for s in _SLOTS if s not in locked]
            role_options = options
            if pair and role.style in {"stab", "slash", "crush"}:
                # Discover floor breakpoints before low-strength ID-order pairs.
                # This is traversal order only; exact complete ordering accepts trials.
                role_options = {
                    slot: tuple(
                        sorted(
                            values,
                            key=lambda i: (
                                -search.eligible[i].bonuses.melee_strength if i is not None else 0,
                                i or 0,
                            ),
                        )
                    )
                    for slot, values in options.items()
                }
            coordinates = combinations(slots, 2) if pair else ((s,) for s in slots)
            groups.extend(_group(original, role.id, group, role_options) for group in coordinates)
    while groups:
        _cancel(search)
        group = groups.popleft()
        try:
            assignment = next(group)
        except StopIteration:
            continue
        groups.append(group)
        yield assignment


def _accept(
    candidate: Solution,
    winners: list[Solution | None],
    unrestricted: Solution | None,
    key: Callable[[Solution], tuple[Any, ...]],
) -> tuple[list[Solution | None], Solution | None, int, int, int]:
    updated = list(winners)
    objective = ties = 0

    def improvement(incumbent: Solution | None) -> bool:
        nonlocal objective, ties
        if incumbent is not None and key(candidate) >= key(incumbent):
            return False
        if incumbent is None or candidate["score"] > incumbent["score"]:
            objective += 1
        else:
            ties += 1
        return True

    if improvement(unrestricted):
        unrestricted = candidate
    for index in range(candidate["maximum_actions"], len(updated)):
        if improvement(updated[index]):
            updated[index] = candidate
    return updated, unrestricted, objective + ties, objective, ties


def refine_completed(
    search: _Search,
    winners: list[Solution | None],
    unrestricted: Solution | None,
    solution_key: Callable[[Solution], tuple[Any, ...]],
    *,
    limit: int = _MAX_ASSIGNMENTS,
) -> tuple[list[Solution | None], Solution | None, dict[str, Any]]:
    """Try exact single substitutions, then same-role pairs after a plateau.

    Every distinct completed trial consumes one assignment before validation;
    each invokes the existing complete joint validator. Improvements are offered
    only to compatible curve points. No local per-role score can accept a trial.
    Later rounds start from improved finalists, and strict final ordering prevents
    cycles. A separate global cap bounds both validation and extra combat cache
    entries (at most four per assignment). Baseline search limits are untouched.
    """
    if type(limit) is not int or not 0 <= limit <= _MAX_ASSIGNMENTS:
        raise ValueError("refinement limit must be an integer from 0 to 10000")
    started = perf_counter()
    cached_before = len(search.performance_cache)
    _cancel(search)
    updated = list(winners)
    seeds = _seeds(updated, unrestricted)
    diagnostic: dict[str, Any] = {
        "triggered": bool(seeds),
        "reason": "valid_incumbents" if seeds else "no_valid_incumbent",
        "work_budget": limit,
        "work_budget_exhausted": False,
        "assignment_attempts": 0,
        "single_slot_assignments": 0,
        "two_slot_assignments": 0,
        "valid_assignments": 0,
        "incumbent_replacements": 0,
        "objective_improvements": 0,
        "tie_improvements": 0,
        "rounds": 0,
        "history_seed_limit": _MAX_HISTORY_SEEDS,
        "baseline": deepcopy({"curve_solutions": winners, "unrestricted": unrestricted}),
    }
    options: dict[str, tuple[int | None, ...]] = {}
    for slot in _SLOTS:
        _cancel(search)
        ids = []
        for item_id, item in search.eligible.items():
            _cancel(search)
            if item.slot == slot:
                ids.append(item_id)
        options[slot] = (None, *sorted(ids))
    seen = {_identity(_assignments(seed)) for seed in seeds}
    history = list(seeds[:_MAX_HISTORY_SEEDS])
    pair = False
    while seeds:
        _cancel(search)
        diagnostic["rounds"] += 1
        replacements = 0
        trial_seeds = _seeds(updated, unrestricted)
        if pair:
            identities = {_identity(_assignments(seed)) for seed in trial_seeds}
            trial_seeds.extend(
                seed for seed in history if _identity(_assignments(seed)) not in identities
            )
        for assignment in _scheduled(search, trial_seeds, options, pair):
            _cancel(search)
            identity = _identity(assignment)
            if identity in seen:
                continue
            if diagnostic["assignment_attempts"] >= limit:
                diagnostic["work_budget_exhausted"] = True
                break
            seen.add(identity)
            diagnostic["assignment_attempts"] += 1
            reporter = getattr(search, "reporter", None)
            if reporter is not None:
                reporter.fraction(diagnostic["assignment_attempts"] / max(1, limit))
            diagnostic["two_slot_assignments" if pair else "single_slot_assignments"] += 1
            candidate = search.solution(assignment, None)
            _cancel(search)
            if candidate is None:
                continue
            diagnostic["valid_assignments"] += 1
            updated, unrestricted, count, objective, ties = _accept(
                candidate, updated, unrestricted, solution_key
            )
            replacements += count
            if count and len(history) < _MAX_HISTORY_SEEDS:
                identity = _identity(assignment)
                if all(_identity(_assignments(seed)) != identity for seed in history):
                    history.append(candidate)
            diagnostic["incumbent_replacements"] += count
            diagnostic["objective_improvements"] += objective
            diagnostic["tie_improvements"] += ties
        if diagnostic["work_budget_exhausted"]:
            break
        if replacements:
            seeds = _seeds(updated, unrestricted)
            pair = False
        elif not pair:
            pair = True
        else:
            break
    _cancel(search)
    diagnostic["duration_seconds"] = perf_counter() - started
    diagnostic["performance_cache_misses"] = len(search.performance_cache) - cached_before
    diagnostic["history_seeds"] = len(history)
    return updated, unrestricted, diagnostic
