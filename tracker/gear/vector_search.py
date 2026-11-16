"""Bounded true-vector gear exploration with complete, disk-backed Pareto archives."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Mapping
from itertools import product
from typing import Any

from tracker.gear.evaluation import loadout_problems
from tracker.gear.objectives import annotate_solution, objective_policy
from tracker.gear.vector_archive import VectorArchive
from tracker.gear.vector_options import OptionVariant, VectorOptions
from tracker.gear.vector_publish import FrontierPoints
from tracker.gear.vector_retention import retain


class VectorSearch:
    """Search projections guide beams; only raw full vectors establish dominance."""

    def __init__(self, search: Any, thorough: bool = False) -> None:
        self.search = search
        self.objectives = search.request.objectives or ()
        self.ids = tuple(objective.id for objective in self.objectives)
        self.policy = objective_policy(self.objectives, thorough)
        self.options = VectorOptions(search)
        caps = [*range(search.request.max_swaps + 1), None]
        common = VectorArchive(self.ids) if len(search.request.roles) == 1 else None
        self.archives = {
            cap: common if common is not None else VectorArchive(self.ids) for cap in caps
        }
        self.seen = self.archives[None].connection
        self.seen.execute(
            "CREATE TABLE seen_assignments(identity TEXT PRIMARY KEY,"
            "cursor INTEGER NOT NULL,complete INTEGER NOT NULL)"
        )
        self.nodes = 0
        self.option_attempts = 0
        self.accepted = 0
        self.complete_attempts = 0
        self.limit = int(self.policy["expansion_limit"])
        self.phase_limit = self.limit
        self.pools: dict[str, list[int | None]] = {}

    def tick(self) -> bool:
        if self.search.cancelled and self.search.cancelled():
            raise ValueError("optimization_cancelled")
        if self.nodes >= self.phase_limit:
            return False
        self.nodes += 1
        if not self.nodes & 1023:
            self.search.reporter.fraction(0.65 * self.nodes / self.limit)
        return True

    def report_refinement(self, value: float) -> None:
        """Reserve the last third of this segment for separately bounded finalists."""
        self.search.reporter.fraction(0.65 + 0.33 * min(1.0, max(0.0, value)))

    @staticmethod
    def identity(assignment: Mapping[str, Mapping[str, int]]) -> str:
        return json.dumps({key: dict(row) for key, row in assignment.items()}, sort_keys=True)

    def offer(self, solution: Mapping[str, Any] | None) -> None:
        if solution is None:
            return
        from tracker.gear.variant_reporting import materialize

        solution = materialize(solution if isinstance(solution, dict) else dict(solution))
        annotated = annotate_solution(solution, self.objectives, self.search.request.roles)
        updated = set()
        for cap, archive in self.archives.items():
            if (cap is None or annotated["maximum_actions"] <= cap) and id(archive) not in updated:
                self.accepted += int(archive.add(annotated))
                updated.add(id(archive))

    def capture_base(self, assignment: Mapping[str, Mapping[str, int]]) -> None:
        """Archive the DPS configuration already scored; queue paid option exploration."""
        if any(role.id not in assignment for role in self.search.request.roles):
            return
        self.offer(self.search.solution(assignment, None))
        if self.objectives:
            self.seen.execute(
                "INSERT OR IGNORE INTO seen_assignments VALUES(?,0,0)", (self.identity(assignment),)
            )

    def capture(self, assignment: Mapping[str, Mapping[str, int]], *, charge: bool = True) -> None:
        """Consider every concrete option product before equipment beam retention."""
        roles = self.search.request.roles
        if not self.objectives:
            return
        if any(role.id not in assignment for role in roles):
            return
        identity = self.identity(assignment)
        previous = self.seen.execute(
            "SELECT cursor,complete FROM seen_assignments WHERE identity=?", (identity,)
        ).fetchone()
        if previous is not None and previous[1]:
            return
        cursor = previous[0] if previous is not None else 0
        self.seen.execute("INSERT OR IGNORE INTO seen_assignments VALUES(?,0,0)", (identity,))
        if any(
            loadout_problems(
                assignment[role.id], self.search.items, self.search.facts, self.search.request, role
            )
            for role in roles
        ):
            self.seen.execute(
                "UPDATE seen_assignments SET complete=1 WHERE identity=?", (identity,)
            )
            return
        alternatives = tuple(self.options.variants(assignment[role.id], role) for role in roles)
        if any(not values for values in alternatives):
            self.seen.execute(
                "UPDATE seen_assignments SET complete=1 WHERE identity=?", (identity,)
            )
            return
        # Physical legality, acquisition, inventory and transition feasibility do
        # not depend on the attack/prayer configuration chosen for this gear.
        first = tuple(values[0] for values in alternatives)
        feasibility = self.options.numeric_feasibility(assignment, first, physical_checked=True)
        if feasibility is None:
            self.seen.execute(
                "UPDATE seen_assignments SET complete=1 WHERE identity=?", (identity,)
            )
            return
        applicable = tuple(
            dict.fromkeys(
                archive
                for cap, archive in self.archives.items()
                if cap is None or feasibility.maximum_actions <= cap
            )
        )
        for position, selected in enumerate(product(*alternatives)):
            if position < cursor:
                continue
            if self.search.cancelled and self.search.cancelled():
                raise ValueError("optimization_cancelled")
            if charge and not self.tick():
                self.seen.execute(
                    "UPDATE seen_assignments SET cursor=? WHERE identity=?", (position, identity)
                )
                return
            self.option_attempts += 1
            self.complete_attempts += 1
            vector = self.weighted(selected, roles)
            if all(archive.strictly_dominated(vector) for archive in applicable):
                continue
            solution = self.options.solution(assignment, selected)
            if solution is not None:
                self.offer(solution)
        self.seen.execute("UPDATE seen_assignments SET complete=1 WHERE identity=?", (identity,))

    @staticmethod
    def weighted(selected: tuple[OptionVariant, ...], roles: Iterable[Any]) -> tuple[float, ...]:
        included = [
            (option, role)
            for option, role in zip(selected, roles, strict=True)
            if role.style != "special"
        ]
        weight = sum(role.weight for _, role in included) or 1
        if not included:
            return selected[0].values
        return tuple(
            sum(option.values[index] * role.weight for option, role in included) / weight
            for index in range(len(included[0][0].values))
        )

    def envelope(
        self, assignment: Mapping[str, Mapping[str, int]], roles: Iterable[Any]
    ) -> tuple[float, ...]:
        """Component maxima are a diversity heuristic, never a feasible vector claim."""
        roles = tuple(role for role in roles if role.id in assignment and role.style != "special")
        weight = sum(role.weight for role in roles) or 1
        values = []
        for role in roles:
            values.append(
                self.options.envelope(assignment[role.id], role)
                or (0.0,) * (len(self.objectives) + 1)
            )
        return tuple(
            sum(value[index] * role.weight for value, role in zip(values, roles, strict=True))
            / weight
            for index in range(len(self.objectives) + 1)
        )

    def candidate_pools(self) -> dict[str, list[int | None]]:
        from tracker.gear.optimizer import SLOTS

        fields = {
            "prayer_bonus": "prayer",
            "melee_strength_bonus": "melee_strength",
            "ranged_strength_bonus": "ranged_strength",
            "magic_damage_bonus": "magic_damage",
        }
        pools: dict[str, list[int | None]] = {}
        for slot in SLOTS:
            candidates = [
                item_id for item_id, item in self.search.eligible.items() if item.slot == slot
            ]
            lanes = [
                [item for item in self.search.pools[slot] if item is not None],
                sorted(candidates, key=lambda item: (self.search.cost({item}), item)),
            ]
            for objective in self.objectives:
                components = ["defence_" + style for style in objective.styles]
                if objective.kind == "defence_roll":
                    from tracker.gear.defensive_rolls import raw_player_defence_rolls
                    from tracker.gear.objectives import objective_value

                    for role in self.search.request.roles:
                        if role.style == "special":
                            continue
                        grades = {
                            item: objective_value(
                                objective,
                                {
                                    "player_defence_rolls": raw_player_defence_rolls(
                                        self.search.levels,
                                        self.search.items[item].bonuses,
                                        role.stance,
                                    )
                                },
                            )
                            for item in candidates
                        }
                        lanes.append(sorted(candidates, key=lambda item: (-grades[item], item)))
                if objective.kind in fields:
                    components = [fields[objective.kind]]
                if objective.kind == "accuracy":
                    components = ["stab", "slash", "crush", "ranged", "magic"]
                for field in components:

                    def component_rank(item: int, field: str = field) -> tuple[float, int]:
                        return -float(getattr(self.search.items[item].bonuses, field)), item

                    lanes.append(
                        sorted(
                            candidates,
                            key=component_rank,
                        )
                    )
            queues = deque(iter(lane) for lane in lanes)
            keep: list[int | None] = [None, *dict.fromkeys(lane[0] for lane in lanes if lane)]
            bound = max(47, 2 * len(self.objectives) + 1)
            while queues and len(keep) <= bound:
                lane = queues.popleft()
                item = next(lane, None)
                if item is not None:
                    if item not in keep:
                        keep.append(item)
                    queues.append(lane)
            pools[slot] = keep
        return pools

    def equipment(
        self, roles: tuple[Any, ...], allowance: int, anchor: int | None = None
    ) -> list[dict[str, int]]:
        from tracker.gear.optimizer import BEAM_WIDTH, SLOTS

        self.phase_limit = min(self.limit, self.nodes + allowance)
        locks = dict(self.search.request.locks)
        for role in roles:
            if any(slot in locks and locks[slot] != item for slot, item in role.locks.items()):
                return []
            locks = {**locks, **role.locks}
        states: list[dict[str, int]] = [{}]
        for slot in SLOTS:
            choices = [locks[slot]] if slot in locks else self.pools[slot]
            expanded = (
                self._native_equipment(roles, states, choices, slot) if slot != SLOTS[-1] else None
            )
            if expanded is None:
                expanded = self._python_equipment(roles, states, choices, slot)

            if anchor is None:
                retained = retain(
                    expanded,
                    lambda row: row[1],
                    lambda row: tuple(sorted(row[0].items())),
                    BEAM_WIDTH,
                )
            else:
                retained = sorted(
                    expanded,
                    key=lambda row: (
                        -row[1][anchor],
                        tuple(-value for value in row[1]),
                        tuple(sorted(row[0].items())),
                    ),
                )[:BEAM_WIDTH]
            states = [row[0] for row in retained]
            if not states:
                break
        return states

    def _python_equipment(
        self,
        roles: tuple[Any, ...],
        states: list[dict[str, int]],
        choices: list[int | None],
        slot: str,
    ) -> list[tuple[dict[str, int], tuple[float, ...]]]:
        from tracker.gear.optimizer import SLOTS

        expanded: list[tuple[dict[str, int], tuple[float, ...]]] = []
        for state, item in product(states, choices):
            if not self.tick():
                break
            candidate = {**state, **({slot: item} if item is not None else {})}
            if (
                not self.search.compatible(candidate)
                or any(item_id not in self.search.eligible for item_id in candidate.values())
                or self.search.cost(set(candidate.values())) > self.search.request.budget_gp
            ):
                continue
            projection = self.options.projection(
                candidate, roles, require_supported=slot not in {"weapon", "shield"}
            )
            if projection is None:
                continue
            assignment = {role.id: candidate for role in roles}
            if slot == SLOTS[-1]:
                self.capture(assignment)
            expanded.append((candidate, projection))

        return expanded

    def _native_equipment(
        self,
        roles: tuple[Any, ...],
        states: list[dict[str, int]],
        choices: list[int | None],
        slot: str,
    ) -> list[tuple[dict[str, int], tuple[float, ...]]] | None:
        """Expand only unfinished gear in bounded native chunks, preserving the node prefix."""
        native = getattr(self.search, "native_context", None)
        if native is None:
            return None
        from tracker.gear.native._stages import StageContext

        context = getattr(self, "_projection_context", None)
        if context is None:
            context = StageContext(native, self.search)
            self._projection_context = context
        if not hasattr(context, "begin_projection"):
            return None
        expansion = context.begin_projection(
            states=states, choices=choices, slot=slot, roles=tuple(role.id for role in roles)
        )
        expanded = []
        while not expansion.done:
            if self.search.cancelled and self.search.cancelled():
                raise ValueError("optimization_cancelled")
            remaining = self.phase_limit - self.nodes
            if remaining <= 0:
                break
            previous = expansion.consumed
            rows = expansion.advance_projection(min(1024 - (self.nodes & 1023), remaining))
            consumed = expansion.consumed - previous
            if consumed <= 0:
                raise RuntimeError("Native vector expansion made no progress")
            self.nodes += consumed
            expanded.extend(rows)
            if self.search.cancelled and self.search.cancelled():
                raise ValueError("optimization_cancelled")
            if not self.nodes & 1023:
                self.search.reporter.fraction(0.65 * self.nodes / self.limit)
        return expanded

    def combine(self, individual: Mapping[str, list[dict[str, int]]], allowance: int) -> None:
        from tracker.gear.optimizer import BEAM_WIDTH, _action_lower_bound

        roles = self.search.request.roles
        caps = [*range(self.search.request.max_swaps + 1), None]
        per_cap = max(1, allowance // len(caps))
        for cap in caps:
            self.phase_limit = min(self.limit, self.nodes + per_cap)
            states: list[dict[str, dict[str, int]]] = [{}]
            for role in roles:
                expanded: list[tuple[dict[str, dict[str, int]], tuple[float, ...]]] = []
                for state, equipment in product(states, individual[role.id]):
                    if not self.tick():
                        break
                    assignment = {**state, role.id: equipment}
                    carried = {item for row in assignment.values() for item in row.values()}
                    if self.search.cost(carried) > self.search.request.budget_gp:
                        continue
                    if cap is not None and any(
                        _action_lower_bound(assignment[a], assignment[b], self.search.items) > cap
                        for a, b in self.search.edges
                        if a in assignment and b in assignment
                    ):
                        continue
                    self.capture(assignment)
                    expanded.append((assignment, self.envelope(assignment, roles)))
                states = [
                    row[0]
                    for row in retain(
                        expanded, lambda row: row[1], lambda row: self.identity(row[0]), BEAM_WIDTH
                    )
                ]
                if not states:
                    break

    def explore(self, seeds: Iterable[Mapping[str, Any] | None]) -> dict[str, Any]:
        candidates = tuple(
            annotate_solution(seed, self.objectives, self.search.request.roles)
            for seed in seeds
            if seed is not None
        )
        for seed in candidates:
            self.offer(seed)
            self.seen.execute(
                "INSERT OR IGNORE INTO seen_assignments VALUES(?,0,0)",
                (self.identity({key: row["equipment"] for key, row in seed["loadouts"].items()}),),
            )
        if not self.objectives:
            return self.publish()
        self.pools = self.candidate_pools()
        roles = self.search.request.roles
        count = max(1, len(self.objectives))
        combat_reserve = 25000 * count
        shared_reserve = 10000 * count
        anchor_budget = int(self.policy["anchor_expansion_limit"])
        anchor_before = self.nodes
        anchor_allowance = max(1, anchor_budget // (max(1, len(self.objectives)) * len(roles)))
        for dimension in range(1, len(self.objectives) + 1):
            for role in roles:
                self.equipment((role,), anchor_allowance, anchor=dimension)
        anchor_work = self.nodes - anchor_before
        diversity_end = self.limit - combat_reserve - shared_reserve
        equipment_budget = max(0, diversity_end - self.nodes)
        equipment_slots = len(roles) + int(len(roles) > 1)
        per_role = max(1, equipment_budget // (equipment_slots + int(len(roles) > 1)))
        individual = {role.id: self.equipment((role,), per_role) for role in roles}
        if len(roles) > 1:
            self.equipment(roles, per_role)
            self.combine(individual, max(0, diversity_end - self.nodes))
        combat_before = self.nodes
        self.phase_limit = min(self.limit, self.nodes + combat_reserve)
        pending = self.seen.execute(
            "SELECT identity FROM seen_assignments WHERE complete=0 ORDER BY identity"
        )
        for row in pending:
            if self.nodes >= self.phase_limit:
                break
            self.capture(json.loads(row[0]))
        combat_work = self.nodes - combat_before
        self.phase_limit = self.limit
        from tracker.gear.vector_refinement import refine

        self.report_refinement(0.0)
        refinement = refine(self, candidates, bool(self.policy["complete_assignment_limit"]))
        self.report_refinement(1.0)
        result = self.publish()
        result["diagnostics"] = {
            **result["diagnostics"],
            "anchor_explored_nodes": anchor_work,
            "combat_explored_nodes": combat_work,
            "refinement": refinement,
        }
        self.search.reporter.fraction(1.0)
        return result

    def publish(self) -> dict[str, Any]:
        groups = [
            {
                "swap_limit": cap,
                "baseline_dps": archive.baseline_dps(),
                "sampled": False,
                "points": FrontierPoints(archive, cap),
            }
            for cap, archive in self.archives.items()
        ]
        return {
            "groups": groups,
            "diagnostics": {
                **self.policy,
                "explored_nodes": self.nodes,
                "option_attempts": self.option_attempts,
                "complete_configuration_attempts": self.complete_attempts,
                "archive_admissions": self.accepted,
                "work_budget_exhausted": self.nodes >= self.limit,
                "archive_counts": {
                    str(cap): len(archive) for cap, archive in self.archives.items()
                },
            },
        }
