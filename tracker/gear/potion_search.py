"""Combine frozen potion branches without mixing their scoring caches."""

from __future__ import annotations

import hashlib
import json
from time import perf_counter
from typing import Any

from tracker.gear.potions import PotionPolicy, potion_setups, relevant_boost_skills


def merge_results(
    request: Any, branches: list[dict[str, Any]], *, complete_frontiers: bool = False
) -> dict[str, Any]:
    """Merge the independent objective archives, preserving each selected setup."""
    from tracker.gear.frontier import pareto
    from tracker.gear.optimizer import _solution_key
    from tracker.gear.running_frontier import publish_groups

    def best(rows: Any) -> Any:
        return min((r for r in rows if r is not None), key=_solution_key, default=None)

    unrestricted = best(r["unrestricted"] for r in branches)
    winners = [
        best(r["curve"][i]["solution"] for r in branches) for i in range(request.max_swaps + 1)
    ]
    selected = winners[-1]
    chosen = next((r for r in branches if r["selected_solution"] == selected), branches[0])
    baseline = unrestricted["score"] if unrestricted else 0
    curve = [
        {
            "swap_limit": i,
            "solution": row,
            "status": "best_found" if row else "no_feasible_solution_found",
            "relative_performance": row["score"] / baseline if baseline and row else None,
        }
        for i, row in enumerate(winners)
    ]
    secondary = []
    for limit in [*range(request.max_swaps + 1), None]:
        rows = pareto(
            point["solution"]
            for result in branches
            for group in result["secondary_frontiers"]
            if group["swap_limit"] == limit
            for point in group["points"]
        )
        if not rows:
            continue
        dps = rows[0]["score"]
        visible = [
            r
            for r in rows
            if complete_frontiers
            or not dps
            or 100 * (dps - r["score"]) / dps <= request.max_dps_loss_pct
        ]
        sampled = len(visible) > 64 and not complete_frontiers
        if sampled:
            visible = [visible[round(i * (len(visible) - 1) / 63)] for i in range(64)]
        secondary.append(
            {
                "swap_limit": limit,
                "baseline_dps": dps,
                "sampled": sampled,
                "points": [
                    {
                        "id": f"potion-{limit}-"
                        + hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest()[:24],
                        "solution": r,
                        "dps_loss": dps - r["score"],
                        "dps_loss_pct": 100 * (dps - r["score"]) / dps if dps else None,
                        "secondary_gain": r["secondary_value"] - rows[0]["secondary_value"],
                    }
                    for r in visible
                ],
            }
        )
    archives = {
        limit: [
            p["solution"]
            for r in branches
            for g in r.get("running_cost_frontiers", [])
            if g["swap_limit"] == limit
            for p in g["points"]
        ]
        for limit in [*range(request.max_swaps + 1), None]
    }
    baselines = {
        limit: best(
            g.get("baseline_solution")
            for r in branches
            for g in r.get("running_cost_frontiers", [])
            if g["swap_limit"] == limit
        )
        for limit in archives
    }
    running = (
        publish_groups(archives, baselines, request.max_dps_loss_pct, complete_frontiers)
        if any(r.get("running_cost_frontiers") for r in branches)
        else []
    )
    disciplines = []
    for discipline in dict.fromkeys(
        d["discipline"] for r in branches for d in r.get("discipline_results", [])
    ):
        parts = [
            d
            for r in branches
            for d in r.get("discipline_results", [])
            if d["discipline"] == discipline
        ]
        winner = min(
            parts,
            key=lambda d: (
                _solution_key(d["selected_solution"]) if d["selected_solution"] else (float("inf"),)
            ),
        )
        # Discipline detail has no per-cap curve; only publish its selected row
        # and merge its objective archives, leaving global curves authoritative.
        detail = merge_results(
            request,
            [
                {
                    **chosen,
                    **d,
                    "discipline_results": [],
                    "unrestricted": d["selected_solution"],
                    "curve": [{"solution": d["selected_solution"]} for _ in winners],
                    "items": [],
                }
                for d in parts
            ],
        )
        disciplines.append(
            {
                **winner,
                "selected_solution": detail["selected_solution"],
                "secondary_frontiers": detail["secondary_frontiers"],
                "running_cost_frontiers": detail["running_cost_frontiers"],
                "search": detail["search"],
            }
        )
    return {
        **chosen,
        "unrestricted": unrestricted,
        "selected_solution": selected,
        "curve": curve,
        "secondary_frontiers": secondary,
        "running_cost_frontiers": running,
        **(
            {
                "discipline_results": disciplines,
                "discipline_comparison": [
                    {
                        key: d[key]
                        for key in ("discipline", "status", "score", "purchase_cost_gp", "reasons")
                    }
                    for d in disciplines
                ],
            }
            if disciplines
            else {}
        ),
        "items": list({i["item_id"]: i for r in branches for i in r["items"]}.values()),
        "suggested_swap_limit": next(
            (
                p["swap_limit"]
                for p in curve
                if p["relative_performance"] is not None and p["relative_performance"] >= 0.95
            ),
            None,
        ),
        "search": {
            **chosen["search"],
            "explored_nodes": sum(r["search"]["explored_nodes"] for r in branches),
            "candidate_truncation": any(r["search"]["candidate_truncation"] for r in branches),
            "potion_selection": {
                "branch_count": len(branches),
                "policy": "frozen-potion-branches-v1",
            },
        },
    }


def optimize_potions(
    snapshot: Any, request: Any, catalog: Any, content: Any, prices: Any, now: Any, **options: Any
) -> dict[str, Any]:
    from tracker.gear.optimizer import optimize, prepare_optimization

    started = perf_counter()
    progress = options.pop("progress", None)
    branch_runner = options.pop("branch_runner", None)
    prepared = options.pop("_prepared", None)
    levels = {**{k: v.level for k, v in snapshot.skills.items()}, **request.skill_overrides}
    from tracker.gear.auto import branch_requests, merge_auto_results

    auto = request.roles[0].allowed_disciplines is not None
    disciplines = list(branch_requests(request)) if auto else [(None, request)]
    jobs = [
        (
            discipline,
            concrete.model_copy(
                update={"potions": PotionPolicy(mode="fixed", selected_ids=selected)}
            ),
        )
        for discipline, concrete in disciplines
        for selected in potion_setups(
            levels,
            request.potions.allowed_ids,
            prices,
            now,
            relevant_skills=relevant_boost_skills(concrete),
        )
    ]
    requests = [fixed for _, fixed in jobs]
    total = len(requests)

    def report(phase: str, completed: int) -> None:
        if progress:
            progress(
                {
                    "phase": phase,
                    "completed_profiles": completed,
                    "total_profiles": total,
                    "elapsed_seconds": perf_counter() - started,
                }
            )

    report("preparation", 0)
    if branch_runner is None:
        prepared = prepared or prepare_optimization(
            snapshot, request, catalog, content, prices, now
        )
    prepared_at = perf_counter()
    branches = []
    # Complete secondary archives are required before applying the global loss cap.
    branch_options = {
        **options,
        "_complete_frontiers": True,
        "_running_frontier": options.get("_running_frontier", False)
        or (auto and any(d == "magic" for d, _ in disciplines)),
    }
    if branch_runner is not None:
        branches = branch_runner(
            snapshot,
            request,
            catalog,
            content,
            prices,
            now,
            branches=requests,
            progress=progress,
            **branch_options,
        )
        if len(branches) != total:
            raise ValueError("optimizer_worker_unavailable: incomplete potion results")
    else:
        for i, fixed in enumerate(requests):
            cancelled = options.get("cancelled")
            if cancelled and cancelled():
                raise ValueError("optimization_cancelled")
            report("profile_started", i)
            branches.append(
                optimize(
                    snapshot,
                    fixed,
                    catalog,
                    content,
                    prices,
                    now,
                    _prepared=prepared,
                    progress=progress,
                    **branch_options,
                )
            )
            report("profile_completed", i + 1)
    branches_at = perf_counter()
    report("merge", total)
    if auto:
        results = [
            (
                discipline,
                merge_results(
                    concrete,
                    [
                        result
                        for (d, _), result in zip(jobs, branches, strict=True)
                        if d == discipline
                    ],
                    complete_frontiers=True,
                ),
            )
            for discipline, concrete in disciplines
            if discipline is not None
        ]
        result = merge_auto_results(
            request, results, complete_frontiers=options.get("_complete_frontiers", False)
        )
    else:
        result = merge_results(
            request, branches, complete_frontiers=options.get("_complete_frontiers", False)
        )
    assumptions = {
        **result["assumptions"],
        "potion_policy": request.potions.model_dump(mode="json"),
    }
    selection = {
        "branch_count": total,
        "policy": "discipline-relevant-potion-branches-v2",
        "timings_seconds": {
            "preparation": prepared_at - started,
            "branches": branches_at - prepared_at,
            "merge": perf_counter() - branches_at,
            "total": perf_counter() - started,
        },
    }
    report("complete", total)
    return {
        **result,
        "search": {**result["search"], "potion_selection": selection},
        "assumptions": assumptions,
        "assumptions_fingerprint": hashlib.sha256(
            json.dumps(assumptions, sort_keys=True).encode()
        ).hexdigest(),
    }
