"""Attack-resource cost reporting and frozen optimization assumptions."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import TYPE_CHECKING, Any

from tracker.gear.halberd_charging import cost_context

if TYPE_CHECKING:
    from tracker.gear.compact_costs import NumericCost, PreparedCost


def _base_magic(search: Any) -> int | None:
    snapshot = getattr(search, "snapshot", None)
    skill = snapshot.skills.get("magic") if snapshot is not None else None
    return skill.level if skill is not None else None


def needs_running_cost_frontier(request: Any) -> bool:
    """Whether the caller explicitly requested the running cost dimension."""
    return any(obj.kind == "gp_per_damage" for obj in getattr(request, "objectives", ()) or ())


def running_cost_policy(request: Any, thorough: bool = False) -> dict[str, Any]:
    from tracker.gear.running_costs import COST_MODEL_VERSION

    return {
        "policy": "running-cost-objective-v1",
        "cost_model_version": COST_MODEL_VERSION,
        "consumable_budget_policy": "reviewed-expendable-ranged-v1",
        "activation": "explicit-gp-per-damage",
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
