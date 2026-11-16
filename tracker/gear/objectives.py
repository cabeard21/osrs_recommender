"""Immutable, canonical objective descriptions and raw numeric projections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

STYLES = ("stab", "slash", "crush", "ranged", "magic")
BONUSES = {
    "prayer_bonus": "prayer",
    "melee_strength_bonus": "melee_strength",
    "ranged_strength_bonus": "ranged_strength",
    "magic_damage_bonus": "magic_damage",
}


class ObjectiveDescriptor(BaseModel):
    """A defence group or one independent, maximized ordinary-combat metric."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[
        "defence_roll",
        "prayer_bonus",
        "melee_strength_bonus",
        "ranged_strength_bonus",
        "magic_damage_bonus",
        "accuracy",
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
    if len(by_id) > 62:
        raise ValueError("At most 62 distinct objective functions are supported")
    return tuple(by_id[key] for key in sorted(by_id))


def objective_definitions(objectives: Iterable[ObjectiveDescriptor]) -> list[dict[str, Any]]:
    result = []
    for objective in objectives:
        defence = objective.kind == "defence_roll"
        label = (
            f"{' & '.join(style.title() for style in objective.styles)} defence roll "
            f"({objective.aggregation})"
            if defence
            else objective.kind.replace("_", " ").capitalize()
        )
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


def objective_value(objective: ObjectiveDescriptor, performance: Mapping[str, Any]) -> float:
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
    objectives: Iterable[ObjectiveDescriptor], performance: Mapping[str, Any]
) -> dict[str, float]:
    return {objective.id: objective_value(objective, performance) for objective in objectives}


def required_objective_skills(objectives: Iterable[ObjectiveDescriptor]) -> frozenset[str]:
    styles = {style for objective in objectives for style in objective.styles}
    return frozenset(("defence", "magic") if "magic" in styles else ("defence",) if styles else ())


def annotate_solution(
    solution: Mapping[str, Any], objectives: tuple[ObjectiveDescriptor, ...], roles: Iterable[Any]
) -> dict[str, Any]:
    included = [
        role for role in roles if role.style != "special" and role.id in solution["loadouts"]
    ]
    weight = sum(role.weight for role in included) or 1
    return {
        **solution,
        "objective_definitions": objective_definitions(objectives),
        "objective_values": {
            objective.id: sum(
                objective_value(objective, solution["loadouts"][role.id]["performance"])
                * role.weight
                for role in included
            )
            / weight
            for objective in objectives
        },
    }


def objective_policy(
    objectives: tuple[ObjectiveDescriptor, ...], thorough: bool = False
) -> dict[str, Any]:
    from tracker.gear.finalist_refinement import ASSIGNMENT_LIMIT

    count = len(objectives)
    expansion_limit = (1_500_000 if thorough else 500_000) * count
    combat_reserve = 25000 * count
    return {
        "policy": "vector-pareto-v1",
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
