"""Immutable, canonical objective descriptions and raw numeric projections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from tracker.gear.carried_weight import measure_carried_weight
from tracker.gear.models import EquipmentDefinition

_MINIMIZED_LABELS = {
    "gp_per_damage": ("Running cost", "GP/damage"),
    "wilderness_loss_gp": ("Wilderness loss if PK’d", "GP"),
    "carried_weight_kg": ("Carried gear weight", "kg"),
}
MINIMIZED_OBJECTIVES = frozenset(_MINIMIZED_LABELS)
STYLES = ("stab", "slash", "crush", "ranged", "magic")
BONUSES = {
    "prayer_bonus": "prayer",
    "melee_strength_bonus": "melee_strength",
    "ranged_strength_bonus": "ranged_strength",
    "magic_damage_bonus": "magic_damage",
}


class ObjectiveDescriptor(BaseModel):
    """A defence group or one independent, ordinary-combat metric."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[
        "defence_roll",
        "prayer_bonus",
        "melee_strength_bonus",
        "ranged_strength_bonus",
        "magic_damage_bonus",
        "accuracy",
        "gp_per_damage",
        "wilderness_loss_gp",
        "carried_weight_kg",
    ]
    styles: tuple[Literal["stab", "slash", "crush", "ranged", "magic"], ...] = ()
    aggregation: Literal["minimum", "mean"] | None = None

    @model_validator(mode="after")
    def canonicalize(self) -> ObjectiveDescriptor:
        if self.kind != "defence_roll":
            if self.styles or self.aggregation is not None:
                raise ValueError("Only defence_roll objectives accept styles and aggregation")
            return self
        if not self.styles:
            raise ValueError("A defence_roll objective requires at least one style")
        styles = tuple(style for style in STYLES if style in self.styles)
        object.__setattr__(self, "styles", styles)
        object.__setattr__(
            self, "aggregation", "minimum" if len(styles) == 1 else self.aggregation or "minimum"
        )
        return self

    @property
    def id(self) -> str:
        return (
            f"defence_roll:{self.aggregation}:{'+'.join(self.styles)}"
            if self.kind == "defence_roll"
            else self.kind
        )


def canonical_objectives(values: Iterable[Any]) -> tuple[ObjectiveDescriptor, ...]:
    descriptors = [ObjectiveDescriptor.model_validate(value) for value in values]
    by_id = {descriptor.id: descriptor for descriptor in descriptors}
    if len(by_id) > 64:
        raise ValueError("At most 64 distinct objective functions are supported")
    return tuple(by_id[key] for key in sorted(by_id))


def objective_definitions(objectives: Iterable[ObjectiveDescriptor]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for objective in objectives:
        defence = objective.kind == "defence_roll"
        label = (
            f"{' & '.join(style.title() for style in objective.styles)} defence roll "
            f"({objective.aggregation})"
            if defence
            else objective.kind.replace("_", " ").capitalize()
        )
        if objective.kind in MINIMIZED_OBJECTIVES:
            label, unit = _MINIMIZED_LABELS[objective.kind]
            result.append(
                {
                    "id": objective.id,
                    "kind": objective.kind,
                    "label": label,
                    "unit": unit,
                    "direction": "minimize",
                }
            )
            continue
        result.append(
            {
                "id": objective.id,
                "kind": objective.kind,
                "label": label,
                "unit": "roll"
                if defence
                else "probability"
                if objective.kind == "accuracy"
                else "percent"
                if objective.kind == "magic_damage_bonus"
                else "bonus",
                **(
                    {"styles": list(objective.styles), "aggregation": objective.aggregation}
                    if defence
                    else {}
                ),
            }
        )
    return result


def objective_value(
    objective: ObjectiveDescriptor,
    performance: Mapping[str, Any],
    running_cost: Mapping[str, Any] | None = None,
    wilderness_risk: Mapping[str, Any] | None = None,
    carried_weight: Mapping[str, Any] | None = None,
) -> float:
    if objective.kind == "carried_weight_kg":
        kg = (carried_weight or {}).get("heaviest_kg")
        if kg is None or not isfinite(kg):
            raise ValueError("Carried gear weight is unavailable")
        return float(kg)
    if objective.kind == "wilderness_loss_gp":
        loss = (wilderness_risk or {}).get("loss_gp")
        if type(loss) is not int or loss < 0:
            raise ValueError("Wilderness loss is unavailable")
        return loss
    if objective.kind == "gp_per_damage":
        cost = (running_cost or {}).get("gp_per_damage")
        if cost is None or not isfinite(cost) or cost < 0:
            raise ValueError("Running cost per damage is unavailable")
        return float(cost)
    if performance.get("supported") is False:
        return 0.0
    if objective.kind == "defence_roll":
        rolls = performance.get("player_defence_rolls") or {}
        if any(rolls.get(style) is None for style in objective.styles):
            raise ValueError(
                "Player defensive roll is unavailable: required combat levels are unknown"
            )
        values = [float(rolls[style]) for style in objective.styles]
        value = min(values) if objective.aggregation == "minimum" else sum(values) / len(values)
    elif objective.kind == "accuracy":
        value = float(performance.get("accuracy") or 0)
    else:
        value = float((performance.get("bonuses") or {}).get(BONUSES[objective.kind], 0))
    if not isfinite(value):
        raise ValueError("Objective values must be finite")
    return value


def objective_values(
    objectives: Iterable[ObjectiveDescriptor],
    performance: Mapping[str, Any],
    running_cost: Mapping[str, Any] | None = None,
    wilderness_risk: Mapping[str, Any] | None = None,
    carried_weight: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    values = {}
    for objective in objectives:
        if objective.kind == "gp_per_damage" and (running_cost or {}).get(objective.id) is None:
            continue
        if objective.kind == "carried_weight_kg" and carried_weight is None:
            continue
        if (
            objective.kind == "wilderness_loss_gp"
            and (wilderness_risk or {}).get("loss_gp") is None
        ):
            continue
        values[objective.id] = objective_value(
            objective, performance, running_cost, wilderness_risk, carried_weight
        )
    return values


def required_objective_skills(objectives: Iterable[ObjectiveDescriptor]) -> frozenset[str]:
    styles = {style for objective in objectives for style in objective.styles}
    return frozenset(("defence", "magic") if "magic" in styles else ("defence",) if styles else ())


def _with_kit_weight(
    solution: Mapping[str, Any],
    objectives: tuple[ObjectiveDescriptor, ...],
    items: Mapping[int, EquipmentDefinition] | None,
) -> Mapping[str, Any]:
    if (
        items is None
        or "carried_weight" in solution
        or not any(goal.kind == "carried_weight_kg" for goal in objectives)
    ):
        return solution
    assignment = {role: row["equipment"] for role, row in solution["loadouts"].items()}
    return {**solution, "carried_weight": measure_carried_weight(assignment, items)}


def annotate_solution(
    solution: Mapping[str, Any],
    objectives: tuple[ObjectiveDescriptor, ...],
    roles: Iterable[Any],
    *,
    items: Mapping[int, EquipmentDefinition] | None = None,
) -> dict[str, Any]:
    solution = _with_kit_weight(solution, objectives, items)
    return {
        **solution,
        "objective_definitions": objective_definitions(objectives),
        "objective_values": solution_objectives(solution, objectives, roles),
    }


def solution_objectives(
    solution: Mapping[str, Any],
    objectives: tuple[ObjectiveDescriptor, ...],
    roles: Iterable[Any],
    *,
    items: Mapping[int, EquipmentDefinition] | None = None,
) -> dict[str, float]:
    if items is not None:
        solution = _with_kit_weight(solution, objectives, items)
    included = [
        role for role in roles if role.style != "special" and role.id in solution["loadouts"]
    ]
    weight = sum(role.weight for role in included) or 1
    return {
        objective.id: sum(
            objective_value(objective, solution["loadouts"][role.id]["performance"]) * role.weight
            for role in included
        )
        / weight
        for objective in objectives
        if objective.kind not in MINIMIZED_OBJECTIVES
    } | objective_values(
        (objective for objective in objectives if objective.kind in MINIMIZED_OBJECTIVES),
        {},
        solution.get("running_cost"),
        solution.get("wilderness_risk"),
        solution.get("carried_weight"),
    )


def objective_policy(
    objectives: tuple[ObjectiveDescriptor, ...], thorough: bool = False
) -> dict[str, Any]:
    from tracker.gear.finalist_refinement import ASSIGNMENT_LIMIT

    count = len(objectives)
    expansion_limit = (1_500_000 if thorough else 500_000) * count
    combat_reserve = 25000 * count
    return {
        "policy": "vector-pareto-v2",
        "objective_count": len(objectives),
        "expansion_limit": expansion_limit,
        "combat_reserve": combat_reserve,
        "anchor_expansion_limit": (expansion_limit - combat_reserve) // 4,
        "shared_assignment_limit": 10000 * count,
        "complete_assignment_limit": 10000 * count if thorough else 0,
        "finalist_assignment_limit": ASSIGNMENT_LIMIT if count else 0,
        "finalist_assignment_scope": "per_seed",
        "finalist_total_assignment_limit": ASSIGNMENT_LIMIT * max(64, 2 * (count + 1))
        if count
        else 0,
        "finalist_seed_limit": max(64, 2 * (count + 1)) if count else 0,
        "finalist_per_seed_limit": 2048 if count else 0,
        "beam_width": 256,
        "archive": "exact-raw-complete-configurations",
        "retention": "extremes-normalized-farthest-v1",
    }
