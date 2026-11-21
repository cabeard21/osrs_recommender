"""Bounded true-vector gear exploration with complete, disk-backed Pareto archives."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Mapping
from itertools import product
from typing import Any

from tracker.gear.compact_costs import aggregate_numeric_cost
from tracker.gear.evaluation import loadout_problems, planning_owned
from tracker.gear.models import EquipmentDefinition
from tracker.gear.objectives import annotate_solution, objective_policy, solution_objectives
from tracker.gear.vector_archive import ArchiveCandidate, VectorArchive
from tracker.gear.vector_options import OptionVariant, VectorOptions
from tracker.gear.vector_publish import FrontierPoints
from tracker.gear.vector_refinement import _safe_improvement
from tracker.gear.vector_retention import retain
from tracker.gear.vector_wilderness import supply_saving_lanes, trip_loss_lookup


class VectorSearch:
    """Search projections guide beams; only raw full vectors establish dominance."""

    def __init__(self, search: Any, thorough: bool = False) -> None:
        self.search = search
        self.objectives = search.request.objectives or ()
        self.ids = tuple(objective.id for objective in self.objectives)
        self.policy = objective_policy(self.objectives, thorough)
        self.options = VectorOptions(search)
        self.prayer_ammunition: tuple[EquipmentDefinition, ...] = ()
        if len(search.request.roles) == 1 and "prayer_bonus" in self.ids:
            self.prayer_ammunition = tuple(
                sorted(
                    (
                        item
                        for item in search.eligible.values()
                        if item.slot == "ammunition"
                        and item.bonuses.prayer > 0
                        and planning_owned(search.facts[item.id])["status"] == "owned"
                    ),
                    key=lambda item: (-item.bonuses.prayer, item.id),
                )
            )
        caps = [*range(search.request.max_swaps + 1), None]
        self.baselines: dict[int | None, dict[str, Any] | None] = dict.fromkeys(caps)
        self._baseline_rows: dict[int | None, ArchiveCandidate] = {}
        common = VectorArchive(self.ids) if len(search.request.roles) == 1 else None
        self.archives = {
            cap: common if common is not None else VectorArchive(self.ids) for cap in caps
        }
        if getattr(search, "native_context", None) is not None:
            for archive in dict.fromkeys(self.archives.values()):
                archive.enable_native_index()
        # These compact fields are available before expanding purchases, transitions,
        # role reports and running resource detail. Other projections use the full report.
        self._screen_base = (
            getattr(search, "native_context", None) is not None
            and self.options.cost_index is not None
            and all(obj.kind in {"gp_per_damage", "prayer_bonus"} for obj in self.objectives)
        )
        self._native_baselines = None
        if self._screen_base:
            from tracker.gear.native._frontier import CapBaselines

            self._native_baselines = CapBaselines(search.request.max_swaps)
        self._base_screened = self._unpriced_screened = self._base_skipped = self._base_reused = 0
        self.seen = self.archives[None].connection
        self.seen.execute(
            "CREATE TABLE seen_assignments(identity TEXT PRIMARY KEY,"
            "cursor INTEGER NOT NULL,complete INTEGER NOT NULL,base_order TEXT)"
        )
        self.nodes = 0
        self.option_attempts = 0
        self.accepted = 0
        self.complete_attempts = 0
        self.native_option_attempts = 0
        self.native_option_screened = 0
        self.native_option_reports = 0
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
        from tracker.gear.compact_solutions import CompactSolution
        from tracker.gear.variant_reporting import materialize

        caps = tuple(
            cap for cap in self.archives if cap is None or solution["maximum_actions"] <= cap
        )
        archives = tuple(dict.fromkeys(self.archives[cap] for cap in caps))
        if self._screen_base and isinstance(solution, CompactSolution):
            survivors = self._screen_compact(solution, archives)
            if survivors is None:
                return
            archives = survivors
        solution = materialize(solution if isinstance(solution, dict) else dict(solution))
        annotated = annotate_solution(solution, self.objectives, self.search.request.roles)
        if (
            self.options.risk_index is not None
            and annotated["objective_values"].get("wilderness_loss_gp") is None
        ):
            return
        candidate = ArchiveCandidate(annotated, self.ids)
        if self.options.cost_index is not None:
            for cap in caps:
                previous = self._baseline_rows.get(cap)
                if (
                    previous is None
                    or candidate.baseline_prefix < previous.baseline_prefix
                    or (
                        candidate.baseline_prefix == previous.baseline_prefix
                        and candidate.tie < previous.tie
                    )
                ):
                    self.baselines[cap] = annotated
                    self._baseline_rows[cap] = candidate
                    if self._native_baselines is not None:
                        self._native_baselines.update(
                            cap, annotated["score"], candidate.baseline_prefix
                        )
        cleaned = None
        for archive in archives:
            if not archive.add_candidate(candidate):
                continue
            self.accepted += 1
            if self.options.cost_index is not None:
                if cleaned is None:
                    row = self.clean_ammunition(annotated)
                    cleaned = candidate if row is annotated else ArchiveCandidate(row, self.ids)
                if cleaned is not candidate:
                    self.accepted += int(archive.add_candidate(cleaned))
            if self.prayer_ammunition:
                upgrade = self._prayer_ammunition_upgrade(annotated)
                if upgrade is not None:
                    self.accepted += int(archive.add(upgrade))

    def _screen_compact(
        self,
        solution: Mapping[str, Any],
        archives: tuple[VectorArchive, ...],
    ) -> tuple[VectorArchive, ...] | None:
        """Keep an equal numeric tie for the exact lexical report comparison."""
        from tracker.gear.native._frontier import admission_mask

        values = solution_objectives(solution, self.objectives, self.search.request.roles)
        compact = ArchiveCandidate({**solution, "objective_values": values}, self.ids)
        mask = 0
        if compact.vector is not None:
            indexes = tuple(archive.native_candidate_index for archive in archives)
            try:
                mask = admission_mask(indexes, compact.vector, compact.prefix)
            except ValueError:
                # The normal per-archive path handles numeric-range fallback.
                return archives
            if any(index is not None for index in indexes):
                self._base_screened += 1
        if not mask:
            assert self._native_baselines is not None
            may_win = self._native_baselines.may_win(
                solution["maximum_actions"], solution["score"], compact
            )
            if compact.vector is None:
                self._unpriced_screened += 1
            if not may_win:
                self._base_skipped += 1
                return None
        return tuple(archive for i, archive in enumerate(archives) if mask & (1 << i))

    def clean_ammunition(self, row: dict[str, Any]) -> dict[str, Any]:
        from tracker.gear.optimizer import _solution_key
        from tracker.gear.refinement import refine_ammunition
        from tracker.gear.variant_reporting import materialize
        from tracker.gear.wilderness_ammo import consumes_ammunition

        for role in self.search.request.roles:
            equipment = row["loadouts"][role.id]["equipment"]
            if role.style == "special" or "ammunition" not in equipment:
                continue
            if not consumes_ammunition(equipment, role.style, self.search.items):
                cleaned = refine_ammunition(
                    self.search,
                    row,
                    _solution_key,
                    {"evaluated_assignments": 0, "improved_finalists": 0},
                )
                if cleaned is not row:
                    cleaned = annotate_solution(
                        materialize(cleaned), self.objectives, self.search.request.roles
                    )
                    if cleaned["objective_values"] == row["objective_values"] and all(
                        candidate["combat_option"] == row["loadouts"][rid]["combat_option"]
                        and candidate["selected_prayer_ids"]
                        == row["loadouts"][rid]["selected_prayer_ids"]
                        for rid, candidate in cleaned["loadouts"].items()
                    ):
                        return cleaned
                break
        return row

    def _prayer_ammunition_upgrade(self, solution: dict[str, Any]) -> dict[str, Any] | None:
        """Check idle melee ammunition on admission, including rows outside the seed pool."""
        role = self.search.request.roles[0]
        loadout = solution["loadouts"][role.id]
        option = loadout["combat_option"]
        if (
            not option
            or option["attack_type"] not in ("stab", "slash", "crush")
            or "ammunition" in self.search.request.locks
            or "ammunition" in role.locks
        ):
            return None
        equipment = loadout["equipment"]
        current = self.search.items.get(equipment.get("ammunition"))
        current_prayer = current.bonuses.prayer if current is not None else 0
        prayers = tuple(loadout["selected_prayer_ids"])
        for item in self.prayer_ammunition:
            if item.bonuses.prayer <= current_prayer:
                break
            assignment = {role.id: {**equipment, "ammunition": item.id}}
            for variant in self.options.variants(assignment[role.id], role):
                attack = variant.option
                if (
                    attack is None
                    or any(getattr(attack, key) != value for key, value in option.items())
                    or tuple(variant.configured.active_prayer_ids) != prayers
                ):
                    continue
                candidate = self.options.solution(assignment, (variant,))
                if (
                    candidate is not None
                    and candidate["running_cost"] == solution["running_cost"]
                    and _safe_improvement(candidate, solution, self.ids)
                ):
                    return candidate
        return None

    def capture_base(self, assignment: Mapping[str, Mapping[str, int]]) -> None:
        """Archive the DPS configuration already scored; queue paid option exploration."""
        if any(role.id not in assignment for role in self.search.request.roles):
            return
        if self._screen_base and getattr(self.search, "compact_states", False):
            from tracker.gear.compact_states import AssignmentState

            state = AssignmentState.from_mapping(assignment)
            # The base winner is deterministic within this frozen branch. Compact
            # scoring preserves insertion order, and seeded overrides can differ
            # even for the same gear. Only memoize unseeded, identically ordered gear.
            seeded = any(
                (role, gear.identity) in self.search.performance_cache
                or (role, gear.identity) in self.search.option_cache
                for role, gear in state.roles
            )
            order = (
                None if seeded else json.dumps([(role, gear.order) for role, gear in state.roles])
            )
            queued = self.seen.execute(
                "INSERT INTO seen_assignments VALUES(?,0,0,?) ON CONFLICT(identity) "
                "DO UPDATE SET base_order=excluded.base_order "
                "WHERE excluded.base_order IS NULL OR base_order IS NOT excluded.base_order",
                (self.identity(state), order),
            )
            if not queued.rowcount:
                self._base_reused += 1
                return
            assignment = state
        elif self.objectives:
            self.seen.execute(
                "INSERT OR IGNORE INTO seen_assignments VALUES(?,0,0,NULL)",
                (self.identity(assignment),),
            )
        self.offer(self.search.solution(assignment, None))

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
        if any(
            loadout_problems(
                assignment[role.id], self.search.items, self.search.facts, self.search.request, role
            )
            for role in roles
        ):
            self._remember_assignment(identity, cursor, complete=True)
            return
        alternatives = tuple(self.options.variants(assignment[role.id], role) for role in roles)
        if any(not values for values in alternatives):
            self._remember_assignment(identity, cursor, complete=True)
            return
        # Physical legality, acquisition, inventory and transition feasibility do
        # not depend on the attack/prayer configuration chosen for this gear.
        first = tuple(values[0] for values in alternatives)
        feasibility = self.options.numeric_feasibility(assignment, first, physical_checked=True)
        if feasibility is None:
            self._remember_assignment(identity, cursor, complete=True)
            return
        applicable = tuple(
            dict.fromkeys(
                archive
                for cap, archive in self.archives.items()
                if cap is None or feasibility.maximum_actions <= cap
            )
        )

        risk_index = self.options.risk_index
        trip_loss = trip_loss_lookup(self.search, assignment) if risk_index is not None else None
        native = getattr(self.search, "native_context", None) is not None
        single_vector = (
            len(roles) == 1
            and roles[0].style != "special"
            and roles[0].weight == 1
            and self.options.cost_index is None
        )
        if (
            single_vector
            and len(applicable) == 1
            and applicable[0].native_candidate_index is not None
        ):
            position = self._scan_native_options(
                assignment, alternatives[0], applicable[0], cursor, charge, trip_loss, risk_index
            )
            if position == len(alternatives[0]):
                self._remember_assignment(identity, cursor, complete=True)
                return
            if charge and self.nodes >= self.phase_limit:
                self._remember_assignment(identity, position, complete=False)
                return
            cursor = position
        for position, selected in enumerate(product(*alternatives)):
            if position < cursor:
                continue
            if self.search.cancelled and self.search.cancelled():
                raise ValueError("optimization_cancelled")
            if charge and not self.tick():
                self._remember_assignment(identity, position, complete=False)
                return
            self.option_attempts += 1
            self.complete_attempts += 1
            if native:
                self.native_option_attempts += 1
            vector = selected[0].values if single_vector else self.weighted(selected, roles)
            if trip_loss is not None and risk_index is not None:
                loss = trip_loss(selected)
                if loss is None:
                    continue
                if vector is not None:
                    vector = (*vector[:risk_index], -loss, *vector[risk_index + 1 :])
            if vector is None:
                # A feasible unpriced option may still be a cap's highest-DPS baseline.
                score = self.weighted_values(selected, roles)[0]
                if all(
                    row is not None and row["score"] > score
                    for cap, row in self.baselines.items()
                    if cap is None or feasibility.maximum_actions <= cap
                ):
                    continue
            elif all(archive.strictly_dominated(vector) for archive in applicable):
                continue
            if native:
                self.native_option_reports += 1
            solution = self.options.solution(assignment, selected)
            if solution is not None:
                self.offer(solution)
        self._remember_assignment(identity, cursor, complete=True)

    def _scan_native_options(
        self,
        assignment: Mapping[str, Mapping[str, int]],
        variants: tuple[OptionVariant, ...],
        archive: VectorArchive,
        position: int,
        charge: bool,
        trip_loss: Any,
        risk_index: int | None,
    ) -> int:
        """Advance to each viable option in order, then recheck the updated archive."""
        while position < len(variants) and (index := archive.native_candidate_index) is not None:
            if self.search.cancelled and self.search.cancelled():
                raise ValueError("optimization_cancelled")
            stop = min(position + 128, len(variants))
            if charge:
                quota = min(self.phase_limit - self.nodes, 1024 - (self.nodes & 1023))
                if quota <= 0:
                    break
                stop = min(stop, position + quota)
            candidate = index.next_candidate(
                variants, position, stop, trip_loss, -1 if risk_index is None else risk_index
            )
            if candidate < 0:
                break
            end = min(candidate + 1, stop)
            consumed = end - position
            self.option_attempts += consumed
            self.complete_attempts += consumed
            self.native_option_attempts += consumed
            self.native_option_screened += consumed
            if charge:
                self.nodes += consumed
                if not self.nodes & 1023:
                    self.search.reporter.fraction(0.65 * self.nodes / self.limit)
            if candidate < stop:
                self.native_option_reports += 1
                solution = self.options.solution(assignment, (variants[candidate],))
                if solution is not None:
                    self.offer(solution)
            position = end
        return position

    def _remember_assignment(self, identity: str, cursor: int, *, complete: bool) -> None:
        self.seen.execute(
            "INSERT INTO seen_assignments VALUES(?,?,?,NULL) "
            "ON CONFLICT(identity) DO UPDATE SET cursor=excluded.cursor,complete=excluded.complete",
            (identity, cursor, complete),
        )

    def weighted(
        self, selected: tuple[OptionVariant, ...], roles: tuple[Any, ...]
    ) -> tuple[float, ...] | None:
        weighted = self.weighted_values(selected, roles)
        cost_index = self.options.cost_index
        if cost_index is None:
            return weighted
        cost = aggregate_numeric_cost(
            [
                (role.weight, option.cost, option.values[0])
                for role, option in zip(roles, selected, strict=True)
                if role.style != "special" and option.cost is not None
            ]
        ).gp_per_damage
        return (
            None if cost is None else (*weighted[:cost_index], -cost, *weighted[cost_index + 1 :])
        )

    @staticmethod
    def weighted_values(
        selected: tuple[OptionVariant, ...], roles: Iterable[Any]
    ) -> tuple[float, ...]:
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
        projection = tuple(
            sum(value[index] * role.weight for value, role in zip(values, roles, strict=True))
            / weight
            for index in range(len(self.objectives) + 1)
        )

        return self.risk_projection(
            projection, {item for gear in assignment.values() for item in gear.values()}
        )

    def risk_projection(
        self, projection: tuple[float, ...], carried: set[int]
    ) -> tuple[float, ...]:
        index = self.options.risk_index
        if index is None:
            return projection
        bound = self.search.wilderness.lower_bound(carried)
        return (*projection[:index], -bound, *projection[index + 1 :])

    def cost_lanes(
        self, slot: str, candidates: list[int], scaffolds: dict[str, list[dict[str, int]]]
    ) -> list[list[int]]:
        cost_index = self.options.cost_index
        if cost_index is None or slot not in {"weapon", "ammunition", "cape", "shield"}:
            return []
        lanes = []
        for role in self.search.request.roles:
            if role.style == "special":
                continue
            grades: dict[int, float] = {}
            for base in scaffolds[role.id]:
                if self.search.cancelled and self.search.cancelled():
                    raise ValueError("optimization_cancelled")
                choices = candidates
                if slot in {"weapon", "ammunition"}:
                    choices = [base[slot]] if slot in base else []
                for item in choices:
                    trial = {**base, slot: item}
                    if self.search.compatible(trial):
                        projection = self.options.envelope(trial, role)
                        if projection is not None:
                            grades[item] = max(grades.get(item, -1e100), projection[cost_index])
            lanes.append(sorted(grades, key=lambda item: (-grades[item], item)))
        return lanes

    def candidate_pools(self) -> dict[str, list[int | None]]:
        from tracker.gear.optimizer import SLOTS
        from tracker.gear.salve import contextual_candidates as salve_candidates
        from tracker.gear.search_scaffolds import contextual_candidates as scaffold_candidates

        fields = {
            "prayer_bonus": "prayer",
            "melee_strength_bonus": "melee_strength",
            "ranged_strength_bonus": "ranged_strength",
            "magic_damage_bonus": "magic_damage",
        }
        pools: dict[str, list[int | None]] = {}
        scaffolds = {
            role.id: self.search.baselines(role)
            for role in self.search.request.roles
            if self.options.cost_index is not None and role.style != "special"
        }
        for slot in SLOTS:
            candidates = [
                item_id for item_id, item in self.search.eligible.items() if item.slot == slot
            ]
            lanes = [
                [item for item in self.search.pools[slot] if item is not None],
                sorted(candidates, key=lambda item: (self.search.cost({item}), item)),
            ]
            if self.options.cost_index is not None:
                lanes.extend(self.cost_lanes(slot, candidates, scaffolds))
                # Rune supply and task-specific spell access can be invisible on bare gear.
                protected = [
                    item
                    for item in candidates
                    if self.search.items[item].tome_effect or item in {4170, 21255}
                ]
                lanes.extend([item] for item in protected)
            if self.search.wilderness is not None:
                lanes.append(sorted(candidates, key=self.search.budget_item_rank))
            if self.options.risk_index is not None:
                lanes.extend(supply_saving_lanes(self.search, slot, candidates))
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
                        lanes.append(
                            sorted(
                                candidates,
                                key=lambda item: (
                                    -grades[item],
                                    *self.search.acquisition_tie({item}),
                                    item,
                                ),
                            )
                        )
                if objective.kind in fields:
                    components = [fields[objective.kind]]
                if objective.kind == "accuracy":
                    components = ["stab", "slash", "crush", "ranged", "magic"]
                for field in components:

                    def component_rank(item: int, field: str = field) -> tuple[Any, ...]:
                        return (
                            -float(getattr(self.search.items[item].bonuses, field)),
                            *self.search.acquisition_tie({item}),
                            item,
                        )

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
            if slot == "neck":
                keep = list(
                    dict.fromkeys(
                        [*keep, *salve_candidates(self.search.request.roles, self.search.eligible)]
                    )
                )
            pools[slot] = list(
                dict.fromkeys([*keep, *scaffold_candidates(self.search, slot, candidates)])
            )
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
        from tracker.gear.search_scaffolds import attack_seeds

        states: list[dict[str, int]] = [{}, *attack_seeds(self.search, roles)]
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
                    lambda row: self.equipment_tie(row[0]),
                    BEAM_WIDTH,
                )
            else:
                retained = sorted(
                    expanded,
                    key=lambda row: (
                        -row[1][anchor],
                        tuple(-value for value in row[1]),
                        self.equipment_tie(row[0]),
                    ),
                )[:BEAM_WIDTH]
            states = [row[0] for row in retained]
            if not states:
                break
        return states

    def equipment_tie(self, equipment: Mapping[str, int]) -> tuple[Any, ...]:
        """Keep affordable physical forms during ties before complete cost validation."""
        ids = set(equipment.values())
        return (
            self.search.cost(ids),
            self.search.untradeable_acquisitions(ids),
            tuple(sorted(equipment.items())),
        )

    def _python_equipment(
        self,
        roles: tuple[Any, ...],
        states: list[dict[str, int]],
        choices: list[int | None],
        slot: str,
    ) -> list[tuple[dict[str, int], tuple[float, ...]]]:
        from tracker.gear.optimizer import SLOTS

        settled_slots = (
            SLOTS[: SLOTS.index(slot) + 1] if self.options.risk_index is not None else ()
        )
        expanded: list[tuple[dict[str, int], tuple[float, ...]]] = []
        for state, item in product(states, choices):
            if not self.tick():
                break
            candidate = {**state, **({slot: item} if item is not None else {})}
            if (
                not self.search.compatible(candidate)
                or (slot == "ammunition" and not self.search.may_equip_ammunition(candidate, roles))
                or any(item_id not in self.search.eligible for item_id in candidate.values())
                or not self.search.slot_budget(
                    (candidate,),
                    set(candidate.values()),
                    slot,
                    complete=slot == SLOTS[-1] and len(roles) == len(self.search.request.roles),
                )
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
            if self.options.risk_index is not None:
                projection = self.risk_projection(
                    projection, {candidate[s] for s in settled_slots if s in candidate}
                )
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
        from tracker.gear.native import NativeSearchUnavailable, required
        from tracker.gear.native._stages import StageContext

        context = getattr(self, "_projection_context", None)
        if context is None:
            context = StageContext(native, self.search)
            self._projection_context = context
        if not hasattr(context, "begin_projection"):
            if required():
                raise NativeSearchUnavailable("Native vector expansion is unavailable")
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
                raise NativeSearchUnavailable("Native vector expansion made no progress")
            self.nodes += consumed
            expanded.extend(rows)
            if self.search.cancelled and self.search.cancelled():
                raise ValueError("optimization_cancelled")
            if not self.nodes & 1023:
                self.search.reporter.fraction(0.65 * self.nodes / self.limit)
        if expansion.consumed:
            from tracker.gear.native import record

            record(
                "vector_projection",
                attempts=expansion.consumed,
                cost=self.options.cost_evaluator is not None,
                slot=slot,
                roles=tuple(role.style for role in roles),
            )
        return expanded

    def combine(self, individual: Mapping[str, list[dict[str, int]]], allowance: int) -> None:
        from tracker.gear.optimizer import BEAM_WIDTH, _action_lower_bound

        roles = self.search.request.roles
        caps = [*range(self.search.request.max_swaps + 1), None]
        per_cap = max(1, allowance // len(caps))
        for cap in caps:
            self.phase_limit = min(self.limit, self.nodes + per_cap)
            states: list[dict[str, dict[str, int]]] = [{}]
            for role_index, role in enumerate(roles):
                complete = role_index == len(roles) - 1
                expanded: list[tuple[dict[str, dict[str, int]], tuple[float, ...]]] = []
                for state, equipment in product(states, individual[role.id]):
                    if not self.tick():
                        break
                    assignment = {**state, role.id: equipment}
                    carried = {item for row in assignment.values() for item in row.values()}
                    if not self.search.within_budget(carried, complete=complete):
                        continue
                    if complete and not self.search.complete_ammunition_allowed(assignment):
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
                        expanded,
                        lambda row: row[1],
                        lambda row: (
                            *self.search.acquisition_tie(
                                {item for gear in row[0].values() for item in gear.values()}
                            ),
                            self.identity(row[0]),
                        ),
                        BEAM_WIDTH,
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
                "INSERT OR IGNORE INTO seen_assignments VALUES(?,0,0,NULL)",
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
        if (
            self._base_screened
            or self._unpriced_screened
            or self._base_skipped
            or self._base_reused
        ):
            from tracker.gear.native import record

            record(
                "completed_candidate_admission",
                screened=self._base_screened,
                unpriced_screened=self._unpriced_screened,
                skipped_reports=self._base_skipped,
                repeated_assignments=self._base_reused,
            )
        if self.native_option_attempts:
            from tracker.gear.native import record

            record(
                "vector_option_batch",
                roles=tuple(role.style for role in self.search.request.roles),
                attempts=self.native_option_attempts,
                screened=self.native_option_screened,
                report_evaluations=self.native_option_reports,
            )
        if self.options.cost_index is not None:
            from tracker.gear.optimizer import _objective_winner_key

            chosen = {}
            for cap, archive in self.archives.items():
                incumbent = self.baselines[cap]
                if incumbent is None:
                    continue
                if archive not in chosen:
                    candidates = archive.iter_solutions(minimum_dps=incumbent["score"])
                    chosen[archive] = min(candidates, key=_objective_winner_key, default=None)
                self.baselines[cap] = chosen[archive] or self.clean_ammunition(incumbent)
        groups = [
            {
                "swap_limit": cap,
                "baseline_dps": (self.baselines[cap] or {}).get("score", archive.baseline_dps()),
                **(
                    {"baseline_solution": self.baselines[cap]}
                    if self.options.cost_index is not None
                    else {}
                ),
                "sampled": False,
                "points": FrontierPoints(
                    archive, cap, baseline_dps=(self.baselines[cap] or {}).get("score")
                ),
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
