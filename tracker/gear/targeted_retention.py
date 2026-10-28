"""Opt-in additive omitted-head trials; bounded discovery preserves baseline ordering."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Collection, Iterator
from copy import deepcopy
from time import perf_counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tracker.gear.optimizer import _Search

Solution = dict[str, Any]
_COMPANIONS = ("cape", "neck", "body", "legs", "hands", "feet", "ring")
_MAX_ASSIGNMENTS = 2000


def _cancel(search: _Search) -> None:
    if search.cancelled and search.cancelled():
        raise ValueError("optimization_cancelled")


def _identity(equipment: dict[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(equipment.items()))


def _trials(
    equipment: dict[str, int], head: int, slot: str | None, options: tuple[int | None, ...]
) -> Iterator[dict[str, int]]:
    if slot is None:
        yield {**equipment, "head": head}
        return
    for item_id in options:
        if item_id == equipment.get(slot):
            continue
        proposed = {s: i for s, i in equipment.items() if s != slot}
        yield {**proposed, "head": head, **({slot: item_id} if item_id is not None else {})}


def _scheduled(
    search: _Search, seeds: list[Solution], heads: list[int], role_id: str, locked: Collection[str]
) -> Iterator[tuple[int, dict[str, int]]]:
    """Each head/seed gets a turn; its next active slot group gets one turn."""
    alternatives: dict[str, list[int]] = {slot: [] for slot in _COMPANIONS if slot not in locked}
    for item_id, item in search.eligible.items():
        _cancel(search)
        if item.slot in alternatives:
            alternatives[item.slot].append(item_id)
    options = {slot: (None, *sorted(ids)) for slot, ids in alternatives.items()}
    queues: deque[tuple[int, deque[Iterator[dict[str, int]]]]] = deque()
    for seed in seeds:
        equipment = seed["loadouts"][role_id]["equipment"]
        for head in heads:
            _cancel(search)
            groups = deque([_trials(equipment, head, None, ())])
            groups.extend(_trials(equipment, head, slot, ids) for slot, ids in options.items())
            queues.append((head, groups))
    while queues:
        _cancel(search)
        head, groups = queues.popleft()
        while groups:
            _cancel(search)
            group = groups.popleft()
            try:
                equipment = next(group)
            except StopIteration:
                continue
            groups.append(group)
            queues.append((head, groups))
            yield head, equipment
            break


def _seeds(
    search: _Search, winners: list[Solution | None], unrestricted: Solution | None, role_id: str
) -> list[Solution]:
    distinct: dict[tuple[tuple[str, int], ...], Solution] = {}
    for solution in [*winners, unrestricted]:
        _cancel(search)
        if solution is None:
            continue
        loadout = solution["loadouts"][role_id]
        if loadout["performance"]["supported"]:
            distinct.setdefault(_identity(loadout["equipment"]), solution)
    return [distinct[key] for key in sorted(distinct)]


def _reason(search: _Search, seeds: list[Solution], heads: list[int]) -> str:
    request = search.request
    if len(request.roles) != 1:
        return "unsupported_scenario"
    role = request.roles[0]
    if (
        role.style not in ("stab", "slash", "crush")
        or role.weight <= 0
        or role.parent_role is not None
        or request.transitions
        or request.ordered_roles
        or request.loop
    ):
        return "unsupported_scenario"
    if "head" in {**request.locks, **role.locks}:
        return "head_locked"
    if not heads:
        return "no_eligible_omitted_heads"
    if not seeds:
        return "no_supported_baseline"
    return "eligible_omitted_heads"


def _accept(
    candidate: Solution,
    winners: list[Solution | None],
    unrestricted: Solution | None,
    solution_key: Callable[[Solution], tuple[Any, ...]],
) -> tuple[list[Solution | None], Solution | None, int]:
    key = solution_key(candidate)
    replacements = 0
    if unrestricted is None or key < solution_key(unrestricted):
        unrestricted = candidate
        replacements += 1
    updated = list(winners)
    for index in range(candidate["maximum_actions"], len(updated)):
        incumbent = updated[index]
        if incumbent is None or key < solution_key(incumbent):
            updated[index] = candidate
            replacements += 1
    return updated, unrestricted, replacements


def refine_omitted_heads(
    search: _Search,
    winners: list[Solution | None],
    unrestricted: Solution | None,
    solution_key: Callable[[Solution], tuple[Any, ...]],
    *,
    limit: int = _MAX_ASSIGNMENTS,
) -> tuple[list[Solution | None], Solution | None, dict[str, Any]]:
    """Refine frozen baseline finalists without changing their search policy.

    The private lower limit supports scheduler tests. No caller may exceed the
    milestone's 2,000 distinct complete assignments. Time is observational only.
    """
    if type(limit) is not int or not 0 <= limit <= _MAX_ASSIGNMENTS:
        raise ValueError("refinement limit must be an integer from 0 to 2000")
    started = perf_counter()
    cached_before = len(search.performance_cache)
    _cancel(search)
    role_id = search.request.roles[0].id
    heads = []
    retained = set(search.pools["head"])
    for item_id, item in search.eligible.items():
        _cancel(search)
        if item.slot == "head" and item_id not in retained:
            heads.append(item_id)
    heads.sort()
    # Multi-role requests are rejected before interpreting per-role winners.
    seeds = _seeds(search, winners, unrestricted, role_id) if len(search.request.roles) == 1 else []
    reason = _reason(search, seeds, heads)
    diagnostics: dict[str, Any] = {
        "triggered": reason == "eligible_omitted_heads",
        "reason": reason,
        "eligible_omitted_item_ids": heads,
        "inspected_item_ids": [],
        "assignment_attempts": 0,
        "valid_assignments": 0,
        "improvements_accepted": 0,
        "incumbent_replacements": 0,
        "work_budget": limit,
        "work_budget_exhausted": False,
        "baseline": deepcopy({"curve_solutions": winners, "unrestricted": unrestricted}),
    }
    updated = list(winners)
    if diagnostics["triggered"]:
        role = search.request.roles[0]
        locked = set(search.request.locks) | set(role.locks)
        seen = {_identity(seed["loadouts"][role_id]["equipment"]) for seed in seeds}
        inspected = set[int]()
        for head, equipment in _scheduled(search, seeds, heads, role_id, locked):
            _cancel(search)
            identity = _identity(equipment)
            if identity in seen:
                continue
            if diagnostics["assignment_attempts"] >= limit:
                diagnostics["work_budget_exhausted"] = True
                break
            seen.add(identity)
            inspected.add(head)
            diagnostics["assignment_attempts"] += 1
            _cancel(search)
            candidate = search.solution({role_id: equipment}, None)
            if candidate is None:
                continue
            diagnostics["valid_assignments"] += 1
            updated, unrestricted, replacements = _accept(
                candidate, updated, unrestricted, solution_key
            )
            diagnostics["incumbent_replacements"] += replacements
            diagnostics["improvements_accepted"] += bool(replacements)
        diagnostics["inspected_item_ids"] = sorted(inspected)
    _cancel(search)
    diagnostics["duration_seconds"] = perf_counter() - started
    diagnostics["performance_cache_misses"] = len(search.performance_cache) - cached_before
    return updated, unrestricted, diagnostics
