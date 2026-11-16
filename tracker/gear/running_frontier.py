"""Independent, bounded DPS versus attack-resource cost exploration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from math import isfinite
from time import perf_counter
from typing import TYPE_CHECKING, Any

from tracker.gear.halberd_charging import cost_context

if TYPE_CHECKING:
    from tracker.gear.compact_costs import NumericCost, PreparedCost


def _base_magic(search: Any) -> int | None:
    snapshot = getattr(search, "snapshot", None)
    skill = snapshot.skills.get("magic") if snapshot is not None else None
    return skill.level if skill is not None else None


def needs_running_cost_frontier(request: Any, catalog: Any = None) -> bool:
    """Include ranged/magic, demon targets, and eligible charged melee gear."""
    ordinary = [r for r in request.roles if r.style != "special"]
    if any(
        (
            bool({"ranged", "magic"}.intersection(r.allowed_disciplines))
            if r.allowed_disciplines is not None
            else r.style in {"ranged", "magic"}
        )
        or bool(getattr(r, "target", None) and "demon" in r.target.traits)
        for r in ordinary
    ):
        return True
    items = catalog if isinstance(catalog, Mapping) else getattr(catalog, "items", {})
    excluded = set(getattr(request, "excluded_item_ids", ()))
    return bool(ordinary) and any(i in items and i not in excluded for i in (23987, 12931))


def cost_scaffolds(original: Any, role: Any) -> list[dict[str, int]]:
    """Keep every legal weapon/ammunition context before cost candidate pruning."""
    bases = original.baselines(role)
    unique = {tuple(sorted(base.items())): base for base in bases}
    return [unique[key] for key in sorted(unique)]


def running_cost_policy(request: Any, thorough: bool = False) -> dict[str, Any]:
    from tracker.gear.finalist_refinement import ASSIGNMENT_LIMIT
    from tracker.gear.running_costs import COST_MODEL_VERSION

    return {
        "policy": "running-cost-frontier-v5-halberds-demonbane",
        "cost_model_version": COST_MODEL_VERSION,
        "consumable_budget_policy": "reviewed-expendable-ranged-v1",
        "activation": "ordinary-attacks-or-demon-v3-halberds",
        "expansion_limit": 1_500_000 if thorough else 500_000,
        "complete_assignment_limit": 10000 if thorough else 0,
        "finalist_assignment_limit": ASSIGNMENT_LIMIT,
    }


def running_cost_assumptions(
    request: Any, prices: Mapping[int, Any], thorough: bool = False
) -> dict[str, Any]:
    """Shared frozen cost inputs for optimization and fixed-loadout evaluations."""
    from tracker.gear.attack_reach import policy_context

    charging = getattr(request, "crystal_halberd_charging", None)
    return {
        **policy_context(request),
        "fire_tome_pages": request.fire_tome_pages,
        "crystal_halberd_charging": charging.model_dump() if charging is not None else None,
        "slayer_tasks": {r.id: getattr(r, "on_slayer_task", False) for r in request.roles},
        "marks_of_darkness": {r.id: getattr(r, "mark_of_darkness", False) for r in request.roles},
        "running_cost_policy": running_cost_policy(request, thorough),
        "running_cost_prices": {
            str(i): {
                key: str(getattr(record, key, None))
                for key in (
                    "high_price_gp",
                    "low_price_gp",
                    "high_trade_at",
                    "low_trade_at",
                    "fetched_at",
                    "source",
                )
            }
            for i, record in sorted(prices.items())
        },
    }


def aggregate_cost(roles: list[tuple[float, dict[str, Any], float]]) -> dict[str, Any]:
    from tracker.gear.running_costs import COST_MODEL_VERSION

    active = [(w, c, d) for w, c, d in roles if w > 0]
    known = bool(active) and all(
        c["status"] == "known"
        and isinstance(c.get("gp_per_hour"), (int, float))
        and isfinite(c["gp_per_hour"])
        and c["gp_per_hour"] >= 0
        for _, c, _ in active
    )
    weight = sum(w for w, _, _ in active)
    spend = sum(w * c["gp_per_hour"] / 3600 for w, c, _ in active) if known else None
    damage = sum(w * d for w, _, d in active)
    return {
        "status": "known" if known and damage > 0 else "unavailable",
        "model_version": COST_MODEL_VERSION,
        "gp_per_attack": active[0][1].get("gp_per_attack") if len(active) == 1 else None,
        "gp_per_second": spend / weight if spend is not None else None,
        "gp_per_hour": spend * 3600 / weight if spend is not None else None,
        "gp_per_damage": spend / damage if spend is not None and damage > 0 else None,
        "resources": [],
        "charging_alternatives": [],
        "charging_assumption": " ".join(
            dict.fromkeys(
                c["charging_assumption"] for _, c, _ in active if c.get("charging_assumption")
            )
        )
        or None,
        "reasons": (
            []
            if known and damage > 0
            else ["An active role has unavailable resource costs or zero total DPS."]
        ),
    }


def _report_prepared_costs(
    solution: dict[str, Any],
    prepared_costs: tuple[tuple[str, PreparedCost, NumericCost, float | None], ...],
    weights: tuple[tuple[str, float], ...],
) -> dict[str, Any]:
    """Expand frozen resource records without retaining the producing search."""
    reports = {
        rid: prepared.report(
            numeric,
            accuracy,
            interval=solution["loadouts"][rid]["performance"].get("attack_interval"),
        )
        for rid, prepared, numeric, accuracy in prepared_costs
    }
    loadouts = {
        rid: {**loadout, "running_cost": reports[rid]}
        for rid, loadout in solution["loadouts"].items()
    }
    costs = [
        (weight, reports[rid], loadouts[rid]["performance"].get("dps") or 0)
        for rid, weight in weights
    ]
    return {**solution, "loadouts": loadouts, "running_cost": aggregate_cost(costs)}


def _numeric_solution_costs(solution: dict[str, Any], search: Any) -> dict[str, Any]:
    from tracker.gear.compact_costs import aggregate_numeric_cost, evaluator
    from tracker.gear.variant_reporting import CompactVariant

    engine = evaluator(search.running_prices, search.running_at)
    loadouts = {}
    costs = {}
    prepared_costs: tuple[tuple[str, PreparedCost, NumericCost, float | None], ...] = ()
    for rid, loadout in solution["loadouts"].items():
        prepared = engine.prepare(
            {slot: search.items[i] for slot, i in loadout["equipment"].items()},
            loadout["combat_option"] or {},
            on_slayer_task=next(
                getattr(r, "on_slayer_task", False) for r in search.request.roles if r.id == rid
            ),
            **cost_context(search.request, rid),
            mark_of_darkness=next(
                getattr(r, "mark_of_darkness", False) for r in search.request.roles if r.id == rid
            ),
            base_magic=_base_magic(search),
        )
        performance = loadout["performance"]
        numeric = prepared.score(
            performance.get("attack_interval"), performance.get("dps"), performance.get("accuracy")
        )
        prepared_costs += ((rid, prepared, numeric, performance.get("accuracy")),)
        costs[rid] = numeric
        loadouts[rid] = {
            **loadout,
            "running_cost": {
                field: getattr(numeric, field) for field in numeric.__dataclass_fields__
            },
        }
    weights = tuple((r.id, r.weight) for r in search.request.roles if r.style != "special")
    aggregate = aggregate_numeric_cost(
        [
            (weight, costs[rid], loadouts[rid]["performance"].get("dps") or 0)
            for rid, weight in weights
        ]
    )
    values = {
        **solution,
        "loadouts": loadouts,
        "running_cost": {
            field: getattr(aggregate, field) for field in aggregate.__dataclass_fields__
        },
    }
    return CompactVariant(values, lambda: _report_prepared_costs(solution, prepared_costs, weights))


def add_solution_costs(
    solution: dict[str, Any], search: Any, *, _defer: bool = True
) -> dict[str, Any]:
    from tracker.gear.compact_costs import active
    from tracker.gear.running_costs import evaluate_running_cost

    if _defer and active() and getattr(search, "compact_cost_ranking", False):
        return _numeric_solution_costs(solution, search)
    loadouts = {}
    for rid, loadout in solution["loadouts"].items():
        option = loadout["combat_option"] or {}
        cost = evaluate_running_cost(
            {slot: search.items[i] for slot, i in loadout["equipment"].items()},
            option,
            loadout["performance"],
            search.running_prices,
            search.running_at,
            on_slayer_task=next(
                getattr(r, "on_slayer_task", False) for r in search.request.roles if r.id == rid
            ),
            **cost_context(search.request, rid),
            mark_of_darkness=next(
                getattr(r, "mark_of_darkness", False) for r in search.request.roles if r.id == rid
            ),
            base_magic=_base_magic(search),
        )
        loadouts[rid] = {**loadout, "running_cost": cost}
    costs = [
        (r.weight, loadouts[r.id]["running_cost"], loadouts[r.id]["performance"].get("dps") or 0)
        for r in search.request.roles
        if r.style != "special"
    ]
    return {**solution, "loadouts": loadouts, "running_cost": aggregate_cost(costs)}


def cost_pareto(rows: Any) -> list[dict[str, Any]]:
    from tracker.gear.variant_reporting import loadout_tie

    ordered = sorted(
        (r for r in rows if r["running_cost"]["gp_per_damage"] is not None),
        key=lambda r: (
            -r["score"],
            r["running_cost"]["gp_per_damage"],
            r["purchase_cost_gp"],
            (r.get("potions") or {}).get("cost_per_application_gp") is None,
            (r.get("potions") or {}).get("cost_per_application_gp") or 0,
            len((r.get("potions") or {}).get("selected_ids", ())),
            loadout_tie(r),
        ),
    )
    result = []
    best = None
    for row in ordered:
        cost = row["running_cost"]["gp_per_damage"]
        if best is None or cost < best:
            result.append(row)
            best = cost
    return result


def publish_groups(
    archives: Any, baselines: Any, cap: float, complete: bool = False
) -> list[dict[str, Any]]:
    from tracker.gear.variant_reporting import materialize

    groups = []
    for limit, rows in archives.items():
        baseline = baselines.get(limit)
        baseline = materialize(baseline) if baseline is not None else None
        dps = baseline["score"] if baseline else None
        visible = [
            materialize(r)
            for r in cost_pareto(rows)
            if complete or not dps or 100 * (dps - r["score"]) / dps <= cap
        ]
        sampled = len(visible) > 64 and not complete
        if sampled:
            visible = [visible[round(i * (len(visible) - 1) / 63)] for i in range(64)]
        points = [
            {
                "id": f"running-cost-{limit}-"
                + sha256(json.dumps(r["loadouts"], sort_keys=True).encode()).hexdigest()[:24],
                "solution": r,
                "dps_loss": max(0, dps - r["score"]) if dps else 0,
                "dps_loss_pct": max(0, 100 * (dps - r["score"]) / dps) if dps else None,
            }
            for r in visible
        ]
        groups.append(
            {
                "swap_limit": limit,
                "baseline_dps": dps,
                "baseline_solution": baseline,
                "points": points,
                "sampled": sampled,
            }
        )
    return groups


def explore_running_costs(
    original: Any, winners: Any, unrestricted: Any, thorough: bool
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from tracker.gear.compact_costs import CostEvaluator, active, aggregate_numeric_cost, evaluator
    from tracker.gear.frontier import explore
    from tracker.gear.optimizer import _Search
    from tracker.gear.priorities import secondary_value

    started = perf_counter()

    class CostSearch(_Search):
        compact_cost_ranking = True
        cost_evaluator: CostEvaluator

        def variant_secondary(self, loadouts: Mapping[str, Mapping[str, Any]]) -> float:
            costs = []
            for role in self.request.roles:
                if role.style == "special" or role.id not in loadouts:
                    continue
                loadout = loadouts[role.id]
                performance = loadout["performance"]
                if not performance.get("supported"):
                    return -1e100
                prepared = self.cost_evaluator.prepare(
                    {s: self.items[i] for s, i in loadout["equipment"].items()},
                    loadout["combat_option"] or {},
                    on_slayer_task=getattr(role, "on_slayer_task", False),
                    **cost_context(self.request, role),
                    mark_of_darkness=getattr(role, "mark_of_darkness", False),
                    base_magic=_base_magic(self),
                )
                dps = performance.get("dps") or 0
                numeric = prepared.score(
                    performance.get("attack_interval"), dps, performance.get("accuracy")
                )
                costs.append((role.weight, numeric, dps))
            cost = aggregate_numeric_cost(costs).gp_per_damage
            return -cost if cost is not None else -1e100

        def secondary(self, loadouts: Any) -> float:
            if active():
                projected = {}
                for role in self.request.roles:
                    if role.style == "special" or role.id not in loadouts:
                        continue
                    equipment = loadouts[role.id]
                    performance, option = self.compact_combat(equipment, role)
                    projected[role.id] = {
                        "equipment": equipment,
                        "performance": performance,
                        "combat_option": option,
                    }
                return self.variant_secondary(projected)
            costs = []
            from tracker.gear.running_costs import evaluate_running_cost

            for role in self.request.roles:
                if role.style == "special" or role.id not in loadouts:
                    continue
                equipment = loadouts[role.id]
                performance = self.performance(equipment, role)
                if not performance.get("supported"):
                    return -1e100
                cost = evaluate_running_cost(
                    {s: self.items[i] for s, i in equipment.items()},
                    self.combat_option(equipment, role) or {},
                    performance,
                    self.running_prices,
                    self.running_at,
                    on_slayer_task=getattr(role, "on_slayer_task", False),
                    **cost_context(self.request, role),
                    mark_of_darkness=getattr(role, "mark_of_darkness", False),
                    base_magic=_base_magic(self),
                )
                costs.append((role.weight, cost, performance.get("dps") or 0))
            cost = aggregate_cost(costs)["gp_per_damage"]
            return -cost if cost is not None else -1e100

        def solution(self, loadouts: Any, limit: int | None) -> dict[str, Any] | None:
            result = super().solution(loadouts, limit)
            if active():
                # super() already used this objective; preserve its deferred cost report.
                return result
            return {**result, "secondary_value": self.secondary(loadouts)} if result else None

    search = CostSearch.__new__(CostSearch)
    search.__dict__ = dict(original.__dict__)
    search.performance_cache = dict(original.performance_cache)
    search.option_cache = dict(original.option_cache)
    search.compact_cache = {}
    search.cost_evaluator = evaluator(search.running_prices, search.running_at)
    search.request = original.request.model_copy(
        update={"secondary_priority": "accuracy", "objectives": None}
    )
    search.native_cost_objective = True
    from tracker.gear.native import reset_context

    reset_context(search, scoring=True)
    search.complete_frontiers = True
    search.secondary_marginals = {}
    # Cost leaders are evaluated against legal ordinary scaffolds, before pool pruning.
    for role in search.request.roles:
        if role.style == "special":
            continue
        sampled_bases = cost_scaffolds(original, role)
        for i in search.eligible:
            slot = search.items[i].slot
            if slot not in {"weapon", "ammunition", "cape", "shield"}:
                continue
            values = [
                search.secondary({role.id: {**b, slot: i}})
                for b in sampled_bases
                if (slot in {"cape", "shield"} or b.get(slot) == i)
                and search.compatible({**b, slot: i})
            ]
            search.secondary_marginals[role.id, i] = max(values, default=-1e100)
    search.pools = dict(original.pools)
    for slot in ("weapon", "ammunition", "cape", "shield"):
        leaders = sorted(
            (i for i in search.eligible if search.items[i].slot == slot),
            key=lambda i: (
                -max(
                    (
                        search.secondary_marginals.get((r.id, i), -1e100)
                        for r in search.request.roles
                    ),
                    default=-1e100,
                ),
                i,
            ),
        )
        tomes = [i for i in search.eligible if slot == "shield" and search.items[i].tome_effect]
        task_staves = [
            i for i in search.eligible if slot == "weapon" and search.items[i].id in {4170, 21255}
        ]
        search.pools[slot] = list(
            dict.fromkeys([None, *original.pools[slot][:16], *leaders[:7], *tomes, *task_staves])
        )

    def objective(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        gp = row["running_cost"]["gp_per_damage"]
        return {
            **row,
            "secondary_priority": "accuracy",
            "secondary_value": -gp if gp is not None else -1e100,
        }

    prepared_at = perf_counter()
    groups, diagnostics, _, _ = explore(
        search, [objective(r) for r in winners], objective(unrestricted), thorough
    )
    explored_at = perf_counter()

    def restore(row: dict[str, Any]) -> dict[str, Any]:
        if getattr(original.request, "objectives", None) is not None:
            from tracker.gear.objectives import annotate_solution

            return annotate_solution(
                {**row, "secondary_priority": "default", "secondary_value": None},
                original.request.objectives,
                original.request.roles,
            )
        roles = [r for r in original.request.roles if r.style != "special"]
        weight = sum(r.weight for r in roles)
        value = sum(
            r.weight
            * secondary_value(
                original.request.secondary_priority, row["loadouts"][r.id]["performance"]
            )
            for r in roles
        ) / (weight or 1)
        return {
            **row,
            "secondary_priority": original.request.secondary_priority,
            "secondary_value": value if original.request.secondary_priority != "default" else None,
        }

    archives = {g["swap_limit"]: [restore(p["solution"]) for p in g["points"]] for g in groups}
    baselines = {}
    for limit, rows in archives.items():
        candidates = [*rows, winners[limit] if limit is not None else unrestricted]
        baselines[limit] = max((r for r in candidates if r), key=lambda r: r["score"], default=None)
    groups = publish_groups(
        archives, baselines, original.request.max_dps_loss_pct, original.complete_frontiers
    )
    published_at = perf_counter()
    diagnostics = {
        **diagnostics,
        **running_cost_policy(original.request, thorough),
        "exploration": {"timings_seconds": diagnostics["timings_seconds"]},
        "timings_seconds": {
            "preparation": prepared_at - started,
            "exploration": explored_at - prepared_at,
            "publication": published_at - explored_at,
            "total": published_at - started,
        },
    }
    return groups, diagnostics
