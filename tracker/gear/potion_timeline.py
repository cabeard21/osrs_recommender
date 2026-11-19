"""Fixed-configuration potion previews; never invokes candidate search."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tracker.gear.compact_costs import PreparedCost, aggregate_numeric_cost
from tracker.gear.potions import boosted_levels, catalog

MODEL_VERSION = "potion-decay-v1"


def decay_levels(base: Mapping[str, int], ids: Sequence[str], seconds: int) -> dict[str, int]:
    definitions = {row["id"]: row for row in catalog()}
    if any(key not in definitions for key in ids):
        raise ValueError("Unknown potion ID")
    divine = {
        skill for key in ids if definitions[key]["divine"] for skill in definitions[key]["skills"]
    }
    boosted = boosted_levels(base, ids)
    return {
        skill: (level if seconds < 300 else base[skill])
        if skill in divine
        else max(base[skill], level - seconds // 60)
        for skill, level in boosted.items()
    }


def event_times(base: Mapping[str, int], ids: Sequence[str]) -> tuple[int, ...]:
    fresh = decay_levels(base, ids, 0)
    events = [0]
    previous = fresh
    # The reviewed catalog has boosts of at most 19 at level 99.
    end = max(300, max((fresh[k] - base[k]) * 60 for k in base)) if base else 300
    for seconds in range(60, end + 1, 60):
        current = decay_levels(base, ids, seconds)
        if current != previous:
            events.append(seconds)
            previous = current
    return (*events, events[-1] + 60)


def measure(
    time: int,
    levels: Mapping[str, int],
    roles: Sequence[Any],
    prepared: Mapping[str, Any],
    priority: Any,
    objectives: Sequence[Any] | None = None,
    prepared_costs: Mapping[str, PreparedCost] | None = None,
    departure_loss_gp: int | None = None,
) -> dict[str, Any]:
    from tracker.gear.combat import evaluate_prepared_loadout
    from tracker.gear.priorities import secondary_value

    values: dict[str, dict[str, Any]] = {}
    ordinary_objectives = tuple(
        o for o in objectives or () if o.kind not in {"gp_per_damage", "wilderness_loss_gp"}
    )
    costs = []
    for role in roles:
        performance = evaluate_prepared_loadout(prepared[role.id], role, levels)
        row = performance.model_dump(mode="json")
        valid = performance.supported and performance.dps is not None
        objective_measurements: dict[str, float | None] = {}
        if objectives is not None and valid:
            from tracker.gear.objectives import objective_values

            objective_measurements.update(objective_values(ordinary_objectives, row))
        if prepared_costs is not None:
            cost = prepared_costs[role.id].score(
                row.get("attack_interval"), performance.dps, performance.accuracy
            )
            costs.append((role.weight, cost, performance.dps or 0))
            objective_measurements["gp_per_damage"] = (
                cost.gp_per_damage if valid and cost.status == "known" else None
            )
        values[role.id] = {
            "dps": performance.dps if valid else None,
            "secondary_value": secondary_value(priority, row)
            if valid and priority != "default"
            else None,
            "reasons": list(performance.limitations) if not valid else [],
            **({"objective_values": objective_measurements} if objectives is not None else {}),
        }
    active = [role for role in roles if role.weight > 0]
    weight = sum(role.weight for role in active)

    def aggregate(key: str) -> float | None:
        if not weight or any(values[role.id][key] is None for role in active):
            return None
        return float(sum(values[role.id][key] * role.weight for role in active) / weight)

    objective_totals: dict[str, float | None] = {}
    if objectives is not None and weight:
        from tracker.gear.objectives import objective_definitions

        for definition in objective_definitions(objectives):
            key = definition["id"]
            if key == "wilderness_loss_gp":
                objective_totals[key] = departure_loss_gp
                continue
            if key == "gp_per_damage":
                objective_totals[key] = (
                    aggregate_numeric_cost(costs).gp_per_damage
                    if all(values[r.id]["dps"] is not None for r in active)
                    else None
                )
                continue
            objective_totals[key] = (
                sum(values[role.id]["objective_values"][key] * role.weight for role in active)
                / weight
                if all(key in values[role.id]["objective_values"] for role in active)
                else None
            )
    return {
        "time_seconds": time,
        "levels": {k: v for k, v in levels.items() if not k.startswith("_")},
        "dps": aggregate("dps"),
        "secondary_value": aggregate("secondary_value"),
        "roles": values,
        **({"objective_values": objective_totals} if objectives is not None else {}),
    }
