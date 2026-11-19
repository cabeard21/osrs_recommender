"""Reselect concrete spells when individually valid attacks exceed joint risk."""

from __future__ import annotations

from collections.abc import Mapping
from heapq import heappop, heappush
from typing import TYPE_CHECKING, Any

from tracker.gear.combat_options import CombatOption
from tracker.gear.priorities import secondary_value
from tracker.gear.vector_options import OptionVariant, VectorOptions

if TYPE_CHECKING:
    from tracker.gear.optimizer import RoleConfig, _Search

MAX_COMBINATIONS = 512


def _role_choices(
    search: _Search, options: VectorOptions, equipment: Mapping[str, int], role: RoleConfig
) -> list[tuple[tuple[float, float], OptionVariant]]:
    priority = search.request.secondary_priority
    metric_first = getattr(search, "metric_first", False)

    def rank(variant: OptionVariant) -> tuple[float, float]:
        if role.style == "special":
            return (0.0, 0.0)
        dps = float(variant.performance.get("dps") or 0)
        secondary = secondary_value(priority, variant.performance)
        return (-secondary, -dps) if metric_first else (-dps, -secondary)

    if role.style != "magic" or role.combat_options is None:
        selected = search.combat_option(equipment, role)
        option = CombatOption.model_validate(selected) if selected else None
        configured = (
            role.model_copy(
                update={
                    "style": option.style,
                    "stance": option.stance,
                    "spell": option.spell or role.spell,
                    "powered_attack": option.powered_attack,
                    "active_prayer_ids": tuple(search.selected_prayers(equipment, role)),
                }
            )
            if option is not None
            else role
        )
        fixed = OptionVariant(configured, option, search.performance(equipment, role), ())
        return [(rank(fixed), fixed)]

    # Stance and prayer do not change a spell's loose runes on fixed equipment.
    by_spell: dict[tuple[str | None, str | None], tuple[tuple[float, float], OptionVariant]] = {}
    for variant in options.variants(equipment, role):
        assert variant.option is not None
        key = (variant.option.spell, variant.option.powered_attack)
        grade = rank(variant)
        if key not in by_spell or grade < by_spell[key][0]:
            by_spell[key] = (grade, variant)
    return sorted(by_spell.values(), key=lambda row: row[0])


def wilderness_spell_solution(
    search: _Search, assignment: Mapping[str, Mapping[str, int]], limit: int | None
) -> dict[str, Any] | None:
    """Visit the best weighted attack combinations first, within a fixed work limit."""
    roles = search.request.roles
    if not search.rune_limits_active or getattr(search, "_rune_options_fixed", False):
        return None
    if not any(role.style == "magic" and role.combat_options is not None for role in roles):
        return None

    options = getattr(getattr(search, "vector_search", None), "options", None)
    if options is None or options.search is not search:
        options = VectorOptions(search)
    choices = tuple(_role_choices(search, options, assignment[role.id], role) for role in roles)
    if any(not row for row in choices):
        return None
    carried = {item for equipment in assignment.values() for item in equipment.values()}

    def priority(indices: tuple[int, ...]) -> tuple[float, float, tuple[int, ...]]:
        grades = tuple(row[index][0] for row, index in zip(choices, indices, strict=True))
        return (
            sum(grade[0] * role.weight for grade, role in zip(grades, roles, strict=True)),
            sum(grade[1] * role.weight for grade, role in zip(grades, roles, strict=True)),
            indices,
        )

    beginning = (0,) * len(roles)
    queue = [priority(beginning)]
    visited = {beginning}
    for _ in range(MAX_COMBINATIONS):
        if not queue:
            break
        if search.cancelled and search.cancelled():
            raise ValueError("optimization_cancelled")
        _, _, indices = heappop(queue)
        selected = tuple(row[index][1] for row, index in zip(choices, indices, strict=True))
        combat_options = {
            role.id: variant.option.model_dump(include={"attack_type", "spell", "powered_attack"})
            for role, variant in zip(roles, selected, strict=True)
            if variant.option is not None
        }
        runes = search.runes_for_loadouts(assignment, combat_options)
        if search.complete_runes_fit(carried, runes):
            solution = options.solution(assignment, selected)
            if solution is not None and (limit is None or solution["maximum_actions"] <= limit):
                return solution

        for dimension, index in enumerate(indices):
            if index + 1 == len(choices[dimension]):
                continue
            neighbor = (*indices[:dimension], index + 1, *indices[dimension + 1 :])
            if neighbor not in visited:
                visited.add(neighbor)
                heappush(queue, priority(neighbor))
    return None
