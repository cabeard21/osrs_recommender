"""Combine frozen potion branches without mixing their scoring caches."""

from __future__ import annotations

import hashlib
import json
from time import perf_counter
from typing import Any

from tracker.gear.discipline_assignments import has_auto
from tracker.gear.potions import PotionPolicy, potion_setups, relevant_boost_skills


def merge_objective_frontiers(
    request: Any,
    branches: list[dict[str, Any]],
    *,
    id_prefix: str = "",
    complete_frontiers: bool = False,
) -> dict[str, Any]:
    """Merge complete vectors; browser filtering and chart sampling happen later."""
    objectives = getattr(request, "objectives", None)
    if objectives is None:
        return {}
    from tracker.gear.objectives import objective_definitions
    from tracker.gear.optimizer import _objective_winner_key
    from tracker.gear.vector_publish import filter_groups, publish_groups

    sources: dict[int | None, list[Any]] = {
        cap: [] for cap in [*range(request.max_swaps + 1), None]
    }
    baselines: dict[int | None, dict[str, Any]] = {}

    for branch in branches:
        groups = branch.get("objective_frontiers")
        if groups is None:
            raise ValueError("Objective branch results require complete vector archives")
        for group in groups:
            if group.get("sampled", False):
                raise ValueError("Objective branch results require complete vector archives")
            cap = group["swap_limit"]
            sources[cap].append(group["points"])
            row = group.get("baseline_solution")
            if row is not None and (
                cap not in baselines
                or _objective_winner_key(row) < _objective_winner_key(baselines[cap])
            ):
                baselines[cap] = row
    archives = {
        cap: (point["solution"] for points in groups for point in points)
        for cap, groups in sources.items()
    }
    groups = publish_groups(archives, request, id_prefix=id_prefix, baselines=baselines)
    if not complete_frontiers:
        groups = filter_groups(groups, request.max_dps_loss_pct)
    return {
        "objective_frontiers": groups,
        "objective_definitions": objective_definitions(objectives),
    }


def merge_results(
    request: Any, branches: list[dict[str, Any]], *, complete_frontiers: bool = False
) -> dict[str, Any]:
    """Merge the independent objective archives, preserving each selected setup."""
    from tracker.gear.frontier import pareto
    from tracker.gear.optimizer import _objective_winner_key

    def best(rows: Any) -> Any:
        return min((r for r in rows if r is not None), key=_objective_winner_key, default=None)

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
                _objective_winner_key(d["selected_solution"])
                if d["selected_solution"]
                else (float("inf"),)
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
            complete_frontiers=complete_frontiers
            if getattr(request, "objectives", None) is not None
            else False,
        )
        disciplines.append(
            {
                **winner,
                "selected_solution": detail["selected_solution"],
                "secondary_frontiers": detail["secondary_frontiers"],
                "running_cost_frontiers": detail["running_cost_frontiers"],
                **merge_objective_frontiers(
                    request,
                    [detail],
                    id_prefix=f"discipline-{discipline}-",
                    complete_frontiers=complete_frontiers,
                ),
                "search": detail["search"],
            }
        )
    return {
        **chosen,
        "unrestricted": unrestricted,
        "selected_solution": selected,
        "curve": curve,
        "secondary_frontiers": secondary,
        "running_cost_frontiers": [],
        **merge_objective_frontiers(request, branches, complete_frontiers=complete_frontiers),
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
            **{k: v for k, v in chosen["search"].items() if k != "timings_seconds"},
            "explored_nodes": sum(r["search"]["explored_nodes"] for r in branches),
            "candidate_truncation": any(r["search"]["candidate_truncation"] for r in branches),
            "potion_selection": {
                "branch_count": len(branches),
                "policy": "frozen-potion-branches-v1",
            },
        },
    }


def _no_potion_scores(
    request: Any, requests: list[Any], branches: list[dict[str, Any]]
) -> list[float | None]:
    """Best score found without potions at each swap limit, across disciplines.

    The empty setup is always one of the frozen branches, so this costs no
    extra search; it lets the UI report how much the chosen potions add.
    """
    unboosted = [
        branch
        for fixed, branch in zip(requests, branches, strict=True)
        if not fixed.potions.selected_ids
    ]

    def best(limit: int) -> float | None:
        scores = [
            branch["curve"][limit]["solution"]["score"]
            for branch in unboosted
            if branch["curve"][limit]["solution"]
        ]
        return max(scores, default=None)

    return [best(limit) for limit in range(request.max_swaps + 1)]


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

    auto = has_auto(request)
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

    def report(phase: str, completed: int, **extra: Any) -> None:
        if progress:
            progress(
                {
                    "phase": phase,
                    "completed_profiles": completed,
                    "total_profiles": total,
                    "elapsed_seconds": perf_counter() - started,
                    **extra,
                }
            )

    from tracker.gear.progress import for_lane, lane_label

    labels = [lane_label(d, fixed.potions.selected_ids) for d, fixed in jobs]
    report("preparation", 0, plan={"lanes": labels})
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
            report("profile_started", i, lane=i)
            branches.append(
                optimize(
                    snapshot,
                    fixed,
                    catalog,
                    content,
                    prices,
                    now,
                    _prepared=prepared,
                    progress=for_lane(progress, i),
                    **branch_options,
                )
            )
            report("profile_completed", i + 1, lane=i, lane_status="complete")
    cancelled = options.get("cancelled")
    if cancelled and cancelled():
        raise ValueError("optimization_cancelled")
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
    assumptions_fingerprint = hashlib.sha256(
        json.dumps(assumptions, sort_keys=True).encode()
    ).hexdigest()
    no_potion_scores = _no_potion_scores(request, requests, branches)
    profiles = [
        {
            "discipline": discipline
            or (
                "melee"
                if fixed.roles[0].style in {"stab", "slash", "crush"}
                else fixed.roles[0].style
            )
            if len(fixed.roles) == 1
            else None,
            "selected_ids": list(fixed.potions.selected_ids),
            "search": branch["search"],
        }
        for (discipline, fixed), branch in zip(jobs, branches, strict=True)
    ]
    finished = perf_counter()
    timings = {
        "preparation": prepared_at - started,
        "branches": branches_at - prepared_at,
        "merge": finished - branches_at,
        "total": finished - started,
    }
    selection = {
        "branch_count": total,
        "no_potion_score_by_swap_limit": no_potion_scores,
        "policy": "discipline-relevant-potion-branches-v2",
        "profiles": profiles,
        "timings_seconds": timings,
    }
    report("complete", total)
    return {
        **result,
        "search": {
            **result["search"],
            "timings_seconds": timings,
            "potion_selection": selection,
        },
        "assumptions": assumptions,
        "assumptions_fingerprint": assumptions_fingerprint,
    }
