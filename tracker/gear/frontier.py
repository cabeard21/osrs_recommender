"""Deterministic bounded search and exact dominance of complete gear assignments."""

from __future__ import annotations

import json
from bisect import bisect_right
from collections import ChainMap, deque
from collections.abc import Callable, Iterable, Iterator
from copy import copy
from hashlib import sha256
from itertools import combinations, product
from operator import attrgetter
from time import perf_counter
from typing import TYPE_CHECKING, Any

from tracker.content.schema import ItemSlot
from tracker.gear.compact_states import AssignmentState, EquipmentState
from tracker.gear.priorities import EQUIPMENT_BONUS_PRIORITIES, ROLL_METRICS
from tracker.gear.progress import NODE_REPORT_MASK, NULL_REPORTER
from tracker.gear.variant_reporting import active as lazy_variants_active
from tracker.gear.variant_reporting import candidate_identity, compact_variant, materialize

if TYPE_CHECKING:
    from tracker.gear.optimizer import _Search

Solution = dict[str, Any]
RankedArchive = tuple[tuple[tuple[Any, ...], Solution], ...]
# Progress shares within one objective pass, independent of its search budgets.
# Finalist refinement has a separate allowance and can outlast beam expansion.
_EXPLORATION_SHARE = 0.65
_AMMUNITION_END = 0.75
_REFINEMENT_END = 0.98


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


def _insert_pareto(archive: RankedArchive, row: Solution, key: tuple[Any, ...]) -> RankedArchive:
    """Insert into an ordered frontier without reranking existing rich solutions.

    Secondary values strictly increase through the archive. An insertion can
    therefore only be dominated by its predecessor and dominate successors.
    Right insertion preserves the stable full-sort winner when keys are equal.
    """
    position = bisect_right(archive, key, key=lambda entry: entry[0])
    secondary = row["secondary_value"]
    if position and archive[position - 1][1]["secondary_value"] >= secondary:
        return archive
    end = position
    while end < len(archive) and archive[end][1]["secondary_value"] <= secondary:
        end += 1
    return (*archive[:position], (key, row), *archive[end:])


def diverse[Row](
    rows: Iterable[Row], rank: Callable[[Row], tuple[Any, ...]], limit: int
) -> list[Row]:
    """Keep extremes and round-robin secondary leaders from eight DPS bands."""
    # Rank evaluation can include exact combat/resource scoring. Decorate once,
    # retaining stable sort order and the original row equality semantics.
    ordered = sorted(((rank(row), row) for row in rows), key=lambda entry: entry[0])
    if len(ordered) <= limit:
        return [row for _, row in ordered]
    # Exact homogeneous compact types have cached physical equality keys.
    # Mixed inputs retain Mapping/list equality, including custom subclasses.
    row_type = type(ordered[0][1])
    identity = (
        attrgetter("slots" if row_type is EquipmentState else "identity")
        if row_type in (EquipmentState, AssignmentState)
        and all(type(row) is row_type for _, row in ordered)
        else None
    )
    scores = [-key[0] for key, _ in ordered]
    low, high = min(scores), max(scores)
    bands: list[list[tuple[tuple[Any, ...], Row]]] = [[] for _ in range(8)]
    for entry, score in zip(ordered, scores, strict=True):
        band = min(7, int(8 * (score - low) / (high - low))) if high > low else 0
        bands[band].append(entry)
    for bucket in bands:
        bucket.sort(key=lambda entry: (entry[0][1], *entry[0]))
    selected = [ordered[0][1]]
    seen = {identity(selected[0])} if identity is not None else set()
    extreme = min(ordered, key=lambda entry: (entry[0][1], *entry[0]))[1]
    if (identity(extreme) not in seen) if identity is not None else extreme != selected[0]:
        selected.append(extreme)
        if identity is not None:
            seen.add(identity(extreme))
    queues = [deque(band) for band in bands]
    while len(selected) < limit and any(queues):
        for queue in queues:
            if queue:
                _, row = queue.popleft()
                if (identity(row) not in seen) if identity is not None else row not in selected:
                    selected.append(row)
                    if identity is not None:
                        seen.add(identity(row))
                    if len(selected) == limit:
                        break
    return selected


def _identity(loadouts: dict[str, Any]) -> str:
    return json.dumps(loadouts, sort_keys=True, separators=(",", ":"))


def _candidate_identity(loadouts: dict[str, Any]) -> str | tuple[Any, ...]:
    from tracker.gear.compact_costs import active as compact_costs_active

    return (
        candidate_identity(loadouts)
        if lazy_variants_active() or compact_costs_active()
        else _identity(loadouts)
    )


def _shared_assignments(
    search: Any, archives: Iterable[list[Solution]]
) -> Iterator[dict[str, Any]]:
    """Round-robin shared slot alternatives without spending extra switch actions."""
    from tracker.gear.optimizer import SLOTS, _assignment_state, _solution_key

    seeds = {
        _candidate_identity(row["loadouts"]): row
        for archive in archives
        for row in diverse(archive, _solution_key, 8)
    }
    locked = set(search.request.locks) | {
        slot for role in search.request.roles for slot in role.locks
    }
    schedules = deque(
        (seed, slot, iter(search.pools[slot]))
        for seed in seeds.values()
        for slot in SLOTS
        if slot not in locked and slot != "weapon" and len(search.pools[slot]) > 1
    )
    while schedules:
        seed, slot, candidates = schedules.popleft()
        try:
            item = next(candidates)
        except StopIteration:
            continue
        schedules.append((seed, slot, candidates))
        assignment = _assignment_state(
            {role: row["equipment"] for role, row in seed["loadouts"].items()}
        )
        if getattr(search, "compact_states", False):
            for role in assignment:
                equipment = assignment[role].without_slot(slot)
                if item is not None:
                    equipment = equipment.with_slot(slot, item)
                assignment = assignment.with_role(role, equipment)
        else:
            assignment = {
                role: {
                    **{s: i for s, i in row["equipment"].items() if s != slot},
                    **({slot: item} if item is not None else {}),
                }
                for role, row in seed["loadouts"].items()
            }
        if any(assignment[r] != seed["loadouts"][r]["equipment"] for r in assignment):
            yield assignment


def _metric_pools(search: Any, original: Any) -> dict[str, list[int | None]]:
    """Round-robin metric, component, damage and affordable candidates."""
    from tracker.gear.optimizer import SLOTS
    from tracker.gear.salve import contextual_candidates as salve_candidates

    pools: dict[str, list[int | None]] = {}
    for slot in SLOTS:
        candidates = [i for i, item in search.eligible.items() if item.slot == slot]
        lanes = []
        for role in search.request.roles:
            if role.style == "special":
                continue
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
        metric = ROLL_METRICS.get(search.request.secondary_priority)
        components = (
            ("magic", "ranged")
            if search.request.secondary_priority == "magic_ranged_defence"
            else metric.styles
            if metric is not None and metric.aggregation == "minimum"
            else ()
        )
        # Individual minima cannot express complementary pieces. Keep each
        # component leader and score their combinations in partial beams.
        for style in components:
            field = "defence_" + style
            lanes.append(
                sorted(
                    candidates,
                    key=lambda i: (
                        -getattr(search.items[i].bonuses, field),
                        i,
                    ),
                )
            )
        lanes.extend(
            [
                [i for i in original.pools[slot] if i is not None],
                sorted(candidates, key=lambda i: (search.cost({i}), i)),
            ]
        )
        queues = deque(iter(lane) for lane in lanes)
        keep: list[int] = []
        while queues and len(keep) < 47:
            lane = queues.popleft()
            item = next(lane, None)
            if item is not None:
                if item not in keep:
                    keep.append(item)
                queues.append(lane)
        if slot == "neck":
            keep = list(
                dict.fromkeys([*keep, *salve_candidates(search.request.roles, search.eligible)])
            )
        pools[slot] = [None, *keep]
    return pools


def explore(
    original: _Search,
    winners: list[Solution | None],
    unrestricted: Solution | None,
    thorough: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[Solution | None], Solution | None]:
    """Preserve the DPS lane and independently explore secondary-diverse beams."""
    from tracker.gear.optimizer import SLOTS, _assignment_state, _solution_key

    started = perf_counter()
    # This isolated search overrides its tick method for a separate work budget.
    search: Any = copy(original)
    from tracker.gear.native import reset_context

    reset_context(search)
    search.compact_cache = {}
    search.frontier_search = True
    search.nodes = 0
    budget = 1_500_000 if thorough else 500_000
    phase_limit = budget - 25000
    search.native_limit = phase_limit
    diagnostics: dict[str, Any] = {
        "policy": "tradeoff-frontier-v2",
        "expansion_limit": budget,
        "explored_nodes": 0,
        "assignment_attempts": 0,
        "complete_assignment_limit": 10000 if thorough else 0,
        "shared_assignment_limit": 10000,
        "shared_assignment_attempts": 0,
        "work_budget_exhausted": False,
    }

    # Metric-lane work already charged to the shared budget, for progress only.
    charged = [0]
    reporter = getattr(original, "reporter", NULL_REPORTER)

    def tick() -> bool:
        if search.cancelled and search.cancelled():
            raise ValueError("optimization_cancelled")
        if search.nodes >= phase_limit:
            return False
        search.nodes += 1
        if not search.nodes & NODE_REPORT_MASK:
            reporter.fraction(_EXPLORATION_SHARE * (charged[0] + search.nodes) / budget)
        return True

    search.tick = tick
    search.native_report = lambda: reporter.fraction(
        _EXPLORATION_SHARE * (charged[0] + search.nodes) / budget
    )
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
                if item is not None and item not in keep and len(keep) < 47:
                    keep.append(item)
        pools[slot] = [None, *keep]
    search.pools = pools
    archives: dict[int | None, list[Solution]] = {
        limit: [] for limit in [*range(search.request.max_swaps + 1), None]
    }
    ranked_archives: dict[int | None, RankedArchive] = dict.fromkeys(archives, ())
    seen = set()
    option_candidates = []

    def accept(solution: Solution | None) -> None:
        nonlocal archives, ranked_archives
        if solution is None:
            return
        identity = _candidate_identity(solution["loadouts"])
        if identity in seen:
            return
        seen.add(identity)
        if any(
            r.combat_options is not None or r.prayers.mode != "disabled"
            for r in search.request.roles
        ):
            option_candidates.append(solution)
            if len(option_candidates) > 256:
                option_candidates[:] = diverse(option_candidates, _solution_key, 128)
        # Rank once across all caps. Identical archives (all Single caps, and
        # often adjacent Multi caps) also share the same immutable update.
        key = _solution_key(solution)
        updates: dict[int, tuple[RankedArchive, list[Solution]]] = {}
        next_archives, next_ranked = dict(archives), dict(ranked_archives)
        for limit in archives:
            if limit is None or solution["maximum_actions"] <= limit:
                previous = ranked_archives[limit]
                archive_id = id(previous)
                if archive_id not in updates:
                    inserted = _insert_pareto(previous, solution, key)
                    rows = (
                        archives[limit]
                        if inserted is previous
                        else [entry[1] for entry in inserted]
                    )
                    updates[archive_id] = inserted, rows
                next_ranked[limit], next_archives[limit] = updates[archive_id]
        archives, ranked_archives = next_archives, next_ranked

    for solution in [*winners, unrestricted]:
        accept(solution)
    pools_at = perf_counter()
    roles = search.request.roles
    # Equipment bonuses do not depend on attack or prayer choice, so these
    # priorities select the same option winner as the DPS lane. Share those
    # evaluations in both directions without changing either equipment beam.
    # Accuracy, defence rolls and CostSearch's accuracy projection still need
    # independent winners, including their recorded options and prayers.
    metric: Any = copy(search)
    reset_context(metric)
    metric.compact_cache = {}
    metric.metric_first = True
    if search.request.secondary_priority not in EQUIPMENT_BONUS_PRIORITIES:
        metric.performance_cache = {}
        metric.option_cache = {}
    metric.nodes = 0
    total_metric_limit = (budget - 25000) // 4
    # Multi must leave room for cap-specific assignments even when its shared
    # seed search exhausts the allowance.
    metric_limit = total_metric_limit // 2 if len(roles) > 1 else total_metric_limit
    metric.native_limit = metric_limit

    def metric_tick() -> bool:
        if metric.cancelled and metric.cancelled():
            raise ValueError("optimization_cancelled")
        if metric.nodes >= metric_limit:
            return False
        metric.nodes += 1
        if not metric.nodes & NODE_REPORT_MASK:
            reporter.fraction(_EXPLORATION_SHARE * metric.nodes / budget)
        return True

    metric.tick = metric_tick
    metric.native_report = lambda: reporter.fraction(_EXPLORATION_SHARE * metric.nodes / budget)
    metric.pools = _metric_pools(metric, original)
    metric_solutions = []
    for equipment in metric.loadouts(roles):
        metric_solutions.append(metric.solution({r.id: equipment for r in roles}, None))
    if len(roles) > 1:
        # Cap-specific allowances prevent unrestricted/early caps from starving
        # constrained defensive alternatives.
        shared_work = metric.nodes
        limits = list(archives)
        per_cap = max(0, (total_metric_limit - shared_work) // len(limits))
        for index, limit in enumerate(limits):
            metric_limit = shared_work + per_cap * (index + 1)
            metric.native_limit = metric_limit
            for assignment in metric.joint_loadouts(limit):
                metric_solutions.append(metric.solution(assignment, limit))
    metric_limit = total_metric_limit
    metric.native_limit = metric_limit
    diagnostics["metric_lane"] = {
        "expansion_limit": metric_limit,
        "explored_nodes": metric.nodes,
        "work_budget_exhausted": metric.nodes >= metric_limit,
    }
    metric_at = perf_counter()
    # Charge actual metric work to the shared total; unused reserved work is
    # available to the diverse lane.
    phase_limit = budget - 25000 - metric.nodes
    search.native_limit = phase_limit
    charged[0] = metric.nodes
    individual = {role.id: search.loadouts((role,)) for role in roles}
    # Shared and joint searches preserve constrained joint solutions.
    common = individual[roles[0].id] if len(roles) == 1 else search.loadouts(roles)
    for equipment in common:
        accept(search.solution({r.id: equipment for r in roles}, None))
    equipment_at = perf_counter()
    if len(roles) > 1:
        for limit in archives:
            for assignment in search.joint_loadouts(limit):
                accept(search.solution(assignment, None))
        # Split the reserved 25,000 expansions between coordinated equipment
        # changes and combat options. Both Fast and Thorough keep their total cap.
        phase_limit = budget - 15000 - metric.nodes
        search.native_limit = phase_limit
        for assignment in _shared_assignments(search, archives.values()):
            if diagnostics["shared_assignment_attempts"] >= 10000 or not tick():
                break
            diagnostics["shared_assignment_attempts"] += 1
            accept(search.solution(assignment, None))
    if thorough:
        # Fair deterministic substitution schedule, shared across all frontier seeds.
        seeds = []
        identities = set()
        for archive in archives.values():
            for row in diverse(archive, _solution_key, 8):
                identity = _candidate_identity(row["loadouts"])
                if identity not in identities:
                    identities.add(identity)
                    seeds.append(row)
        schedules: deque[tuple[Any, str, tuple[ItemSlot, ...], Iterator[tuple[Any, ...]]]] = deque()
        for seed in seeds:
            assignment = _assignment_state(
                {r: row["equipment"] for r, row in seed["loadouts"].items()}
            )
            for role in roles:
                locked = set(search.request.locks) | set(role.locks)
                slots = [s for s in SLOTS if s not in locked]
                for group in [*((s,) for s in slots), *combinations(slots, 2)]:
                    schedules.append(
                        (assignment, role.id, group, iter(product(*(pools[s] for s in group))))
                    )
        while schedules and diagnostics["assignment_attempts"] < 10000:
            assignment, role, group, iterator = schedules.popleft()
            try:
                values = next(iterator)
            except StopIteration:
                continue
            schedules.append((assignment, role, group, iterator))
            if search.cancelled and search.cancelled():
                raise ValueError("optimization_cancelled")
            if getattr(search, "compact_states", False):
                replacement = assignment[role]
                for slot in group:
                    replacement = replacement.without_slot(slot)
                for slot, item in zip(group, values, strict=True):
                    if item is not None:
                        replacement = replacement.with_slot(slot, item)
            else:
                replacement = {s: i for s, i in assignment[role].items() if s not in group}
                replacement.update(
                    {s: i for s, i in zip(group, values, strict=True) if i is not None}
                )
            diagnostics["assignment_attempts"] += 1
            accept(
                search.solution(
                    assignment.with_role(role, replacement)
                    if getattr(search, "compact_states", False)
                    else {**assignment, role: replacement},
                    None,
                )
            )
    assignments_at = perf_counter()
    # Reserve work for option tradeoffs even if equipment beam expansion exhausts its share.
    # Keep the existing shared/refinement seed schedule intact before adding
    # the metric lane; extra early seeds can otherwise crowd out DPS refinements.
    diverse_finalists = [row for archive in archives.values() for row in archive]
    for solution in metric_solutions:
        accept(solution)
    phase_limit = budget - metric.nodes
    search.native_limit = phase_limit
    option_seeds = {
        _candidate_identity(row["loadouts"]): row
        for archive in [option_candidates, *archives.values()]
        for row in archive
    }
    for seed in option_seeds.values():
        for row in _combat_variants(search, seed, tick):
            accept(row)
    options_at = perf_counter()
    # Later equipment and combat-option searches can reintroduce inert ammo.
    # Normalize complete rows before ranking and hashing the published results.
    from tracker.gear.finalist_refinement import ASSIGNMENT_LIMIT, refine_finalist
    from tracker.gear.refinement import refine_ammunition

    cleanup = {"evaluated_assignments": 0, "improved_finalists": 0}
    reporter.fraction(_EXPLORATION_SHARE)
    # A newly dominating metric point must not discard a diverse seed before
    # its local refinement: that seed may improve beyond the new point.
    retained = [*diverse_finalists, *(r for archive in archives.values() for r in archive)]
    cleaned = {
        _identity(row["loadouts"]): row
        for candidate in retained
        for row in [materialize(candidate)]
    }
    normalized = {}
    for index, (identity, row) in enumerate(cleaned.items()):
        normalized[identity] = materialize(refine_ammunition(search, row, _solution_key, cleanup))
        reporter.fraction(
            _EXPLORATION_SHARE + (_AMMUNITION_END - _EXPLORATION_SHARE) * (index + 1) / len(cleaned)
        )
    cleaned = normalized
    reporter.fraction(_AMMUNITION_END)
    ammunition_at = perf_counter()
    finalists = {
        "assignment_limit_per_finalist": ASSIGNMENT_LIMIT,
        "evaluated_assignments": 0,
        "improved_finalists": 0,
        "exhausted_finalists": 0,
        "finalists": len(cleaned),
    }
    refined = {}
    for index, (identity, row) in enumerate(cleaned.items()):

        def report_refinement(fraction: float, index: int = index) -> None:
            reporter.fraction(
                _AMMUNITION_END
                + (_REFINEMENT_END - _AMMUNITION_END) * (index + fraction) / len(cleaned)
            )

        candidate, work = refine_finalist(
            search, row, progress=report_refinement if reporter.active else None
        )
        # Refinement can return a freshly scored candidate whose resource report
        # is deferred, even though the input seed was already materialized.
        refined[identity] = materialize(candidate)
        finalists["evaluated_assignments"] += work["evaluated_assignments"]
        finalists["improved_finalists"] += int(work["improvements"] > 0)
        finalists["exhausted_finalists"] += int(work["work_budget_exhausted"])
        report_refinement(1.0)
    cleaned = refined
    reporter.fraction(_REFINEMENT_END)
    finalists_at = perf_counter()
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
        finalist_refinement=finalists,
        explored_nodes=search.nodes + metric.nodes,
        valid_assignments=len(seen),
        work_budget_exhausted=metric.nodes >= metric_limit
        or search.nodes >= budget - 25000 - metric.nodes
        or diagnostics["shared_assignment_attempts"] >= 10000
        or (thorough and diagnostics["assignment_attempts"] >= 10000),
    )
    published_at = perf_counter()
    diagnostics["timings_seconds"] = {
        "pool_preparation": pools_at - started,
        "metric_lane": metric_at - pools_at,
        "diverse_equipment": equipment_at - metric_at,
        "assignments": assignments_at - equipment_at,
        "combat_variants": options_at - assignments_at,
        "ammunition_refinement": ammunition_at - options_at,
        "finalist_refinement": finalists_at - ammunition_at,
        "publication": published_at - finalists_at,
        "total": published_at - started,
    }
    reporter.fraction(1.0)
    return groups, diagnostics, updated, unlimited


def _combat_variants(search: Any, seed: Solution, tick: Callable[[], bool]) -> Iterator[Solution]:
    """Enumerate legal option changes with isolated cache overrides and exact validation."""
    from tracker.gear.optimizer import _Search, _solution_key

    states = [seed]
    for role in search.request.roles:
        allowed = role.combat_options
        if (allowed is None and role.prayers.mode == "disabled") or role.style == "special":
            continue
        expanded = list(states)
        for state in states:
            equipment = state["loadouts"][role.id]["equipment"]
            weapon = search.items.get(equipment.get("weapon", -1))
            for configured, option in search.configured_options(role, weapon):
                if not tick():
                    return
                if (
                    lazy_variants_active()
                    and not getattr(search, "rune_limits_active", False)
                    and (type(search) is _Search or hasattr(search, "variant_secondary"))
                ):
                    solution = compact_variant(search, state, role, configured, option)
                    if solution is not None:
                        expanded.append(solution)
                        yield solution
                    continue
                performance = search.evaluate(equipment, configured).model_dump(mode="json")
                if not performance["supported"]:
                    continue
                variant = copy(search)
                from tracker.gear.native import reset_context

                reset_context(variant)
                variant.compact_cache = {}
                # Only the selected roles differ. Keep writes local while using
                # the shared immutable cached evaluations for other lookups.
                variant.performance_cache = ChainMap({}, search.performance_cache)
                variant.option_cache = ChainMap({}, search.option_cache)
                # Retain previously chosen options for all other roles in this state.
                for rid, loadout in state["loadouts"].items():
                    key = (rid, tuple(sorted(loadout["equipment"].items())))
                    variant.performance_cache[key] = loadout["performance"]
                    variant.option_cache[key] = {
                        **(loadout["combat_option"] or {}),
                        "__prayer_ids": loadout.get("selected_prayer_ids", []),
                    }
                key = (role.id, tuple(sorted(equipment.items())))
                variant.performance_cache[key] = performance
                variant.option_cache[key] = option.model_dump(
                    mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
                )
                variant.option_cache[key] = {
                    **variant.option_cache[key],
                    "__prayer_ids": list(configured.active_prayer_ids),
                }
                assignment = {rid: row["equipment"] for rid, row in state["loadouts"].items()}
                solution = variant.solution(assignment, None)
                if solution is not None:
                    expanded.append(solution)
                    yield solution
        states = diverse(pareto(expanded), _solution_key, 128)
