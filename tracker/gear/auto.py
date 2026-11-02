"""Single-role cross-discipline orchestration over fixed, authoritative searches."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from hashlib import sha256
from typing import Any


def branch_requests(request: Any) -> Iterator[tuple[str, Any]]:
    role = request.roles[0]
    for discipline in ("melee", "ranged", "magic"):
        if discipline in (role.allowed_disciplines or ()):
            concrete = role.model_copy(
                update={
                    "allowed_disciplines": None,
                    "style": "slash" if discipline == "melee" else discipline,
                    "stance": "rapid" if discipline == "ranged" else "accurate",
                }
            )
            yield discipline, request.model_copy(update={"roles": (concrete,)})


def optimize_auto(
    snapshot: Any,
    request: Any,
    catalog: Any,
    content: Any,
    price_records: Any,
    now: Any,
    **options: Any,
) -> dict[str, Any]:
    from tracker.gear.frontier import pareto
    from tracker.gear.optimizer import _solution_key, optimize

    branches = []
    for discipline, concrete in branch_requests(request):
        cancelled = options.get("cancelled")
        if cancelled and cancelled():
            raise ValueError("optimization_cancelled")
        result = optimize(
            snapshot,
            concrete,
            catalog,
            content,
            price_records,
            now,
            _complete_frontiers=True,
            **options,
        )
        branches.append((discipline, result))

    def best(rows: Any) -> dict[str, Any] | None:
        return min((r for r in rows if r is not None), key=_solution_key, default=None)

    unrestricted = best(r["unrestricted"] for _, r in branches)
    winners = [
        best(r["curve"][i]["solution"] for _, r in branches) for i in range(request.max_swaps + 1)
    ]
    selected = winners[-1]
    chosen = next((r for _, r in branches if r["selected_solution"] == selected), branches[0][1])
    baseline = unrestricted["score"] if unrestricted else 0
    curve: list[dict[str, Any]] = [
        {
            "swap_limit": i,
            "status": "best_found" if row else "no_feasible_solution_found",
            "solution": row,
            "relative_performance": row["score"] / baseline if row and baseline else None,
        }
        for i, row in enumerate(winners)
    ]
    frontiers = []
    if request.secondary_priority != "default":
        for limit in [*range(request.max_swaps + 1), None]:
            rows = pareto(
                point["solution"]
                for _, result in branches
                for group in result["secondary_frontiers"]
                if group["swap_limit"] == limit
                for point in group["points"]
            )
            dps = rows[0]["score"] if rows else None
            visible = [
                r
                for r in rows
                if not dps or 100 * (dps - r["score"]) / dps <= request.max_dps_loss_pct
            ]
            sampled = len(visible) > 64
            if sampled:
                visible = [visible[round(i * (len(visible) - 1) / 63)] for i in range(64)]
            points = [
                {
                    "id": f"frontier-{limit}-"
                    + sha256(json.dumps(r["loadouts"], sort_keys=True).encode()).hexdigest()[:24],
                    "solution": r,
                    "dps_loss": dps - r["score"],
                    "dps_loss_pct": 100 * (dps - r["score"]) / dps if dps else None,
                    "secondary_gain": r["secondary_value"] - rows[0]["secondary_value"],
                }
                for r in visible
            ]
            frontiers.append(
                {"swap_limit": limit, "baseline_dps": dps, "points": points, "sampled": sampled}
            )
    comparison = []
    for discipline, result in branches:
        row = result["selected_solution"]
        comparison.append(
            {
                "discipline": discipline,
                "status": "best_found" if row else "no_feasible_solution_found",
                "score": row["score"] if row else None,
                "purchase_cost_gp": row["purchase_cost_gp"] if row else None,
                "reasons": [] if row else result["limitations"],
            }
        )
    discipline_results = []
    for summary, (discipline, result) in zip(comparison, branches, strict=True):
        groups = []
        for group in result["secondary_frontiers"]:
            points = group["points"]
            sampled = len(points) > 64
            visible = (
                [points[round(i * (len(points) - 1) / 63)] for i in range(64)]
                if sampled
                else points
            )
            groups.append(
                {
                    **group,
                    "sampled": sampled or group["sampled"],
                    "points": [
                        {**point, "id": f"discipline-{discipline}-{point['id']}"}
                        for point in visible
                    ],
                }
            )
        discipline_results.append(
            {
                **summary,
                "selected_solution": result["selected_solution"],
                "secondary_frontiers": groups,
                "search": result["search"],
                "alternatives": result["alternatives"],
                "limitations": result["limitations"],
            }
        )
    return {
        **chosen,
        "curve": curve,
        "selected_solution": selected,
        "unrestricted": unrestricted,
        "secondary_frontiers": frontiers,
        "discipline_comparison": comparison,
        "discipline_results": discipline_results,
        "items": list({i["item_id"]: i for _, r in branches for i in r["items"]}.values()),
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
            "explored_nodes": sum(r["search"]["explored_nodes"] for _, r in branches),
            "candidate_truncation": any(r["search"]["candidate_truncation"] for _, r in branches),
            "discipline_selection": {
                "policy": "full-per-discipline-v1",
                "branch_count": len(branches),
                "branches": {d: r["search"] for d, r in branches},
            },
        },
    }


def resolve_auto_role(
    role: Any,
    equipment: Mapping[str, int],
    items: Any,
    snapshot: Any,
    levels: Mapping[str, int],
    selected: Mapping[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]] | None:
    """Resolve a fixed loadout against the same legal filters as equipment search."""
    from tracker.gear.combat_options import eligible_combat_options
    from tracker.gear.evaluation import evaluate_equipment

    weapon = items.get(equipment.get("weapon", -1))
    candidates = []
    allowed = role.combat_options
    for discipline in ("melee", "ranged", "magic"):
        if discipline not in role.allowed_disciplines:
            continue
        for option in eligible_combat_options(
            weapon, snapshot, discipline=discipline, levels=levels
        ):
            payload = option.model_dump(
                include={"attack_type", "stance", "spell", "powered_attack"}
            )
            spell_id = option.spell or (
                f"powered:{weapon.id}" if option.powered_attack and weapon else None
            )
            if (
                not option.available
                or option.attack_type not in allowed.attack_types
                or option.stance not in allowed.stances
                or (spell_id is not None and spell_id not in allowed.spells)
                or (selected is not None and payload != dict(selected))
            ):
                continue
            configured = role.model_copy(
                update={
                    "allowed_disciplines": None,
                    "style": option.style,
                    "stance": option.stance,
                    "spell": option.spell or role.spell,
                    "powered_attack": option.powered_attack,
                    "combat_options": None,
                }
            )
            performance = evaluate_equipment(equipment, items, configured, levels)
            if performance.supported:
                candidates.append(
                    (
                        performance.dps or 0,
                        option.attack_type,
                        option.stance,
                        option.spell or "",
                        configured,
                        payload,
                    )
                )
    if not candidates:
        return None
    chosen = max(candidates, key=lambda row: row[:4])
    return chosen[-2], chosen[-1]
