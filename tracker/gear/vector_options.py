"""Concrete attack/prayer alternatives used by the vector equipment search."""

from __future__ import annotations

from collections import ChainMap, OrderedDict
from collections.abc import Mapping
from copy import copy
from dataclasses import dataclass
from typing import Any

from tracker.gear.combat import evaluate_prepared_loadout, evaluate_prepared_score
from tracker.gear.combat_options import CombatOption, ancient_spell_problem
from tracker.gear.evaluation import loadout_problems
from tracker.gear.objectives import annotate_solution, objective_values
from tracker.gear.scoring import PreparedEquipment
from tracker.gear.transitions import inventory_slots


@dataclass(frozen=True)
class OptionVariant:
    configured: Any
    option: CombatOption | None
    performance: Mapping[str, Any]
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class NumericFeasibility:
    maximum_actions: int
    purchase_cost_gp: int
    gear_inventory_slots: int
    max_gear_inventory_slots: int


class VectorOptions:
    """Bounded numeric cache; rich performance is materialized only for archive admission."""

    def __init__(self, search: Any) -> None:
        self.search = search
        self.objectives = search.request.objectives or ()
        self.cache: OrderedDict[Any, tuple[OptionVariant, ...]] = OrderedDict()
        self.envelope_cache: OrderedDict[Any, tuple[float, ...] | None] = OrderedDict()
        self.role_indices = {
            role.id: index for index, role in enumerate(getattr(search.request, "roles", ()))
        }

    def variants(self, equipment: Mapping[str, int], role: Any) -> tuple[OptionVariant, ...]:
        identity = role.id, tuple(sorted(equipment.items()))
        if identity in self.cache:
            self.cache.move_to_end(identity)
            return self.cache[identity]
        result = self._variants(equipment, role)
        self.cache[identity] = result
        if len(self.cache) > 512:
            self.cache.popitem(last=False)
        return result

    def projection(
        self, equipment: Mapping[str, int], roles: tuple[Any, ...], *, require_supported: bool
    ) -> tuple[float, ...] | None:
        """Compute legality and the component envelope in the same numeric cache visit."""
        included = []
        for role in roles:
            values = self.envelope(equipment, role)
            if require_supported and values is None:
                return None
            if role.style != "special":
                included.append((role, values or (0.0,) * (len(self.objectives) + 1)))
        weight = sum(role.weight for role, _ in included) or 1
        return tuple(
            sum(values[index] * role.weight for role, values in included) / weight
            for index in range(len(self.objectives) + 1)
        )

    def envelope(self, equipment: Mapping[str, int], role: Any) -> tuple[float, ...] | None:
        """Keep only small numeric component maxima for partial-beam ranking."""
        identity = role.id, tuple(sorted(equipment.items()))
        if identity in self.envelope_cache:
            self.envelope_cache.move_to_end(identity)
            return self.envelope_cache[identity]
        native = getattr(self.search, "native_context", None)
        if role.style == "special":
            result: tuple[float, ...] | None = (0.0,) * (len(self.objectives) + 1)
        elif native is not None and hasattr(native, "score_projection"):
            result = native.score_projection(equipment, self.role_indices[role.id])
        else:
            alternatives = self.variants(equipment, role)
            result = (
                tuple(
                    max(option.values[index] for option in alternatives)
                    for index in range(len(self.objectives) + 1)
                )
                if alternatives
                else None
            )
        self.envelope_cache[identity] = result
        if len(self.envelope_cache) > 4096:
            self.envelope_cache.popitem(last=False)
        return result

    def _variants(self, equipment: Mapping[str, int], role: Any) -> tuple[OptionVariant, ...]:
        if role.style == "special":
            return (
                OptionVariant(
                    role,
                    None,
                    {"supported": True, "dps": None},
                    (0.0,) * (len(self.objectives) + 1),
                ),
            )
        native = self.search.native_context
        if native is not None:
            from tracker.gear.native.packing import BONUS_FIELDS

            index = next(
                i for i, current in enumerate(self.search.request.roles) if current.id == role.id
            )
            result = []
            for performance in native.score_variants(equipment, index):
                configured, option = native.option_records[performance["option_index"]]
                public = {
                    **performance,
                    "bonuses": dict(zip(BONUS_FIELDS, performance["bonuses"], strict=True)),
                }
                result.append(
                    OptionVariant(
                        configured,
                        option,
                        public,
                        (
                            float(public["dps"]),
                            *(
                                performance["objective_values"][objective.id]
                                for objective in self.objectives
                            ),
                        ),
                    )
                )
            return tuple(result)
        prepared = self.search.prepare(equipment)
        if not isinstance(prepared, PreparedEquipment):
            return ()
        configured = self.search.configured_options(
            role, self.search.items.get(equipment.get("weapon", -1))
        )
        if role.combat_options is None and role.prayers.mode == "disabled":
            if (
                role.style == "magic"
                and role.powered_attack is None
                and ancient_spell_problem(
                    self.search.items.get(equipment.get("weapon", -1)),
                    self.search.snapshot,
                    role.spell,
                    role.stance,
                    self.search.levels,
                    mark_of_darkness=role.mark_of_darkness,
                )
            ):
                return ()
            configured = (
                (
                    role,
                    CombatOption(
                        attack_type=role.style,
                        stance=role.stance,
                        spell=role.spell if role.style == "magic" else None,
                        powered_attack=role.powered_attack,
                    ),
                ),
            )
        result = []
        for selected, option in configured:
            score = evaluate_prepared_score(
                prepared, selected, self.search.levels, include_defence=True
            )
            if not score.supported:
                continue
            public = {
                "supported": True,
                "dps": score.dps,
                "accuracy": score.accuracy,
                "bonuses": score.bonuses.__dict__,
                "player_defence_rolls": score.player_defence_rolls,
            }
            values = objective_values(self.objectives, public)
            result.append(
                OptionVariant(
                    selected,
                    option,
                    public,
                    (
                        float(score.dps or 0),
                        *(values[objective.id] for objective in self.objectives),
                    ),
                )
            )
        return tuple(result)

    def numeric_feasibility(
        self,
        assignment: Mapping[str, Mapping[str, int]],
        selected: tuple[OptionVariant, ...],
        *,
        physical_checked: bool = False,
    ) -> NumericFeasibility | None:
        """Apply complete physical/resource checks without constructing combat reports."""
        request = self.search.request
        if any(role.id not in assignment for role in request.roles) or any(
            not alternative.performance["supported"] for alternative in selected
        ):
            return None
        if not physical_checked and any(
            loadout_problems(
                assignment[role.id], self.search.items, self.search.facts, request, role
            )
            for role in request.roles
        ):
            return None
        carried = {item for equipment in assignment.values() for item in equipment.values()}
        cost = self.search.cost(carried)
        if cost > request.budget_gp:
            return None
        capacity = 28 - request.reserved_supply_slots
        occupancies = [
            inventory_slots(equipment, carried, self.search.items)
            for equipment in assignment.values()
        ]
        if max(occupancies, default=0) > capacity:
            return None
        transitions = []
        for source, destination in self.search.edges:
            transition = self.search._transition(
                tuple(sorted(assignment[source].items())),
                tuple(sorted(assignment[destination].items())),
                frozenset(carried),
                capacity,
            )
            if transition is None:
                return None
            transitions.append(transition)
        peak = max(
            [*occupancies, *(transition["max_gear_inventory_slots"] for transition in transitions)],
            default=0,
        )
        base = request.base_role or request.roles[0].id
        return NumericFeasibility(
            max((transition["action_count"] for transition in transitions), default=0),
            cost,
            inventory_slots(assignment[base], carried, self.search.items),
            peak,
        )

    def solution(
        self, assignment: Mapping[str, Mapping[str, int]], selected: tuple[OptionVariant, ...]
    ) -> dict[str, Any] | None:
        from tracker.gear.optimizer import _equipment_identity, _Search

        variant = copy(self.search)
        variant.compact_states = False
        variant.performance_cache = ChainMap({}, self.search.performance_cache)
        variant.option_cache = ChainMap({}, self.search.option_cache)
        for role, alternative in zip(self.search.request.roles, selected, strict=True):
            equipment = assignment[role.id]
            key = role.id, _equipment_identity(equipment)
            if role.style == "special":
                performance = self.search.performance(equipment, role)
            else:
                prepared = self.search.prepare(equipment)
                assert isinstance(prepared, PreparedEquipment)
                performance = evaluate_prepared_loadout(
                    prepared, alternative.configured, self.search.levels
                ).model_dump(mode="json")
            variant.performance_cache[key] = performance
            variant.option_cache[key] = (
                {
                    **alternative.option.model_dump(
                        mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
                    ),
                    "__prayer_ids": list(alternative.configured.active_prayer_ids),
                }
                if alternative.option
                else None
            )
        solution = _Search.solution(variant, assignment, None)
        return (
            annotate_solution(solution, self.objectives, self.search.request.roles)
            if solution
            else None
        )
