"""Execution-local compact solution projections and exact deferred reports."""

from __future__ import annotations

import json
import weakref
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy, deepcopy
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

from tracker.gear.compact_states import AssignmentState
from tracker.gear.variant_reporting import CompactVariant, _ReportTie, materialize

MAX_SOLUTIONS = 256
MAX_ROLE_REPORTS = 1024


_OWNERS: ContextVar[list[Any] | None] = ContextVar("compact_solution_owners", default=None)


@contextmanager
def solution_scope() -> Iterator[None]:
    owners: list[Any] = []
    token = _OWNERS.set(owners)
    try:
        yield
    finally:
        for reference in owners:
            owner = reference()
            if owner is not None:
                reports = owner.__dict__.pop("_compact_role_reports", None)
                if reports is not None and reports[0]() is owner:
                    reports[1].rows.clear()
                entry = owner.__dict__.pop("_compact_solution_pool", None)
                if entry is not None:
                    entry[1].clear()
        _OWNERS.reset(token)


class _SolutionPool:
    """Intern archive-live records without retaining rejected report factories."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.rows: OrderedDict[tuple[Any, ...], weakref.ReferenceType[CompactSolution] | None] = (
            OrderedDict()
        )

    def lookup(self, key: tuple[Any, ...]) -> tuple[bool, CompactSolution | None]:
        try:
            reference = self.rows[key]
        except KeyError:
            return False, None
        if reference is None:
            self.rows.move_to_end(key)
            return True, None
        row = reference()
        if row is None:
            if self.rows.get(key) is reference:
                del self.rows[key]
            return False, None
        self.rows.move_to_end(key)
        return True, row

    def add(self, key: tuple[Any, ...], row: CompactSolution | None) -> None:
        if row is None:
            self.rows[key] = None
        else:
            pool_ref = weakref.ref(self)

            def released(reference: weakref.ReferenceType[CompactSolution]) -> None:
                pool = pool_ref()
                if pool is not None and pool.rows.get(key) is reference:
                    del pool.rows[key]

            self.rows[key] = weakref.ref(row, released)
        self.rows.move_to_end(key)
        if len(self.rows) > self.capacity:
            self.rows.popitem(last=False)

    def clear(self) -> None:
        self.rows.clear()

    def __len__(self) -> int:
        return len(self.rows)

    def values(self) -> Iterator[CompactSolution | None]:
        for reference in tuple(self.rows.values()):
            yield reference() if reference is not None else None


class _RoleReportPool:
    """Bounded read-only public payload reuse inside one exact search owner."""

    def __init__(self, capacity: int = MAX_ROLE_REPORTS) -> None:
        self.capacity = capacity
        self.rows: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()

    def report(self, key: tuple[Any, ...], factory: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        if key in self.rows:
            self.rows.move_to_end(key)
            return self.rows[key]
        result = factory()
        self.rows[key] = result
        if len(self.rows) > self.capacity:
            self.rows.popitem(last=False)
        return result


def _role_report_pool(search: Any) -> _RoleReportPool:
    owner, pool = getattr(search, "_compact_role_reports", (None, None))
    if owner is None or owner() is not search:
        pool = _RoleReportPool()
        search._compact_role_reports = (weakref.ref(search), pool)
    assert isinstance(pool, _RoleReportPool)
    return pool


@dataclass(frozen=True, slots=True)
class SolutionRecord:
    score: float
    secondary_value: float | None
    purchase_cost_gp: int
    maximum_actions: int
    max_gear_inventory_slots: int
    carried_item_ids: tuple[int, ...]
    transitions: tuple[Any, ...]


class _ReportRecipe:
    """Shared lazy report for a row and its rank, without a bound-row cycle."""

    def __init__(self, report: Any) -> None:
        self.factory = report
        self.full: dict[str, Any] | None = None

    def __call__(self) -> dict[str, Any]:
        if self.full is None:
            full = materialize(self.factory())
            self.full = full
            self.factory = None
        return self.full


class CompactSolution(CompactVariant):
    """Frozen ranking facts with the existing publication-compatible facade."""

    def __init__(self, values: dict[str, Any], report: Any) -> None:
        recipe = _ReportRecipe(report)
        super().__init__(values, recipe)
        self.record = SolutionRecord(
            values["score"],
            values["secondary_value"],
            values["purchase_cost_gp"],
            values["maximum_actions"],
            values["max_gear_inventory_slots"],
            tuple(values["carried_item_ids"]),
            _freeze(values["transitions"]),
        )
        from tracker.gear.optimizer import _solution_key

        rank = _solution_key(self)
        self._compact_rank = (*rank[:-1], _ReportTie(recipe))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple((key, _freeze(item)) for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, float):
        return (float, value.hex())
    if isinstance(value, (int, bool)):
        return (type(value), value)
    return value


def _override_identity(value: Any) -> str | None:
    """Exact JSON distinctions in seeded public reports, encoded by C machinery."""
    return json.dumps(value, sort_keys=True) if value is not None else None


def compact_solution(
    search: Any, loadouts: Mapping[str, Mapping[str, int]], limit: int | None
) -> dict[str, Any] | None:
    """Reuse feasible solutions across caps without sharing objective winners."""
    assignment = AssignmentState.from_mapping(loadouts)
    keys = tuple((rid, equipment.identity) for rid, equipment in assignment.roles)
    # Copies used for frontier overrides must never inherit their parent's pool.
    owner, pool = getattr(search, "_compact_solution_pool", (None, None))
    if owner is None or owner() is not search:
        pool = _SolutionPool(MAX_SOLUTIONS)
        search._compact_solution_pool = (weakref.ref(search), pool)
        owners = _OWNERS.get()
        if owners is not None:
            owners.append(weakref.ref(search))
    identity = (
        id(search.request),
        tuple((rid, equipment.ordered_identity) for rid, equipment in assignment.roles),
        tuple(
            (
                _override_identity(search.performance_cache.get(key)),
                _override_identity(search.option_cache.get(key)),
            )
            for key in keys
        ),
    )
    assert isinstance(pool, _SolutionPool)
    found, result = pool.lookup(identity)
    if found:
        return (
            result
            if result is None or limit is None or result["maximum_actions"] <= limit
            else None
        )

    seeded_performance = {
        key: search.performance_cache[key] for key in keys if key in search.performance_cache
    }
    seeded_options = {key: search.option_cache[key] for key in keys if key in search.option_cache}
    numeric = {}
    options = {}
    prayers = {}
    for role in search.request.roles:
        equipment = assignment[role.id]
        performance, option = search.compact_combat(equipment, role)
        numeric[role.id], options[role.id] = performance, option
        key = (role.id, equipment.identity)
        if key in search.performance_cache:
            prayers[role.id] = list((search.option_cache.get(key) or {}).get("__prayer_ids", ()))
        elif role.combat_options is not None or role.prayers.mode != "disabled":
            winner = search.configured_winner(equipment, role, cache_result=True)
            prayers[role.id] = list(winner.role.active_prayer_ids) if winner else []
        else:
            prayers[role.id] = []
    runes = search.runes_for_loadouts(assignment, options)
    trip = search.trip_report(assignment, options)
    if not search.trip_fits(trip) or not search.complete_runes_fit(assignment.carried, runes):
        return cast(dict[str, Any] | None, search.rune_alternative_solution(assignment, limit))
    runes = runes or {}
    values = _numeric_values(search, assignment, numeric, options, prayers, limit, len(runes))
    if values is None:
        if len(runes) > search.request.reserved_supply_slots:
            alternative = search.rune_alternative_solution(assignment, limit)
            if alternative is not None:
                return cast(dict[str, Any], alternative)
        # A cap rejection does not imply unrestricted infeasibility.
        if limit is not None:
            return None
        result = None
    else:
        if trip is not None:
            values = {**values, "wilderness_risk": trip}

        def report() -> dict[str, Any]:
            # One shared execution owner, rather than a copy per candidate.
            # Only publication allocates an isolated exact-report view.
            report_search = copy(search)
            report_search._compact_solution_bypass = True
            report_search.__dict__.pop("_compact_solution_pool", None)
            report_search.performance_cache = dict(seeded_performance)
            report_search.option_cache = dict(seeded_options)
            report_search.compact_cache = search.compact_cache
            report_keys = {
                rid: (
                    rid,
                    equipment.ordered_identity,
                    _override_identity(values["loadouts"][rid]["combat_option"]),
                    tuple(values["loadouts"][rid]["selected_prayer_ids"]),
                    overrides,
                )
                for (rid, equipment), overrides in zip(assignment.roles, identity[2], strict=True)
            }
            return _expand_report(
                report_search, assignment, values, _role_report_pool(search), report_keys, runes
            )

        result = CompactSolution(values, report)
    pool.add(identity, result)
    return result if result is None or limit is None or result["maximum_actions"] <= limit else None


def _numeric_values(
    search: Any,
    assignment: AssignmentState,
    numeric: dict[str, Any],
    options: dict[str, Any],
    prayers: dict[str, Any],
    limit: int | None,
    rune_slots: int,
) -> dict[str, Any] | None:
    from tracker.gear.evaluation import loadout_problems, unowned_untradeables
    from tracker.gear.potions import potion_summary
    from tracker.gear.priorities import secondary_value
    from tracker.gear.running_frontier import _numeric_solution_costs
    from tracker.gear.transitions import inventory_slots

    roles = search.request.roles
    if not search.complete_ammunition_allowed(assignment) or any(
        not numeric[r.id]["supported"] for r in roles
    ):
        return None
    if any(
        loadout_problems(assignment[r.id], search.items, search.facts, search.request, r)
        for r in roles
    ):
        return None
    carried = assignment.carried
    cost = search.feasible_purchase_cost(carried)
    if cost is None:
        return None
    capacity = 28 - max(search.request.reserved_supply_slots, rune_slots)
    occupancies = [inventory_slots(e, carried, search.items) for e in assignment.values()]
    if max(occupancies, default=0) > capacity:
        return None
    transitions = []
    for a, b in search.edges:
        transition = search._transition(
            assignment[a].identity,
            assignment[b].identity,
            carried,
            capacity,
        )
        if transition is None or (limit is not None and transition["action_count"] > limit):
            return None
        transitions.append(
            {
                "from_role": a,
                "to_role": b,
                "action_count": transition["action_count"],
                "max_gear_inventory_slots": transition["max_gear_inventory_slots"],
            }
        )
    scored = tuple(r for r in roles if r.style != "special")
    weight = sum(r.weight for r in scored)
    score = sum((numeric[r.id].get("dps") or 0) * r.weight for r in scored) / (weight or 1)
    priority = search.request.secondary_priority
    # Cost-search subclasses implement independent resource objectives.
    from tracker.gear.optimizer import _Search

    if type(search).secondary is not _Search.secondary:
        secondary = search.secondary(assignment)
    else:
        secondary = (
            sum(secondary_value(priority, numeric[r.id]) * r.weight for r in scored) / (weight or 1)
            if priority != "default"
            else None
        )
    peak = max([*occupancies, *(t["max_gear_inventory_slots"] for t in transitions)], default=0)
    base = search.request.base_role or roles[0].id
    values = {
        "score": score,
        "secondary_priority": priority,
        "secondary_value": secondary,
        "loadouts": {
            r.id: {
                "equipment": assignment[r.id],
                "performance": numeric[r.id],
                "combat_option": options[r.id],
                "selected_prayer_ids": prayers[r.id],
                "discipline": None
                if r.style == "special"
                else "melee"
                if r.style in {"stab", "slash", "crush"}
                else r.style,
            }
            for r in roles
        },
        "transitions": transitions,
        "purchase_cost_gp": cost,
        "unowned_untradeable_item_ids": unowned_untradeables(
            set(carried), search.facts, search.request
        ),
        "carried_item_ids": sorted(carried),
        "distinct_items": len(carried),
        "gear_inventory_slots": inventory_slots(assignment[base], carried, search.items),
        "max_gear_inventory_slots": peak,
        "remaining_supply_slots": 28 - peak,
        "remaining_inventory_slots": capacity - peak,
        "reserved_supply_slots": search.request.reserved_supply_slots,
        "maximum_actions": max((t["action_count"] for t in transitions), default=0),
        "potions": None,
    }
    if hasattr(search, "running_prices"):
        if search.request.potions.mode == "fixed":
            values["potions"] = potion_summary(
                {k: v.level for k, v in search.snapshot.skills.items()},
                search.request.potions.selected_ids,
                search.running_prices,
                search.running_at,
            )
        return dict(_numeric_solution_costs(values, search))
    return values


def _expand_report(
    search: Any,
    assignment: AssignmentState,
    values: dict[str, Any],
    role_reports: _RoleReportPool,
    report_keys: Mapping[str, tuple[Any, ...]],
    runes: Mapping[int, int],
) -> dict[str, Any]:
    """Expand a validated record without repeating feasibility or weighted sums."""
    from tracker.gear.evaluation import purchases
    from tracker.gear.revenant_acquisition import loadout_preparations
    from tracker.gear.running_frontier import add_solution_costs

    if search.cancelled and search.cancelled():
        raise ValueError("optimization_cancelled")
    loadouts = {}
    preparations = loadout_preparations(assignment.carried, search.facts, search.request)
    for role in search.request.roles:
        equipment = assignment[role.id]
        loadouts[role.id] = {
            **values["loadouts"][role.id],
            "equipment": equipment.to_dict(),
            "preparations": [
                preparations[i] for i in sorted(equipment.values()) if i in preparations
            ],
            "performance": role_reports.report(
                report_keys[role.id],
                partial(search.performance, equipment, role),
            ),
        }
    transitions = []
    for a, b in search.edges:
        transition = search._transition(
            assignment[a].identity,
            assignment[b].identity,
            assignment.carried,
            28 - max(search.request.reserved_supply_slots, len(runes)),
        )
        assert transition is not None
        transitions.append({"from_role": a, "to_role": b, **deepcopy(transition)})
    result = {
        **values,
        "loadouts": loadouts,
        "transitions": transitions,
        "purchases": purchases(set(assignment.carried), search.facts, search.request),
    }
    if search.wilderness is not None and "wilderness_risk" not in result:
        result["wilderness_risk"] = search.wilderness_report(
            assignment, search.request.base_role or search.request.roles[0].id, runes
        )
    return (
        add_solution_costs(result, search, _defer=False)
        if hasattr(search, "running_prices")
        else result
    )
