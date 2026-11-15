"""Bounded deterministic equipment search over frozen account/price inputs.

Search quality is always reported as best-found: candidate and beam truncation
cannot establish global optimality or prove that a request is infeasible.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from itertools import product
from time import perf_counter
from types import MappingProxyType
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.content.schema import ItemSlot
from tracker.estimation.prices import PriceRecord
from tracker.gear.combat import (
    ELEMENTAL_SPELLS,
    MODEL_VERSION,
    CombatScore,
    evaluate_prepared_loadout,
    evaluate_prepared_score,
)
from tracker.gear.combat_options import CombatOption, ancient_spell_problem, eligible_combat_options
from tracker.gear.defensive_rolls import raw_player_defence_rolls
from tracker.gear.elemental_amulets import MODEL_VERSION as ELEMENTAL_AMULET_MODEL_VERSION
from tracker.gear.elemental_amulets import applied_spell_bonus
from tracker.gear.evaluation import (
    equipment_problems,
    item_problems,
    loadout_problems,
    purchase_cost,
    purchases,
    resolve_bolt_context,
    resolve_tome_context,
    unowned_untradeables,
    validate_request_context,
)
from tracker.gear.facts import equipment_fact, hypothetical_snapshot
from tracker.gear.fixed_reporting import active as fixed_reporting_active
from tracker.gear.halberd_charging import CrystalChargingPolicy
from tracker.gear.hopper import MODEL_VERSION as HOPPER_MODEL_VERSION
from tracker.gear.lazy_reporting import active as lazy_reporting_active
from tracker.gear.leafy import MODEL_VERSION as LEAFY_MODEL_VERSION
from tracker.gear.local_refinement import refine_completed
from tracker.gear.models import (
    CombatPerformance,
    CombatTarget,
    EquipmentDefinition,
    TargetSelection,
)
from tracker.gear.npcs import discipline_problem
from tracker.gear.potions import PotionPolicy, boosted_levels, potion_summary
from tracker.gear.powered import review as powered_review
from tracker.gear.prayers import (
    CATALOG_REVISION as PRAYER_CATALOG_REVISION,
)
from tracker.gear.prayers import (
    MODEL_VERSION as PRAYER_MODEL_VERSION,
)
from tracker.gear.prayers import (
    PrayerPolicy,
)
from tracker.gear.prayers import (
    effects as prayer_effects,
)
from tracker.gear.prayers import (
    setups as prayer_setups,
)
from tracker.gear.priorities import SecondaryPriority, secondary_value
from tracker.gear.progress import NULL_REPORTER, StageReporter
from tracker.gear.refinement import refine_ammunition, refine_magic_staves, refine_shared_slots
from tracker.gear.running_frontier import needs_running_cost_frontier
from tracker.gear.scoring import EquipmentScorer, PreparedEquipment
from tracker.gear.slayer import MODEL_VERSION as SLAYER_MODEL_VERSION
from tracker.gear.support import SupportPolicy, project_catalog, support_context
from tracker.gear.targeted_retention import refine_omitted_heads
from tracker.gear.tomes import MODEL_VERSION as TOME_MODEL_VERSION
from tracker.gear.tomes import applied_tome
from tracker.gear.tomes import review as tome_review
from tracker.gear.transitions import inventory_slots, plan_transition

SLOTS: tuple[ItemSlot, ...] = (
    "weapon",
    "shield",
    "ammunition",
    "head",
    "cape",
    "neck",
    "body",
    "legs",
    "hands",
    "feet",
    "ring",
)
# Temporary larger search for investigating material-tier selection.
# Previous limits: beam 128, candidates 12, expansions 1,000,000.
BEAM_WIDTH = 256
CANDIDATES_PER_SLOT = 24
MAX_EXPANSIONS = 5_000_000
ItemId = Annotated[int, Field(strict=True, gt=0)]


class CombatOptionFilters(BaseModel):
    """Explicit user allowlists; an empty list intentionally permits no attacks."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    attack_types: tuple[
        Literal["stab", "slash", "crush", "light", "standard", "heavy", "magic"], ...
    ] = Field(max_length=7)
    stances: tuple[
        Literal["accurate", "aggressive", "controlled", "defensive", "rapid", "longrange"], ...
    ] = Field(max_length=6)
    spells: tuple[Annotated[str, Field(max_length=40, pattern=r"^[a-z0-9_:]+$")], ...] = Field(
        max_length=100
    )


class RoleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    safe_spotting: bool = Field(default=False, strict=True)
    fight_duration_seconds: int = Field(default=60, ge=1, le=3600, strict=True)
    on_slayer_task: bool = Field(default=False, strict=True)
    fire_tome_pages: Literal["burnt", "searing"] = Field(default="burnt", exclude=True)
    bolt_diary_boost: bool = Field(default=False, exclude=True)
    bolt_diary_known: bool = Field(default=False, exclude=True)
    prayers: PrayerPolicy = PrayerPolicy()
    active_prayer_ids: tuple[str, ...] = Field(default=(), exclude=True)
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    style: Literal["stab", "slash", "crush", "ranged", "magic", "special"]
    stance: Literal["accurate", "aggressive", "controlled", "defensive", "rapid", "longrange"] = (
        "accurate"
    )
    spell: str = Field(default="fire_strike", max_length=40)
    combat_options: CombatOptionFilters | None = None
    allowed_disciplines: tuple[Literal["melee", "ranged", "magic"], ...] | None = Field(
        default=None, min_length=1, max_length=3
    )
    powered_attack: str | None = None
    weight: float = Field(default=1, ge=0, le=1_000_000, allow_inf_nan=False)
    target_selection: TargetSelection | None = None
    target: CombatTarget | None = None
    locks: Mapping[ItemSlot, ItemId | None] = Field(default_factory=dict)
    parent_role: str | None = None

    @model_validator(mode="after")
    def freeze_locks(self) -> RoleConfig:
        if self.safe_spotting and self.style == "special":
            raise ValueError("Safe spotting requires a scored combat configuration")
        if self.fire_tome_pages != "burnt":
            raise ValueError("fire_tome_pages is scenario-wide, not a role request field")
        if self.bolt_diary_boost or self.bolt_diary_known:
            raise ValueError("Bolt diary context is resolved internally, not a request field")
        if self.active_prayer_ids:
            raise ValueError("active_prayer_ids is resolved internally, not a request field")
        if self.allowed_disciplines is not None:
            if len(set(self.allowed_disciplines)) != len(self.allowed_disciplines):
                raise ValueError("allowed_disciplines must be unique")
            if self.style == "special" or self.combat_options is None:
                raise ValueError("Auto requires an ordinary role and explicit combat_options")
        if self.powered_attack is not None:
            raise ValueError("powered_attack is selected by the optimizer, not a request field")
        object.__setattr__(self, "locks", MappingProxyType(dict(self.locks)))
        return self

    @field_serializer("locks")
    def serialize_locks(self, value: Mapping[str, int | None]) -> dict[str, int | None]:
        return dict(value)


class OptimizationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    crystal_halberd_charging: CrystalChargingPolicy = CrystalChargingPolicy()
    potions: PotionPolicy = PotionPolicy()
    fire_tome_pages: Literal["burnt", "searing"] = "burnt"
    roles: tuple[RoleConfig, ...] = Field(min_length=1, max_length=4)
    mode: Literal["owned", "usable", "future"] = "usable"
    include_untradeables: bool = Field(default=False, strict=True)
    support_policy: SupportPolicy = "verified_only"
    budget_gp: int = Field(default=0, ge=0, strict=True)
    secondary_priority: SecondaryPriority = "default"
    max_dps_loss_pct: float = Field(default=10, strict=True, ge=0, le=100, allow_inf_nan=False)
    locks: Mapping[ItemSlot, ItemId | None] = Field(default_factory=dict)
    base_role: str | None = None
    transitions: tuple[tuple[str, str], ...] = ()
    ordered_roles: tuple[str, ...] = ()
    loop: bool = False
    reserved_supply_slots: int = Field(default=12, ge=0, le=28, strict=True)
    max_swaps: int = Field(default=8, ge=0, le=12, strict=True)
    skill_overrides: Mapping[str, int] = Field(default_factory=dict)
    quest_overrides: Mapping[str, str] = Field(default_factory=dict)
    assumed_item_ids: tuple[ItemId, ...] = ()
    excluded_item_ids: tuple[ItemId, ...] = Field(default=(), max_length=500)
    expected_snapshot_id: str | None = None

    @model_validator(mode="after")
    def validate_context(self) -> OptimizationRequest:
        ids = {r.id for r in self.roles}
        if len(ids) != len(self.roles):
            raise ValueError("role IDs must be unique")
        scored = {r.id for r in self.roles if r.style != "special"}
        if not any(r.style != "special" and r.weight > 0 for r in self.roles):
            raise ValueError("at least one scored role must have positive active time")
        if (
            len(self.transitions) > 16
            or len(self.skill_overrides) > 23
            or len(self.quest_overrides) > 1000
            or len(self.assumed_item_ids) > 500
        ):
            raise ValueError("request exceeds optimizer input limits")
        if any(isinstance(i, bool) or i <= 0 for i in self.assumed_item_ids):
            raise ValueError("assumed item IDs must be positive integers")
        if self.base_role is not None and self.base_role not in ids:
            raise ValueError("base_role must reference a configured role")
        if any(a not in ids or b not in ids or a == b for a, b in self.transitions):
            raise ValueError("transitions must reference different configured roles")
        if any(key not in ids for key in self.ordered_roles):
            raise ValueError("ordered_roles must reference configured roles")
        if len(self.ordered_roles) > 100:
            raise ValueError("at most 100 ordered phases")
        if self.transitions and self.ordered_roles:
            raise ValueError("choose explicit transitions or ordered_roles")
        for role in self.roles:
            if role.parent_role is not None and (
                role.parent_role not in ids or role.parent_role == role.id
            ):
                raise ValueError("parent_role must reference another role")
            if role.style == "special" and (
                role.parent_role is None or role.locks.get("weapon") is None
            ):
                raise ValueError("special role requires parent_role and a weapon lock")
            if role.style == "special" and role.parent_role not in scored:
                raise ValueError("special role parent must be a scored combat role")
            if any(k in self.locks and self.locks[k] != v for k, v in role.locks.items()):
                raise ValueError("conflicting global and role locks")
            if any(v is not None and v <= 0 for v in role.locks.values()):
                raise ValueError("locked item IDs must be positive")
            if any(v is not None and v in self.excluded_item_ids for v in role.locks.values()):
                raise ValueError("role lock conflicts with excluded_item_ids")
        if any(v is not None and v <= 0 for v in self.locks.values()):
            raise ValueError("locked item IDs must be positive")
        if any(v is not None and v in self.excluded_item_ids for v in self.locks.values()):
            raise ValueError("global lock conflicts with excluded_item_ids")
        if any(not 1 <= v <= 99 for v in self.skill_overrides.values()):
            raise ValueError("future skill levels must be 1 to 99")
        if self.mode != "future" and (
            self.skill_overrides or self.quest_overrides or self.assumed_item_ids
        ):
            raise ValueError("hypothetical assumptions require future mode")
        if any(
            v not in ("complete", "in_progress", "not_started", "unknown")
            for v in self.quest_overrides.values()
        ):
            raise ValueError("invalid quest status assumption")
        for field in ("locks", "skill_overrides", "quest_overrides"):
            object.__setattr__(self, field, MappingProxyType(dict(getattr(self, field))))
        return self

    def prepared_weapon_locks(self) -> OptimizationRequest:
        """A locked uncharged edition requests its disclosed usable preparation.

        Normalize only explicitly selected attacks for that locked edition. Empty
        or unrelated allowlists stay unchanged, and both physical exclusions win.
        """
        execution = self.model_copy()
        conversions: dict[int, int] = {}

        def prepared(locks: Mapping[ItemSlot, int | None]) -> dict[ItemSlot, int | None]:
            result = dict(locks)
            preparers: tuple[tuple[ItemSlot, Callable[[int], Any]], ...] = (
                ("weapon", powered_review),
                ("shield", tome_review),
            )
            for slot, review_form in preparers:
                source = locks.get(slot)
                if source is None:
                    continue
                form = review_form(source)
                if form is None or source != form.uncharged_id or source == form.charged_id:
                    continue
                if source in self.excluded_item_ids or form.charged_id in self.excluded_item_ids:
                    raise ValueError("prepared equipment lock conflicts with excluded_item_ids")
                conversions[source] = form.charged_id
                result[slot] = form.charged_id
            return result

        global_locks = prepared(self.locks)
        roles = []
        for role in self.roles:
            source = role.locks.get("weapon", self.locks.get("weapon"))
            locks = prepared(role.locks)
            options = role.combat_options
            staff = powered_review(source) if source is not None else None
            if options is not None and staff is not None and source == staff.uncharged_id:
                spells = tuple(
                    dict.fromkeys(
                        f"powered:{staff.charged_id}" if s == f"powered:{source}" else s
                        for s in options.spells
                    )
                )
                options = options.model_copy(update={"spells": spells})
            roles.append(
                role.model_copy(
                    update={
                        "locks": MappingProxyType(locks),
                        "combat_options": options,
                        "fire_tome_pages": self.fire_tome_pages,
                    }
                )
            )
        object.__setattr__(execution, "locks", MappingProxyType(global_locks))
        object.__setattr__(execution, "roles", tuple(roles))
        object.__setattr__(
            execution,
            "assumed_item_ids",
            tuple(
                dict.fromkeys(
                    conversions.get(i, form.charged_id if (form := tome_review(i)) else i)
                    for i in self.assumed_item_ids
                )
            ),
        )
        return execution

    @field_serializer("locks", "skill_overrides", "quest_overrides")
    def serialize_mappings(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return dict(value)


def required_transitions(request: OptimizationRequest) -> tuple[tuple[str, str], ...]:
    if request.transitions:
        edges = list(request.transitions)
    elif request.ordered_roles:
        edges = list(zip(request.ordered_roles, request.ordered_roles[1:], strict=False))
        if request.loop and len(request.ordered_roles) > 1:
            edges.append((request.ordered_roles[-1], request.ordered_roles[0]))
    else:
        base = request.base_role or request.roles[0].id
        edges = [
            (a, b)
            for role in request.roles
            if role.id != base and role.style != "special"
            for a, b in ((base, role.id), (role.id, base))
        ]
    for role in request.roles:
        if role.style == "special" and role.parent_role and role.id not in request.ordered_roles:
            edges.extend(((role.parent_role, role.id), (role.id, role.parent_role)))
    return tuple(dict.fromkeys((a, b) for a, b in edges if a != b))


class _Winner(NamedTuple):
    score: CombatScore
    option: CombatOption
    role: RoleConfig


def _equipment_identity(equipment: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    from tracker.gear.compact_states import EquipmentState

    return (
        equipment.identity
        if isinstance(equipment, EquipmentState)
        else tuple(sorted(equipment.items()))
    )


def _equipment_ids(equipment: Mapping[str, int]) -> Any:
    from tracker.gear.compact_states import EquipmentState

    return equipment.ordered_ids if isinstance(equipment, EquipmentState) else equipment.values()


def _equipment_state(equipment: Any) -> Any:
    from tracker.gear.compact_states import EquipmentState
    from tracker.gear.execution_profile import compact_states_active

    return EquipmentState.from_mapping(equipment) if compact_states_active() else equipment


def _assignment_state(loadouts: Any) -> Any:
    from tracker.gear.compact_states import AssignmentState
    from tracker.gear.execution_profile import compact_states_active

    return AssignmentState.from_mapping(loadouts) if compact_states_active() else loadouts


class _Search:
    native_cost_objective: bool = False
    running_prices: Mapping[int, PriceRecord]
    running_at: datetime

    def __init__(
        self,
        snapshot: AccountSnapshot,
        request: OptimizationRequest,
        items: Mapping[int, EquipmentDefinition],
        facts: Mapping[int, dict[str, Any]],
        cancelled: Callable[[], bool] | None,
        prepared_eligible: Mapping[int, EquipmentDefinition] | None = None,
        *,
        reporter: StageReporter = NULL_REPORTER,
    ) -> None:
        # Telemetry only; shared by frontier copies so their work is reported too.
        self.reporter = reporter
        request = request.model_copy(
            update={
                "roles": tuple(
                    resolve_tome_context(
                        resolve_bolt_context(role, snapshot), request.fire_tome_pages
                    )
                    for role in request.roles
                )
            }
        )
        self.snapshot, self.request, self.items, self.facts = snapshot, request, items, facts
        from tracker.gear.execution_profile import factored_evaluation_active

        self.factored_evaluation = factored_evaluation_active()
        from tracker.gear.execution_profile import compact_states_active

        self.compact_states = compact_states_active()

        if self.compact_states:

            @lru_cache(maxsize=8192)
            def assignment_json(identity: tuple[Any, ...]) -> str:
                return json.dumps(
                    {role: dict(equipment) for role, equipment in identity}, sort_keys=True
                )

            from tracker.gear.compact_acquisition import AcquisitionFacts

            acquisition_facts = AcquisitionFacts.from_facts(facts, request)

            @lru_cache(maxsize=8192)
            def acquisition(ids: frozenset[int]) -> tuple[int, int]:
                return acquisition_facts.totals(ids)

            self._assignment_json = assignment_json
            self._acquisition = acquisition
        self.compact_multi = len(request.roles) > 1 and self.factored_evaluation
        self.levels: Mapping[str, int] = {k: v.level for k, v in snapshot.skills.items()}
        if request.potions.mode == "fixed":
            base_magic = self.levels.get("magic", 0)
            self.levels = boosted_levels(self.levels, request.potions.selected_ids)
            if self.levels.get("magic", 0) != base_magic:
                self.levels = {**self.levels, "_base_magic": base_magic}
        from tracker.gear.prepared_combat import freeze_levels

        self.levels = freeze_levels(self.levels)
        self.cancelled = cancelled
        self.nodes = 0
        self.truncated = False
        self.complete_frontiers = False
        self.edges = required_transitions(request)
        self.performance_cache: MutableMapping[
            tuple[str, tuple[tuple[str, int], ...]], dict[str, Any]
        ] = {}
        self.option_cache: MutableMapping[
            tuple[str, tuple[tuple[str, int], ...]], dict[str, Any] | None
        ] = {}
        self.compact_cache: dict[tuple[Any, ...], _Winner | CombatScore | None] = {}
        self.scorer = EquipmentScorer(items)
        self.configured_option_cache: dict[
            tuple[str, int | None], tuple[tuple[RoleConfig, CombatOption], ...]
        ] = {}
        self.scoring_option_cache: dict[
            tuple[Any, ...], tuple[tuple[RoleConfig, CombatOption], ...]
        ] = {}
        self.prayer_setup_cache: dict[str, tuple[tuple[str, ...], ...]] = {}
        self.prayer_option_cache: dict[tuple[str, str], tuple[tuple[str, ...], ...]] = {}

        if self.compact_states:
            from tracker.gear.compact_transitions import (
                SLOT_SET,
                TransitionProblem,
                prepare_transition,
                solve_transition,
            )

            @lru_cache(maxsize=1024)
            def reduced_transition(problem: TransitionProblem) -> dict[str, Any] | None:
                return solve_transition(problem, items)

            self._transition_reduced = reduced_transition

        compact_transitions = self.compact_states

        # Catalog definitions are fixed for this search; bound retained plans per
        # request and include inventory context as well as directional equipment.
        @lru_cache(maxsize=8192)
        def transition(
            source: tuple[tuple[str, int], ...],
            destination: tuple[tuple[str, int], ...],
            carried: frozenset[int],
            capacity: int,
        ) -> dict[str, Any] | None:
            if compact_transitions:
                source_mapping, destination_mapping = dict(source), dict(destination)
                if (
                    source_mapping.keys() <= SLOT_SET
                    and destination_mapping.keys() <= SLOT_SET
                    and all(type(item) is int for item in source_mapping.values())
                    and all(type(item) is int for item in destination_mapping.values())
                    and all(type(item) is int for item in carried)
                ):
                    return reduced_transition(
                        prepare_transition(
                            source_mapping, destination_mapping, carried=carried, capacity=capacity
                        )
                    )
            return plan_transition(
                dict(source), dict(destination), items, carried=carried, capacity=capacity
            )

        if compact_transitions:
            from weakref import ref

            outer_reference = ref(transition)

            def clear_transitions() -> None:
                outer = outer_reference()
                if outer is not None:
                    type(outer).cache_clear(outer)
                reduced_transition.cache_clear()

            transition.cache_clear = clear_transitions  # type: ignore[method-assign]
        self._transition = transition
        eligible = (
            prepared_eligible
            if prepared_eligible is not None
            else {i: item for i, item in items.items() if self.allowed(i)}
        )
        # Purchases are distinct, nonnegative costs. An item costing more than
        # the entire budget cannot appear in any feasible shared loadout. Prune
        # before building attack scaffolds and scoring expensive marginals;
        # keep the full catalog/facts for request validation and diagnostics.
        self.eligible = {
            i: item for i, item in eligible.items() if self.cost({i}) <= request.budget_gp
        }
        self.marginals: dict[tuple[str, int], float] = {}
        self.secondary_marginals: dict[tuple[str, int], float] = {}
        from tracker.gear.native import create_context

        self.native_context = create_context(self)
        self.native_limit = MAX_EXPANSIONS
        self.pools = self.candidate_pools()

    def assignment_tie(self, loadouts: Any) -> Any:
        if self.compact_states:
            from tracker.gear.compact_ranking import AssignmentTie

            return AssignmentTie(_assignment_state(loadouts))
        return json.dumps(loadouts, sort_keys=True)

    def assignment_json(self, loadouts: Any) -> str:
        if self.compact_states:
            return self._assignment_json(_assignment_state(loadouts).identity)
        return json.dumps(loadouts, sort_keys=True)

    def retain[Row](
        self, rows: list[Row], rank: Callable[[Row], tuple[Any, ...]], limit: int
    ) -> list[Row]:
        if not getattr(self, "frontier_search", False):
            return sorted(rows, key=rank)[:limit]
        from tracker.gear.frontier import diverse

        if getattr(self, "metric_first", False):

            def metric_rank(row: Row) -> tuple[Any, ...]:
                key = rank(row)
                return (key[1], key[0], *key[2:])

            # Preserve both extremes even in this lane; complementary partial
            # loadouts can temporarily have an equal weakest-side metric.
            return diverse(rows, metric_rank, limit)[:limit]
        return diverse(rows, rank, limit)

    def tick(self) -> bool:
        if self.cancelled and self.cancelled():
            raise ValueError("optimization_cancelled")
        if self.nodes >= MAX_EXPANSIONS:
            return False
        self.nodes += 1
        return True

    def allowed(self, item_id: int) -> bool:
        return not item_problems(item_id, self.facts[item_id], self.request)

    def cost(self, ids: set[int] | frozenset[int]) -> int:
        if self.compact_states:
            return self._acquisition(frozenset(ids))[0]
        return purchase_cost(ids if isinstance(ids, set) else set(ids), self.facts, self.request)

    def untradeable_acquisitions(self, ids: set[int] | frozenset[int]) -> int:
        """Break otherwise equal choices by acquisitions, without pricing effort."""
        if self.compact_states:
            return self._acquisition(frozenset(ids))[1]
        return len(
            unowned_untradeables(
                ids if isinstance(ids, set) else set(ids), self.facts, self.request
            )
        )

    def acquisition_tie(self, ids: set[int]) -> tuple[int, int]:
        """Preserve historical candidate ordering when the option is disabled."""
        return (
            (self.cost(ids), self.untradeable_acquisitions(ids))
            if self.request.include_untradeables
            else (0, 0)
        )

    def prayer_options(self, role: RoleConfig, style: str) -> tuple[tuple[str, ...], ...]:
        """Reuse legal setups and collapse only identical reported combat effects.

        Both defence modifiers remain in the signature even for DPS-only search:
        all five defence rolls are reported, and frontier lanes reuse these options.
        Fixed selections retain the user's setup, including irrelevant prayers.
        """
        if role.id not in self.prayer_setup_cache:
            self.prayer_setup_cache[role.id] = prayer_setups(
                role.prayers,
                self.snapshot,
                {key: value.level for key, value in self.snapshot.skills.items()},
            )
        setups = self.prayer_setup_cache[role.id]
        if role.prayers.mode != "optimize":
            return setups
        key = (role.id, style)
        if key not in self.prayer_option_cache:
            representatives: dict[tuple[int, ...], tuple[str, ...]] = {}
            frontier_representatives: dict[tuple[int, ...], tuple[str, ...]] = {}
            for ids in setups:
                modifiers = prayer_effects(ids)
                offensive = (
                    (modifiers.magic_accuracy, modifiers.magic_damage)
                    if style == "magic"
                    else (modifiers.ranged_accuracy, modifiers.ranged_strength)
                    if style == "ranged"
                    else (modifiers.attack, modifiers.strength)
                )
                signature = (*offensive, modifiers.defence, modifiers.magic_defence)
                previous = representatives.get(signature)
                if previous is None or (-len(ids), tuple(reversed(ids))) > (
                    -len(previous),
                    tuple(reversed(previous)),
                ):
                    representatives[signature] = ids
                frontier_previous = frontier_representatives.get(signature)
                if frontier_previous is None or json.dumps(list(ids)) < json.dumps(
                    list(frontier_previous)
                ):
                    frontier_representatives[signature] = ids
            # Frontier archives use serialized loadout identity after objective ties,
            # unlike performance()'s fewer-prayers preference. Keep each existing
            # tie winner so grouping cannot change either published setup or ID.
            retained = set(representatives.values()) | set(frontier_representatives.values())
            self.prayer_option_cache[key] = tuple(ids for ids in setups if ids in retained)
        return self.prayer_option_cache[key]

    def configured_options(
        self, role: RoleConfig, weapon: EquipmentDefinition | None
    ) -> tuple[tuple[RoleConfig, CombatOption], ...]:
        """Account, role filters and catalog stay fixed for this search."""
        if discipline_problem(role):
            return ()
        key = (role.id, weapon.id if weapon else None)
        if key not in self.configured_option_cache:
            allowed = role.combat_options
            configured = []
            if allowed is not None:
                discipline = "melee" if role.style in {"stab", "slash", "crush"} else role.style
                for option in eligible_combat_options(
                    weapon, self.snapshot, discipline=discipline, levels=self.levels
                ):
                    spell_id = option.spell or (
                        f"powered:{weapon.id}" if option.powered_attack and weapon else None
                    )
                    if (
                        not option.available
                        or option.attack_type not in allowed.attack_types
                        or option.stance not in allowed.stances
                        or (spell_id is not None and spell_id not in allowed.spells)
                    ):
                        continue
                    selected = role.model_copy(
                        update={
                            "style": option.style,
                            "stance": option.stance,
                            "spell": option.spell or role.spell,
                            "powered_attack": option.powered_attack,
                        }
                    )
                    from tracker.gear.attack_reach import safe_spotting_problem

                    if safe_spotting_problem(weapon, selected) is None:
                        configured.append((selected, option))
            elif role.prayers.mode != "disabled":
                problem = (
                    ancient_spell_problem(
                        weapon, self.snapshot, role.spell, role.stance, self.levels
                    )
                    if role.style == "magic" and role.powered_attack is None
                    else None
                )
                if problem is None:
                    configured.append(
                        (
                            role,
                            CombatOption(
                                attack_type=role.style,
                                stance=role.stance,
                                spell=role.spell if role.style == "magic" else None,
                                powered_attack=role.powered_attack,
                            ),
                        )
                    )
            self.configured_option_cache[key] = tuple(
                (selected.model_copy(update={"active_prayer_ids": ids}), option)
                for selected, option in configured
                for ids in self.prayer_options(role, selected.style)
            )
        return self.configured_option_cache[key]

    def scoring_prayer_key(self, configured: RoleConfig) -> tuple[int, ...]:
        """Keep only prayer modifiers participating in this lane's option rank.

        DPS-first option ranking does not compare defence rolls. The metric-first
        lane additionally compares its requested roll; both still materialize the
        selected setup's complete performance, including every reported defence.
        """
        modifiers = prayer_effects(configured.active_prayer_ids)
        offensive = (
            (modifiers.magic_accuracy, modifiers.magic_damage)
            if configured.style == "magic"
            else (modifiers.ranged_accuracy, modifiers.ranged_strength)
            if configured.style == "ranged"
            else (modifiers.attack, modifiers.strength)
        )
        priority = self.request.secondary_priority
        if not getattr(self, "metric_first", False) or not priority.endswith("_defence_roll"):
            return offensive
        defensive = (
            (modifiers.defence, modifiers.magic_defence)
            if priority
            in {"balanced_defence_roll", "magic_ranged_defence_roll", "magic_defence_roll"}
            else (modifiers.defence,)
        )
        return (*offensive, *defensive)

    def scoring_options(
        self,
        role: RoleConfig,
        weapon: EquipmentDefinition | None,
        neck: EquipmentDefinition | None = None,
        shield: EquipmentDefinition | None = None,
    ) -> tuple[tuple[RoleConfig, CombatOption], ...]:
        """Score rank-equivalent attacks once, retaining the existing tie winner.

        The ordinary model scales every element in a tier to the same base hit.
        Weakness matches and amulet base-hit increments remain separate.
        Full configured options remain available
        to the resource-cost and combat-option frontier searches.
        """
        key = (
            role.id,
            weapon.id if weapon else None,
            shield.id if shield else None,
            role.fire_tome_pages,
            role.on_slayer_task,
            getattr(self, "metric_first", False),
            self.request.secondary_priority,
            (neck.elemental_spell_bonus.elements, neck.elemental_spell_bonus.base_max_hit_bonus)
            if neck is not None and neck.elemental_spell_bonus is not None
            else None,
        )
        if key not in self.scoring_option_cache:
            target = role.target or CombatTarget()
            representatives: dict[tuple[Any, ...], tuple[RoleConfig, CombatOption]] = {}
            for configured, option in self.configured_options(role, weapon):
                prayer_key = self.scoring_prayer_key(configured)
                identity: tuple[Any, ...] = (
                    "option",
                    option.attack_type,
                    option.stance,
                    option.spell,
                    option.powered_attack,
                    prayer_key,
                )
                if (
                    configured.style == "magic"
                    and option.powered_attack is None
                    and option.spell in ELEMENTAL_SPELLS
                ):
                    element, tier = option.spell.split("_")
                    element = "air" if element == "wind" else element
                    matched = element == target.weakness_element and target.weakness_percent > 0
                    identity = (
                        "elemental",
                        option.stance,
                        tier,
                        matched,
                        applied_spell_bonus(neck, option.spell),
                        bool(applied_tome(shield, option.spell)),
                        prayer_key,
                    )
                previous = representatives.get(identity)
                if previous is None or (
                    option.spell or "",
                    -len(configured.active_prayer_ids),
                    tuple(reversed(configured.active_prayer_ids)),
                ) > (
                    previous[1].spell or "",
                    -len(previous[0].active_prayer_ids),
                    tuple(reversed(previous[0].active_prayer_ids)),
                ):
                    representatives[identity] = (configured, option)
            self.scoring_option_cache[key] = tuple(representatives.values())
        return self.scoring_option_cache[key]

    def prepare(self, equipment: Mapping[str, int]) -> PreparedEquipment | CombatPerformance:
        """Validate physical slots before using cached incremental bonus totals."""
        problems = equipment_problems(equipment, self.items)
        if problems:
            return CombatPerformance(supported=False, limitations=problems)
        return self.scorer.prepare(equipment)

    def evaluate(self, equipment: Mapping[str, int], role: RoleConfig) -> CombatPerformance:
        prepared = self.prepare(equipment)
        return (
            prepared
            if isinstance(prepared, CombatPerformance)
            else evaluate_prepared_loadout(prepared, role, self.levels)
        )

    def option_rank(
        self, performance: CombatScore, option: CombatOption, prayers: tuple[str, ...]
    ) -> tuple[Any, ...]:
        """Rank immutable results directly; only metric-first lanes need a projection."""
        primary = (
            (
                secondary_value(
                    self.request.secondary_priority,
                    {
                        "supported": performance.supported,
                        "accuracy": performance.accuracy,
                        "bonuses": performance.bonuses.__dict__,
                        "player_defence_rolls": performance.player_defence_rolls,
                    },
                ),
                performance.dps or 0,
            )
            if getattr(self, "metric_first", False)
            else (performance.dps or 0,)
        )
        return (
            *primary,
            option.attack_type,
            option.stance,
            option.spell or "",
            -len(prayers),
            tuple(reversed(prayers)),
        )

    def scoring_batches(
        self,
        prepared: PreparedEquipment,
        options: tuple[tuple[RoleConfig, CombatOption], ...],
    ) -> tuple[tuple[tuple[RoleConfig, CombatOption], ...], ...]:
        """Try defensive grades in exact metric-first order, with legal fallbacks.

        Only the first grade with a supported outgoing attack can win. Raw roll
        math and the secondary projection are shared with full combat evaluation.
        Unknown required levels retain exhaustive evaluation and its error policy.
        """
        priority = self.request.secondary_priority
        if not getattr(self, "metric_first", False) or not priority.endswith("_defence_roll"):
            return (options,)
        grades: dict[float, list[tuple[RoleConfig, CombatOption]]] = {}
        memo: dict[tuple[str, int, int], float] = {}
        for configured, option in options:
            modifiers = prayer_effects(configured.active_prayer_ids)
            key = (configured.stance, modifiers.defence, modifiers.magic_defence)
            if key not in memo:
                rolls = raw_player_defence_rolls(
                    self.levels, prepared.bonuses, configured.stance, modifiers
                )
                try:
                    memo[key] = secondary_value(
                        priority, {"supported": True, "player_defence_rolls": rolls}
                    )
                except ValueError:
                    return (options,)
            grades.setdefault(memo[key], []).append((configured, option))
        return tuple(tuple(grades[value]) for value in sorted(grades, reverse=True))

    def lazy_eligible(self, role: RoleConfig) -> bool:
        return (
            lazy_reporting_active()
            and type(self) is _Search
            and (len(self.request.roles) == 1 or self.compact_multi)
            and role.style != "special"
            and (role.combat_options is not None or role.prayers.mode != "disabled")
        )

    def configured_winner(
        self,
        equipment: Mapping[str, int],
        role: RoleConfig,
        prepared: PreparedEquipment | CombatPerformance | None = None,
        *,
        cache_result: bool = False,
    ) -> _Winner | None:
        key = (
            role.id,
            _equipment_identity(equipment),
            getattr(self, "metric_first", False),
            self.request.secondary_priority,
        )
        cache = self.lazy_eligible(role) or cache_result
        if cache and key in self.compact_cache:
            cached = self.compact_cache[key]
            assert cached is None or isinstance(cached, _Winner)
            return cached
        if self.native_context is not None:
            from tracker.gear.native.adapter import winner as native_winner

            winner = native_winner(self, equipment, role, prepared)
            if cache:
                self.compact_cache[key] = winner
            return winner
        weapon = self.items.get(equipment.get("weapon", -1))
        options = self.scoring_options(
            role,
            weapon,
            self.items.get(equipment.get("neck", -1)),
            self.items.get(equipment.get("shield", -1)),
        )
        if prepared is None and options:
            prepared = self.prepare(equipment)
        include_defence = getattr(self, "metric_first", False) and (
            self.request.secondary_priority.endswith("_defence_roll")
        )
        evaluated = []
        if isinstance(prepared, PreparedEquipment):
            for batch in self.scoring_batches(prepared, options):
                for configured, option in batch:
                    score = evaluate_prepared_score(
                        prepared, configured, self.levels, include_defence=include_defence
                    )
                    if score.supported:
                        evaluated.append(_Winner(score, option, configured))
                if evaluated:
                    break
        winner = (
            max(
                evaluated,
                key=lambda row: self.option_rank(row.score, row.option, row.role.active_prayer_ids),
            )
            if evaluated
            else None
        )
        if cache:
            self.compact_cache[key] = winner
        return winner

    def fixed_eligible(self, role: RoleConfig) -> bool:
        return (
            fixed_reporting_active()
            and type(self) is _Search
            and (len(self.request.roles) == 1 or self.compact_multi)
            and role.style != "special"
            and role.combat_options is None
            and role.prayers.mode == "disabled"
        )

    def fixed_performance(self, equipment: Mapping[str, int], role: RoleConfig) -> dict[str, Any]:
        key = ("fixed", role.id, _equipment_identity(equipment))
        cached = self.compact_cache.get(key)
        if cached is None:
            prepared = self.prepare(equipment)
            if not isinstance(prepared, PreparedEquipment):
                return self.performance(equipment, role)
            cached = evaluate_prepared_score(
                prepared,
                role,
                self.levels,
                include_defence=self.request.secondary_priority.endswith("_defence_roll"),
            )
            if role.style == "magic" and role.powered_attack is None:
                problem = ancient_spell_problem(
                    self.items.get(equipment.get("weapon", -1)),
                    self.snapshot,
                    role.spell,
                    role.stance,
                    self.levels,
                )
                if problem:
                    cached = cached._replace(supported=False, dps=None)
            self.compact_cache[key] = cached
        assert isinstance(cached, CombatScore)
        return {
            "supported": cached.supported,
            "dps": cached.dps,
            "accuracy": cached.accuracy,
            "bonuses": cached.bonuses.__dict__,
            "player_defence_rolls": cached.player_defence_rolls,
        }

    def search_performance(self, equipment: Mapping[str, int], role: RoleConfig) -> dict[str, Any]:
        key = (role.id, _equipment_identity(equipment))
        if key in self.performance_cache:
            return self.performance(equipment, role)
        if getattr(self, "compact_cost_ranking", False) and role.style != "special":
            from tracker.gear.compact_costs import active as compact_costs_active

            if compact_costs_active():
                return self.compact_combat(equipment, role)[0]
        if self.fixed_eligible(role):
            if self.cancelled and self.cancelled():
                raise ValueError("optimization_cancelled")
            return self.fixed_performance(equipment, role)
        if not self.lazy_eligible(role):
            return self.performance(equipment, role)
        if self.cancelled and self.cancelled():
            raise ValueError("optimization_cancelled")
        winner = self.configured_winner(equipment, role)
        if winner is None:
            return {"supported": False, "dps": None}
        score = winner.score
        rolls = score.player_defence_rolls
        if rolls is None and self.request.secondary_priority.endswith("_defence_roll"):
            rolls = raw_player_defence_rolls(
                self.levels,
                score.bonuses,
                winner.role.stance,
                prayer_effects(winner.role.active_prayer_ids),
            )
        return {
            "supported": score.supported,
            "dps": score.dps,
            "accuracy": score.accuracy,
            "bonuses": score.bonuses.__dict__,
            "player_defence_rolls": rolls,
        }

    def compact_combat(
        self, equipment: Mapping[str, int], role: RoleConfig
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Numeric ranking with the same option winner and exact seeded overrides."""
        from tracker.gear.combat import numeric_attack_interval

        key = (role.id, _equipment_identity(equipment))
        if key in self.performance_cache or role.style == "special":
            return self.performance(equipment, role), self.combat_option(equipment, role)
        if self.cancelled and self.cancelled():
            raise ValueError("optimization_cancelled")
        weapon = self.items.get(equipment.get("weapon", -1))
        selected = role
        if role.combat_options is not None or role.prayers.mode != "disabled":
            winner = self.configured_winner(equipment, role, cache_result=True)
            if winner is None:
                return {"supported": False, "dps": None}, None
            score, option, selected = winner
            public_option = option.model_dump(
                mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
            )
        else:
            score_key = ("numeric-fixed", *key)
            cached = self.compact_cache.get(score_key)
            if cached is None:
                prepared = self.prepare(equipment)
                if not isinstance(prepared, PreparedEquipment):
                    return self.performance(equipment, role), self.combat_option(equipment, role)
                cached = evaluate_prepared_score(prepared, role, self.levels)
                if (
                    role.style == "magic"
                    and role.powered_attack is None
                    and ancient_spell_problem(
                        weapon, self.snapshot, role.spell, role.stance, self.levels
                    )
                ):
                    cached = cached._replace(supported=False, dps=None)
                self.compact_cache[score_key] = cached
            assert isinstance(cached, CombatScore)
            score = cached
            public_option = {
                "attack_type": role.style,
                "stance": role.stance,
                "spell": role.spell if role.style == "magic" else None,
                "powered_attack": None,
            }
        rolls = score.player_defence_rolls
        if rolls is None and self.request.secondary_priority.endswith("_defence_roll"):
            rolls = raw_player_defence_rolls(
                self.levels,
                score.bonuses,
                selected.stance,
                prayer_effects(selected.active_prayer_ids),
            )
        return {
            "supported": score.supported,
            "dps": score.dps,
            "accuracy": score.accuracy,
            "bonuses": score.bonuses.__dict__,
            "player_defence_rolls": rolls,
            "attack_interval": (
                numeric_attack_interval(weapon, selected) if score.supported else None
            ),
        }, public_option

    def search_secondary(
        self, equipment: Mapping[str, int], roles: tuple[RoleConfig, ...]
    ) -> float:
        if not all(self.lazy_eligible(role) or self.fixed_eligible(role) for role in roles):
            return self.secondary({role.id: equipment for role in roles})
        if self.request.secondary_priority == "default":
            return 0.0
        weight = sum(role.weight for role in roles)
        return sum(
            secondary_value(
                self.request.secondary_priority, self.search_performance(equipment, role)
            )
            * role.weight
            for role in roles
        ) / (weight or 1)

    def partial_secondary(self, loadouts: Mapping[str, Mapping[str, int]]) -> float:
        """Rank Multi prefixes numerically, retaining role weights and option winners."""
        if self.request.secondary_priority == "default":
            return 0.0
        roles = [r for r in self.request.roles if r.style != "special" and r.id in loadouts]
        weight = sum(r.weight for r in roles)
        return sum(
            secondary_value(
                self.request.secondary_priority, self.search_performance(loadouts[r.id], r)
            )
            * r.weight
            for r in roles
        ) / (weight or 1)

    def performance(self, equipment: Mapping[str, int], role: RoleConfig) -> dict[str, Any]:
        key = (role.id, _equipment_identity(equipment))
        if key not in self.performance_cache:
            if self.cancelled and self.cancelled():
                raise ValueError("optimization_cancelled")
            if role.style == "special":
                result: dict[str, Any] = {
                    "supported": True,
                    "dps": None,
                    "limitations": [
                        "Special role is unscored; no damage or utility benefit assumed."
                    ],
                }
            elif role.combat_options is not None or role.prayers.mode != "disabled":
                options = self.scoring_options(
                    role,
                    self.items.get(equipment.get("weapon", -1)),
                    self.items.get(equipment.get("neck", -1)),
                    self.items.get(equipment.get("shield", -1)),
                )
                prepared = self.prepare(equipment) if options else None
                winner = self.configured_winner(equipment, role, prepared)
                if winner is not None:
                    selected, selected_role = winner.option, winner.role
                    selected_prayers = selected_role.active_prayer_ids
                    assert isinstance(prepared, PreparedEquipment)
                    result = evaluate_prepared_loadout(
                        prepared, selected_role, self.levels
                    ).model_dump(mode="json")
                    self.option_cache[key] = selected.model_dump(
                        mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
                    )
                    self.option_cache[key] = {
                        **(self.option_cache[key] or {}),
                        "__prayer_ids": list(selected_prayers),
                    }
                else:
                    result = {
                        "supported": False,
                        "dps": None,
                        "limitations": [
                            "No legal combat configuration satisfies account and option filters."
                        ],
                    }
                    self.option_cache[key] = None
            else:
                result = self.evaluate(equipment, role).model_dump(mode="json")
                problem = (
                    ancient_spell_problem(
                        self.items.get(equipment.get("weapon", -1)),
                        self.snapshot,
                        role.spell,
                        role.stance,
                        self.levels,
                    )
                    if role.style == "magic" and role.powered_attack is None
                    else None
                )
                if problem:
                    result = {
                        **result,
                        "supported": False,
                        "dps": None,
                        "limitations": [*result["limitations"], problem],
                    }
                self.option_cache[key] = {
                    "attack_type": role.style,
                    "stance": role.stance,
                    "spell": role.spell if role.style == "magic" else None,
                    "powered_attack": None,
                }
            self.performance_cache[key] = result
        return self.performance_cache[key]

    def combat_option(
        self, equipment: Mapping[str, int], role: RoleConfig
    ) -> dict[str, Any] | None:
        self.performance(equipment, role)
        option = self.option_cache.get((role.id, _equipment_identity(equipment)))
        return {k: v for k, v in option.items() if k != "__prayer_ids"} if option else None

    def selected_prayers(self, equipment: Mapping[str, int], role: RoleConfig) -> list[str]:
        self.performance(equipment, role)
        option = self.option_cache.get((role.id, _equipment_identity(equipment))) or {}
        return list(option.get("__prayer_ids", ()))

    def secondary(self, loadouts: Mapping[str, Mapping[str, int]]) -> float:
        """Normalize active time across scored roles; utility roles contribute nothing."""
        if self.request.secondary_priority == "default":
            return 0.0
        roles = [r for r in self.request.roles if r.style != "special" and r.id in loadouts]
        weight = sum(r.weight for r in roles)
        return sum(
            secondary_value(self.request.secondary_priority, self.performance(loadouts[r.id], r))
            * r.weight
            for r in roles
        ) / (weight or 1)

    def compatible(self, equipment: Mapping[str, int]) -> bool:
        weapon = self.items.get(equipment.get("weapon", -1))
        return not (weapon and weapon.two_handed and "shield" in equipment)

    def candidate_pools(self) -> dict[str, list[int | None]]:
        numeric = self.factored_evaluation and type(self) is _Search
        performance_for = self.search_performance if numeric else self.performance
        secondary_for = self.partial_secondary if numeric else self.secondary
        locked = {v for r in self.request.roles for v in r.locks.values() if v is not None}
        locked |= {v for v in self.request.locks.values() if v is not None}
        pools: dict[str, list[int | None]] = {}
        baselines = {r.id: self.baselines(r) for r in self.request.roles}
        for index, slot in enumerate(SLOTS):
            self.reporter.slots(index / len(SLOTS))
            candidates = [i for i, item in self.eligible.items() if item.slot == slot]
            # Compare actual model DPS against legal weapon/ammunition scaffolds;
            # never invent weighted bonus desirability scores.
            by_role: list[list[int]] = []
            for role in self.request.roles:

                def marginal(i: int, role: RoleConfig = role, slot: str = slot) -> float:
                    scores = []
                    secondary_scores = []
                    for base in baselines[role.id]:
                        equipment = {**base, slot: i}
                        if self.compatible(equipment):
                            performance = performance_for(equipment, role)
                            if performance["supported"]:
                                scores.append(performance.get("dps") or 0)
                                secondary_scores.append(
                                    (scores[-1], secondary_for({role.id: equipment}))
                                )
                    value = max(scores, default=-1)
                    self.marginals[role.id, i] = value
                    self.secondary_marginals[role.id, i] = max(
                        (secondary for score, secondary in secondary_scores if score == value),
                        default=0,
                    )
                    return value

                by_role.append(
                    sorted(
                        candidates,
                        key=lambda i: (
                            -marginal(i),
                            -self.secondary_marginals[role.id, i],
                            *self.acquisition_tie({i}),
                            i,
                        ),
                    )
                )
            cheap = sorted(
                candidates, key=lambda i: (self.cost({i}), self.untradeable_acquisitions({i}), i)
            )
            ordered = sorted(locked & set(candidates))
            for row in zip(
                *[lst + [None] * (len(candidates) - len(lst)) for lst in [cheap, *by_role]],
                strict=False,
            ):
                ordered.extend(i for i in row if i is not None and i not in ordered)
            keep = max(CANDIDATES_PER_SLOT - 1, len(locked & set(candidates)))
            self.truncated |= len(ordered) > keep
            retained = ordered[:keep]
            if slot in {"weapon", "head"}:
                from tracker.gear.halberds import FORMS as HALBERD_FORMS

                relevant = set(HALBERD_FORMS) if slot == "weapon" else {12931}
                if any(r.style in {"stab", "slash", "crush"} for r in self.request.roles):
                    retained = list(
                        dict.fromkeys([*retained, *(i for i in ordered if i in relevant)])
                    )
            if slot in {"head", "weapon"} and any(r.on_slayer_task for r in self.request.roles):
                # Task effects can beat stronger raw stats in complete loadouts.
                # Preserve physical choices: ownership, prices and locks differ.
                retained = list(
                    dict.fromkeys(
                        [
                            *retained,
                            *(
                                i
                                for i in ordered
                                if self.items[i].slayer_bonus
                                or self.items[i].slayer_staff_enchanted
                            ),
                        ]
                    )
                )
            if slot in {"weapon", "ammunition"} and any(
                r.target is not None and "leafy" in r.target.traits for r in self.request.roles
            ):
                from tracker.gear.leafy import BROAD_AMMO, LEAF_WEAPONS
                from tracker.gear.slayer import MAGIC_DART_STAVES

                contextual = (
                    BROAD_AMMO if slot == "ammunition" else LEAF_WEAPONS | MAGIC_DART_STAVES
                )
                retained = list(
                    dict.fromkeys([*retained, *(i for i in ordered if i in contextual)])
                )
            if slot == "ammunition":
                # Equal-strength dragon bolts have distinct target-dependent procs.
                # Preserve every reviewed effect/form without dropping ordinary candidates.
                retained = list(
                    dict.fromkeys([*retained, *(i for i in ordered if self.items[i].bolt_effect)])
                )
            if slot == "shield":
                retained = list(
                    dict.fromkeys([*retained, *(i for i in ordered if self.items[i].tome_effect)])
                )
            if slot == "weapon":
                # Preserve weapon families whose complete-gear synergy is invisible
                # to weapon-only scaffolds, without changing the DPS objective.
                families: dict[str, int] = {}
                for i in ordered:
                    model = self.items[i].powered_attack_model
                    if model and any(
                        self.configured_options(r, self.items[i]) for r in self.request.roles
                    ):
                        families.setdefault(model, i)
                retained = list(dict.fromkeys([*retained, *families.values()]))
            pools[slot] = [None, *retained]
        return pools

    def baselines(self, role: RoleConfig) -> list[dict[str, int]]:
        """Legal ordinary-attack scaffolds for model-based candidate selection."""
        performance = (
            self.search_performance
            if self.factored_evaluation and type(self) is _Search
            else self.performance
        )
        bases: list[dict[str, int]] = [{}]
        for item_id, item in self.eligible.items():
            if item.slot != "weapon":
                continue
            base = {"weapon": item_id}
            if role.style == "ranged" and item.ammo_for:
                bases.extend(
                    {**base, "ammunition": ammo_id}
                    for ammo_id, ammo in self.eligible.items()
                    if ammo.slot == "ammunition" and ammo.ammo_type in item.ammo_for
                )
            else:
                bases.append(base)
        bases.extend(self.synergy_seeds((role,))[1:])
        return [b for b in bases if performance(b, role)["supported"]]

    def synergy_seeds(
        self, roles: tuple[RoleConfig, ...], *, best_only: bool = False
    ) -> list[dict[str, int]]:
        """Trial complete reviewed halberd/head pairs before isolated slots prune them."""
        from tracker.gear.halberds import FORMS as HALBERD_FORMS

        seeds: list[dict[str, int]] = [{}]
        if 12931 not in self.eligible or any(
            r.style not in {"stab", "slash", "crush"} for r in roles
        ):
            return seeds
        for weapon in HALBERD_FORMS:
            pair = {"weapon": weapon, "head": 12931}
            if (
                weapon not in self.eligible
                or self.cost(set(pair.values())) > self.request.budget_gp
            ):
                continue
            if any(
                any(slot in locks and locks[slot] != item for slot, item in pair.items())
                or locks.get("shield") is not None
                for role in roles
                for locks in ({**self.request.locks, **role.locks},)
            ):
                continue
            seeds.append(pair)
        if best_only and len(seeds) > 2:
            tested = [
                (sum((self.performance(seed, r).get("dps") or 0) * r.weight for r in roles), seed)
                for seed in seeds[1:]
                if all(self.performance(seed, r)["supported"] for r in roles)
            ]
            if not tested:
                return [{}]
            _, best = max(
                tested,
                key=lambda row: (row[0], -self.cost(set(row[1].values())), -row[1]["weapon"]),
            )
            return [{}, best]
        return seeds

    def joint_loadouts(self, limit: int | None) -> list[dict[str, dict[str, int]]]:
        """Assign each slot jointly, retaining shared choices before role beams lose them.

        Actual baseline DPS comparisons select branches; final complete DPS remains
        the only scoring objective. Width/branch caps keep the search bounded.
        """
        roles = self.request.roles
        role_indices = {role.id: index for index, role in enumerate(roles)}
        indexed_edges = tuple((role_indices[a], role_indices[b]) for a, b in self.edges)
        numeric = self.compact_multi and type(self) is _Search
        performance = self.search_performance if numeric else self.performance
        secondary = self.partial_secondary if numeric else self.secondary
        beam = [
            _assignment_state({r.id: equipment for r, equipment in zip(roles, rows, strict=True)})
            for rows in product(*(self.synergy_seeds((r,), best_only=True) for r in roles))
        ]
        for index, slot in enumerate(SLOTS):
            self.reporter.slots(index / len(SLOTS))
            candidates = [i for i in self.pools[slot] if i is not None]
            common = sorted(
                candidates,
                key=lambda i: (
                    -sum(self.marginals.get((r.id, i), -1) * r.weight for r in roles),
                    -sum(
                        self.secondary_marginals.get((r.id, i), 0) * r.weight
                        for r in roles
                        if r.style != "special"
                    ),
                    *self.acquisition_tie({i}),
                    i,
                ),
            )[:1]
            choices = []
            for role in roles:
                locks = {**self.request.locks, **role.locks}
                ranked = sorted(
                    candidates,
                    key=lambda i: (
                        -self.marginals.get((role.id, i), -1),
                        -self.secondary_marginals.get((role.id, i), 0),
                        *self.acquisition_tie({i}),
                        i,
                    ),
                )
                options = (
                    [locks[slot]]
                    if slot in locks
                    else list(
                        dict.fromkeys(
                            [
                                None,
                                *ranked[:2],
                                *common,
                                *(
                                    sorted(
                                        candidates,
                                        key=lambda i: (
                                            -self.secondary_marginals.get((role.id, i), 0),
                                            *self.acquisition_tie({i}),
                                            i,
                                        ),
                                    )[:2]
                                    if getattr(self, "frontier_search", False)
                                    else []
                                ),
                            ]
                        )
                    )
                )
                choices.append(options)
            if self.native_context is not None:
                from tracker.gear.native.adapter import expand

                beam = expand(
                    self,
                    "joint",
                    beam,
                    choices,
                    slot=slot,
                    roles=roles,
                    cap=limit,
                    limit=32 if getattr(self, "frontier_search", False) else 16,
                )
                if not beam:
                    break
                continue
            expanded = []
            for state in beam:
                for assigned in product(*choices):
                    if not self.tick():
                        break
                    candidate: Any
                    if self.compact_states:
                        from tracker.gear.compact_states import AssignmentState

                        equipment_rows = tuple(
                            equipment.with_slot(slot, item) if item is not None else equipment
                            for (_, equipment), item in zip(state.roles, assigned, strict=True)
                        )
                        carried_ids = frozenset().union(*(e.physical_ids for e in equipment_rows))
                        if any(i not in self.eligible for i in carried_ids):
                            continue
                        if any(not self.compatible(e) for e in equipment_rows):
                            continue
                        if self.cost(carried_ids) > self.request.budget_gp:
                            continue
                        if any(
                            len(carried_ids - e.physical_ids)
                            > 28 - self.request.reserved_supply_slots
                            for e in equipment_rows
                        ):
                            continue
                        if limit is not None and any(
                            _action_lower_bound(equipment_rows[a], equipment_rows[b], self.items)
                            > limit
                            for a, b in indexed_edges
                        ):
                            continue
                        if slot not in ("weapon", "shield") and any(
                            not performance(e, r)["supported"]
                            for r, e in zip(roles, equipment_rows, strict=True)
                        ):
                            continue
                        expanded.append(
                            AssignmentState.from_roles(
                                tuple((r.id, e) for r, e in zip(roles, equipment_rows, strict=True))
                            )
                        )
                        continue
                    candidate = {
                        r.id: {**state[r.id], **({slot: i} if i is not None else {})}
                        for r, i in zip(roles, assigned, strict=True)
                    }
                    carried = (
                        candidate.carried
                        if self.compact_states
                        else {i for equipment in candidate.values() for i in equipment.values()}
                    )
                    if any(i not in self.eligible for i in carried):
                        continue
                    if any(not self.compatible(e) for e in candidate.values()):
                        continue
                    if self.cost(carried) > self.request.budget_gp:
                        continue
                    if any(
                        inventory_slots(e, carried, self.items)
                        > 28 - self.request.reserved_supply_slots
                        for e in candidate.values()
                    ):
                        continue
                    if limit is not None and any(
                        _action_lower_bound(candidate[a], candidate[b], self.items) > limit
                        for a, b in self.edges
                    ):
                        continue
                    if slot not in ("weapon", "shield") and any(
                        not performance(candidate[r.id], r)["supported"] for r in roles
                    ):
                        continue
                    expanded.append(candidate)

            def rank(c: Any) -> tuple[Any, ...]:
                # Model-derived branch ordering; full joint solutions below are
                # always compared using their complete calculated encounter score.
                score = sum(
                    self.marginals.get((r.id, i), 0) * r.weight
                    for r in roles
                    for i in _equipment_ids(c[r.id])
                )
                union = (
                    c.carried
                    if self.compact_states
                    else {i for e in c.values() for i in e.values()}
                )
                return (
                    -score,
                    -secondary(c),
                    len(union),
                    self.cost(union),
                    self.untradeable_acquisitions(union),
                    self.assignment_tie(c),
                )

            beam = self.retain(
                expanded, rank, 32 if getattr(self, "frontier_search", False) else 16
            )
            if not beam:
                break
        return beam if beam and all(len(e) <= len(SLOTS) for e in beam[0].values()) else []

    def loadouts(self, roles: tuple[RoleConfig, ...]) -> list[dict[str, int]]:
        """Assign common equipment when several roles are passed (zero-action seed)."""
        performance = (
            self.search_performance
            if self.factored_evaluation and type(self) is _Search
            else self.performance
        )
        locks = dict[str, int | None](self.request.locks.items())
        for role in roles:
            for slot, item_id in role.locks.items():
                if slot in locks and locks[slot] != item_id:
                    return []
                locks[slot] = item_id
        states = [_equipment_state(seed) for seed in self.synergy_seeds(roles)]
        for index, slot in enumerate(SLOTS):
            self.reporter.slots(index / len(SLOTS))
            choices = [locks[slot]] if slot in locks else self.pools[slot]
            if self.native_context is not None:
                from tracker.gear.native.adapter import expand

                states = expand(
                    self,
                    "loadout",
                    states,
                    choices,
                    slot=slot,
                    roles=roles,
                    limit=BEAM_WIDTH,
                )
                if not states:
                    return []
                continue
            expanded: list[dict[str, int]] = []
            for state, item_id in product(states, choices):
                if not self.tick():
                    break
                if item_id is not None and (
                    item_id not in self.eligible or self.items[item_id].slot != slot
                ):
                    continue
                if self.compact_states:
                    weapon_id = (
                        item_id if slot == "weapon" and item_id is not None else state.slots[0]
                    )
                    weapon = self.items.get(weapon_id) if weapon_id is not None else None
                    shield = (
                        (item_id is not None) if slot == "shield" else state.slots[1] is not None
                    )
                    if weapon and weapon.two_handed and shield:
                        continue
                    physical_ids = (
                        state.physical_ids if item_id is None else state.physical_ids | {item_id}
                    )
                    if self.cost(physical_ids) > self.request.budget_gp:
                        continue
                    candidate = state.with_slot(slot, item_id) if item_id is not None else state
                else:
                    addition: dict[str, int] = {slot: item_id} if item_id is not None else {}
                    candidate = {**state, **addition}
                    if (
                        not self.compatible(candidate)
                        or self.cost(set(candidate.values())) > self.request.budget_gp
                    ):
                        continue
                # Weapon/ammo legality can be checked once both slots have been assigned.
                if slot not in ("weapon", "shield") and any(
                    not self.search_performance(candidate, r)["supported"] for r in roles
                ):
                    continue
                expanded.append(candidate)

            def rank(e: Any) -> tuple[Any, ...]:
                physical_ids = e.physical_ids if self.compact_states else set(e.values())
                score = sum(
                    (self.search_performance(e, r).get("dps") or 0) * r.weight for r in roles
                )
                # Exact partial-DPS ties can hide a later max-hit breakpoint.
                # Preserve melee strength before arbitrary item IDs; complete DPS
                # remains the first key and the final solution's only damage score.
                strength = (
                    sum(self.items[i].bonuses.melee_strength for i in _equipment_ids(e))
                    if all(r.style in {"stab", "slash", "crush"} for r in roles)
                    else 0
                )
                return (
                    -score,
                    -self.search_secondary(e, roles),
                    self.cost(physical_ids),
                    -strength,
                    self.untradeable_acquisitions(physical_ids),
                    _equipment_identity(e),
                )

            states = self.retain(expanded, rank, BEAM_WIDTH)
            if not states:
                return []
        return [s for s in states if all(performance(s, r)["supported"] for r in roles)]

    def solution(
        self, loadouts: Mapping[str, Mapping[str, int]], limit: int | None
    ) -> dict[str, Any] | None:
        if self.compact_states and not getattr(self, "_compact_solution_bypass", False):
            from tracker.gear.compact_solutions import compact_solution

            return compact_solution(self, loadouts, limit)
        if any(not self.performance(loadouts[r.id], r)["supported"] for r in self.request.roles):
            return None
        for role in self.request.roles:
            equipment = loadouts[role.id]
            if loadout_problems(equipment, self.items, self.facts, self.request, role):
                return None
        carried = {i for equipment in loadouts.values() for i in equipment.values()}
        cost = self.cost(carried)
        if cost > self.request.budget_gp:
            return None
        capacity = 28 - self.request.reserved_supply_slots
        base = self.request.base_role or self.request.roles[0].id
        occupancies = [inventory_slots(e, carried, self.items) for e in loadouts.values()]
        if max(occupancies, default=0) > capacity:
            return None
        transitions: list[dict[str, Any]] = []
        for a, b in self.edges:
            transition = self._transition(
                tuple(sorted(loadouts[a].items())),
                tuple(sorted(loadouts[b].items())),
                frozenset(carried),
                capacity,
            )
            if transition is None or (limit is not None and transition["action_count"] > limit):
                return None
            transitions.append({"from_role": a, "to_role": b, **deepcopy(transition)})
        weight = sum(r.weight for r in self.request.roles if r.style != "special")
        score = sum(
            (self.performance(loadouts[r.id], r).get("dps") or 0) * r.weight
            for r in self.request.roles
            if r.style != "special"
        ) / (weight or 1)
        peak = max([*occupancies, *(t["max_gear_inventory_slots"] for t in transitions)], default=0)
        result = {
            "score": score,
            "secondary_priority": self.request.secondary_priority,
            "secondary_value": self.secondary(loadouts)
            if self.request.secondary_priority != "default"
            else None,
            "loadouts": {
                r.id: {
                    "equipment": dict(loadouts[r.id]),
                    "preparations": [
                        self.facts[i]["preparation"]
                        for i in sorted(loadouts[r.id].values())
                        if self.facts[i].get("preparation")
                    ],
                    "discipline": (
                        None
                        if r.style == "special"
                        else "melee"
                        if r.style in {"stab", "slash", "crush"}
                        else r.style
                    ),
                    "performance": self.performance(loadouts[r.id], r),
                    "combat_option": self.combat_option(loadouts[r.id], r),
                    "selected_prayer_ids": self.selected_prayers(loadouts[r.id], r),
                }
                for r in self.request.roles
            },
            "transitions": transitions,
            "purchase_cost_gp": cost,
            "purchases": purchases(carried, self.facts, self.request),
            "unowned_untradeable_item_ids": unowned_untradeables(carried, self.facts, self.request),
            "carried_item_ids": sorted(carried),
            "distinct_items": len(carried),
            "gear_inventory_slots": inventory_slots(loadouts[base], carried, self.items),
            "max_gear_inventory_slots": peak,
            "remaining_supply_slots": 28 - peak,
            "remaining_inventory_slots": 28 - peak - self.request.reserved_supply_slots,
            "reserved_supply_slots": self.request.reserved_supply_slots,
            "maximum_actions": max((t["action_count"] for t in transitions), default=0),
            "potions": None,
        }
        if hasattr(self, "running_prices"):
            from tracker.gear.running_frontier import add_solution_costs

            if self.request.potions.mode == "fixed":
                result = {
                    **result,
                    "potions": potion_summary(
                        {k: v.level for k, v in self.snapshot.skills.items()},
                        self.request.potions.selected_ids,
                        self.running_prices,
                        self.running_at,
                    ),
                }
            return add_solution_costs(result, self)
        return result


def _solution_key(solution: Mapping[str, Any]) -> tuple[Any, ...]:
    cached: tuple[Any, ...] | None = getattr(solution, "_compact_rank", None)
    if cached is not None:
        return cached
    from tracker.gear.variant_reporting import loadout_tie

    return (
        -solution["score"],
        -(solution.get("secondary_value") or 0),
        solution["max_gear_inventory_slots"],
        solution["purchase_cost_gp"],
        len(solution.get("unowned_untradeable_item_ids", ())),
        sum(t["action_count"] for t in solution["transitions"]),
        (solution.get("potions") or {}).get("cost_per_application_gp") is None,
        (solution.get("potions") or {}).get("cost_per_application_gp") or 0,
        len((solution.get("potions") or {}).get("selected_ids", ())),
        loadout_tie(solution),
    )


def _action_lower_bound(
    source: Mapping[str, int],
    destination: Mapping[str, int],
    items: Mapping[int, EquipmentDefinition],
) -> int:
    from tracker.gear.compact_states import EquipmentState

    if isinstance(source, EquipmentState) and isinstance(destination, EquipmentState):
        old, new = source.slots, destination.slots
        actions = sum(a != b for a, b in zip(old, new, strict=True))
        # Existing SLOTS keeps weapon/shield first. Automatic hand removals
        # consume no separate action, exactly as in the mapping lower bound.
        weapon = items.get(new[0]) if new[0] is not None else None
        if new[0] is not None and new[0] != old[0] and weapon and weapon.two_handed:
            actions -= int(old[1] is not None and new[1] is None)
        previous_weapon = items.get(old[0]) if old[0] is not None else None
        if (
            new[1] is not None
            and new[1] != old[1]
            and previous_weapon
            and previous_weapon.two_handed
        ):
            actions -= int(old[0] is not None and new[0] is None)
        return actions
    equips = {s for s, i in destination.items() if source.get(s) != i}
    removed = {s for s in source if s not in destination}
    weapon = items.get(destination.get("weapon", -1))
    if "weapon" in equips and weapon and weapon.two_handed:
        removed.discard("shield")
    previous_weapon = items.get(source.get("weapon", -1))
    if "shield" in equips and previous_weapon and previous_weapon.two_handed:
        removed.discard("weapon")
    return len(equips) + len(removed)


def _slot_alternatives(search: _Search, solution: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate substitutions in the selected surrounding setup, without a new search."""
    if solution is None or len(search.request.roles) != 1:
        return {}
    role = search.request.roles[0]
    equipment = solution["loadouts"][role.id]["equipment"]
    alternatives: dict[str, Any] = {}
    for slot, candidates in search.pools.items():
        rows = []
        for item_id in candidates:
            if item_id == equipment.get(slot):
                continue
            replacement = {s: i for s, i in equipment.items() if s != slot}
            if item_id is not None:
                replacement[slot] = item_id
            candidate = search.solution({role.id: replacement}, search.request.max_swaps)
            if candidate is not None:
                rows.append(
                    {
                        "item_id": item_id,
                        "score": candidate["score"],
                        "score_delta": candidate["score"] - solution["score"],
                        "secondary_value": candidate["secondary_value"],
                        "purchase_cost_gp": candidate["purchase_cost_gp"],
                    }
                )
        alternatives[slot] = sorted(
            rows,
            key=lambda r: (
                -r["score"],
                -(r["secondary_value"] or 0),
                r["purchase_cost_gp"],
                r["item_id"] or 0,
            ),
        )[:5]
    return alternatives


@dataclass(frozen=True)
class PreparedOptimization:
    """Base facts reusable across potion branches; no combat scoring caches."""

    catalog: Any
    snapshot: AccountSnapshot
    facts: Mapping[int, dict[str, Any]]
    eligible: Mapping[int, EquipmentDefinition]


def prepare_optimization(
    snapshot: AccountSnapshot,
    request: OptimizationRequest,
    catalog: Any,
    content: Content,
    price_records: Mapping[int, PriceRecord],
    now: datetime,
) -> PreparedOptimization:
    request = request.prepared_weapon_locks()
    catalog = project_catalog(catalog, request.support_policy)
    validate_request_context(request, snapshot, catalog.items, content)
    projected = hypothetical_snapshot(
        snapshot, request.skill_overrides, request.quest_overrides, now
    )
    facts = {
        i: equipment_fact(
            projected,
            item,
            content,
            price_records,
            now,
            support_assumptions=getattr(catalog, "community_assumptions", {}).get(i, ()),
        )
        for i, item in catalog.items.items()
    }
    eligible = {
        i: item for i, item in catalog.items.items() if not item_problems(i, facts[i], request)
    }
    return PreparedOptimization(
        catalog, projected, MappingProxyType(facts), MappingProxyType(eligible)
    )


def optimize(
    snapshot: AccountSnapshot,
    request: OptimizationRequest | Mapping[str, Any],
    catalog: Any,
    content: Content,
    price_records: Mapping[int, PriceRecord],
    now: datetime,
    cancelled: Callable[[], bool] | None = None,
    *,
    targeted_head_refinement: bool = False,
    local_refinement: bool = False,
    _complete_frontiers: bool = False,
    _running_frontier: bool = False,
    _prepared: PreparedOptimization | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    potion_branch_runner: Callable[..., list[dict[str, Any]]] | None = None,
    _execution_profile: str = "baseline",
    _fixed_reporting: bool = False,
    _factored_evaluation: bool = False,
    _compact_states: bool = False,
    _native_search: bool = False,
) -> dict[str, Any]:
    """Return a frozen-context curve; experimental refinements are Python-only opt-in."""
    from tracker.gear.execution_profile import execution_context, validate_profile

    profile = validate_profile(_execution_profile)
    if not isinstance(_fixed_reporting, bool):
        raise ValueError("Invalid fixed reporting option")
    if not isinstance(_factored_evaluation, bool):
        raise ValueError("Invalid factored evaluation option")
    if not isinstance(_compact_states, bool):
        raise ValueError("Invalid compact states option")
    if not isinstance(_native_search, bool):
        raise ValueError("Invalid native search option")
    if _native_search and profile == "baseline":
        from tracker.gear.native import record

        record("fallback", reason="requires_combined_compact_execution")
        _native_search = False
    execution: dict[str, Any] = {"_execution_profile": profile} if profile != "baseline" else {}
    if _fixed_reporting:
        execution["_fixed_reporting"] = True
    if _factored_evaluation:
        execution["_factored_evaluation"] = True
    if _compact_states:
        execution["_compact_states"] = True
    if _native_search:
        execution["_native_search"] = True
    started = perf_counter()
    request = (
        request
        if isinstance(request, OptimizationRequest)
        else OptimizationRequest.model_validate(request)
    )
    request = request.prepared_weapon_locks()
    if request.potions.mode == "optimize":
        from tracker.gear.potion_search import optimize_potions

        return optimize_potions(
            snapshot,
            request,
            catalog,
            content,
            price_records,
            now,
            cancelled=cancelled,
            targeted_head_refinement=targeted_head_refinement,
            local_refinement=local_refinement,
            _complete_frontiers=_complete_frontiers,
            _running_frontier=_running_frontier,
            _prepared=_prepared,
            progress=progress,
            branch_runner=potion_branch_runner,
            **execution,
        )
    if any(role.allowed_disciplines is not None for role in request.roles):
        from tracker.gear.auto import optimize_auto

        return optimize_auto(
            snapshot,
            request,
            catalog,
            content,
            price_records,
            now,
            cancelled=cancelled,
            targeted_head_refinement=targeted_head_refinement,
            local_refinement=local_refinement,
            _prepared=_prepared,
            _complete_frontiers=_complete_frontiers,
            _running_frontier=_running_frontier,
            progress=progress,
            **execution,
        )
    if profile != "baseline":
        with execution_context(
            profile,
            request,
            fixed_reporting=_fixed_reporting,
            factored_evaluation=_factored_evaluation,
            compact_states=_compact_states,
            native_search=_native_search,
        ):
            return optimize(
                snapshot,
                request,
                catalog,
                content,
                price_records,
                now,
                cancelled,
                targeted_head_refinement=targeted_head_refinement,
                local_refinement=local_refinement,
                _complete_frontiers=_complete_frontiers,
                _running_frontier=_running_frontier,
                _prepared=_prepared,
                progress=progress,
                potion_branch_runner=potion_branch_runner,
            )
    reporter = StageReporter(progress) if progress else NULL_REPORTER
    reporter.stage("preparation", elapsed_seconds=0.0)
    prepared = _prepared or prepare_optimization(
        snapshot, request, catalog, content, price_records, now
    )
    catalog, projected, facts = prepared.catalog, prepared.snapshot, prepared.facts
    prepared_at = perf_counter()
    reporter.stage("candidate_ranking", elapsed_seconds=prepared_at - started)
    search = _Search(
        projected, request, catalog.items, facts, cancelled, prepared.eligible, reporter=reporter
    )
    request = search.request
    candidates_at = perf_counter()
    reporter.stage("gear_search", elapsed_seconds=candidates_at - started)
    search.running_prices = price_records
    search.running_at = now
    search.complete_frontiers = _complete_frontiers
    swap_limits = [*range(request.max_swaps + 1), None] if len(request.roles) > 1 else []
    # Equal progress segments: per-role beams, Multi's common/joint/tuple beams, scoring.
    search_units = len(request.roles) + (1 + 2 * len(swap_limits) if swap_limits else 0) + 1
    individual: dict[str, list[Any]] = {}
    for unit, role in enumerate(request.roles):
        reporter.segment(unit, search_units)
        individual[role.id] = search.loadouts((role,))
    unit = len(request.roles)
    for role in request.roles:
        if role.style != "special" or role.parent_role is None:
            continue
        for equipment in individual[role.parent_role]:
            locks = {**request.locks, **role.locks}
            additions: dict[str, int] = {s: i for s, i in locks.items() if i is not None}
            seeded = {**equipment, **additions}
            seeded = {s: i for s, i in seeded.items() if s not in locks or locks[s] is not None}
            weapon = catalog.items.get(seeded.get("weapon", -1))
            if weapon and weapon.two_handed and "shield" not in locks:
                seeded.pop("shield", None)
            if search.compatible(seeded):
                individual[role.id].append(_equipment_state(seeded))
    # Direct common-equipment search avoids losing the zero-swap setup in independent
    # role beams. More complex disconnected graphs are explored by the joint beam.
    # Single has no transitions: its individual beam already contains every
    # shared seed, and all feasible finalists apply to every action cap.
    if swap_limits:
        reporter.segment(unit, search_units)
        unit += 1
    common = (
        individual[request.roles[0].id]
        if len(request.roles) == 1
        else search.loadouts(request.roles)
    )
    tuples: list[dict[str, dict[str, int]]] = [
        _assignment_state({role.id: equipment for role in request.roles}) for equipment in common
    ]
    # Joint per-slot search comes first so independent tuple expansion cannot
    # consume the deterministic node budget before shared gear is explored.
    for swap_limit in swap_limits:
        reporter.segment(unit, search_units)
        unit += 1
        tuples.extend(search.joint_loadouts(swap_limit))

    partial_performance = search.search_performance if search.compact_multi else search.performance
    partial_secondary = search.partial_secondary if search.compact_multi else search.secondary

    def partial_rank(c: Any) -> tuple[Any, ...]:
        score = sum(
            (partial_performance(c[r.id], r).get("dps") or 0) * r.weight
            for r in request.roles
            if r.id in c
        )
        carried = (
            c.carried if search.compact_states else {i for e in c.values() for i in e.values()}
        )
        return (
            -score,
            -partial_secondary(c),
            len(carried),
            *search.acquisition_tie(carried),
            search.assignment_tie(c),
        )

    # Search each constraint separately. A high-scoring unrestricted beam must not
    # evict all feasible low-action tuples before the action limit is considered.
    for swap_limit in swap_limits:
        reporter.segment(unit, search_units)
        unit += 1
        beam = [_assignment_state({})]
        for role_index, role in enumerate(request.roles):
            reporter.fraction(role_index / len(request.roles))
            if search.native_context is not None:
                from tracker.gear.native.adapter import expand

                beam = expand(
                    search,
                    "tuple",
                    beam,
                    individual[role.id],
                    roles=request.roles,
                    cap=swap_limit,
                    limit=BEAM_WIDTH,
                    tuple_role=role.id,
                )
                if not beam:
                    break
                continue
            expanded = []
            for partial, equipment in product(beam, individual[role.id]):
                if not search.tick():
                    break
                if search.compact_states:
                    carried = partial.carried | equipment.physical_ids
                    if search.cost(carried) > request.budget_gp:
                        continue
                    if swap_limit is not None and any(
                        _action_lower_bound(
                            equipment if a == role.id else partial[a],
                            equipment if b == role.id else partial[b],
                            catalog.items,
                        )
                        > swap_limit
                        for a, b in search.edges
                        if (a == role.id or a in partial) and (b == role.id or b in partial)
                    ):
                        continue
                    candidate = partial.with_role(role.id, equipment)
                else:
                    candidate = {**partial, role.id: equipment}
                    carried = {i for e in candidate.values() for i in e.values()}
                    if search.cost(carried) > request.budget_gp:
                        continue
                    if swap_limit is not None and any(
                        _action_lower_bound(candidate[a], candidate[b], catalog.items) > swap_limit
                        for a, b in search.edges
                        if a in candidate and b in candidate
                    ):
                        continue
                expanded.append(candidate)
            beam = sorted(expanded, key=partial_rank)[:BEAM_WIDTH]
            # Only the selected beam survives this expansion. In particular the
            # last product's rejected states must not stay live through frontiers.
            del expanded
        tuples.extend(beam)
    unrestricted = None
    winners: list[dict[str, Any] | None] = [None] * (request.max_swaps + 1)
    unique_tuples = {search.assignment_json(e): e for e in tuples}
    reporter.segment(search_units - 1, search_units)
    for scored, loadouts in enumerate(unique_tuples.values()):
        reporter.fraction(scored / len(unique_tuples))
        if cancelled and cancelled():
            raise ValueError("optimization_cancelled")
        solution = search.solution(loadouts, None)
        if solution is None:
            continue
        if unrestricted is None or _solution_key(solution) < _solution_key(unrestricted):
            unrestricted = solution
        for limit in range(solution["maximum_actions"], request.max_swaps + 1):
            previous = winners[limit]
            if previous is None or _solution_key(solution) < _solution_key(previous):
                winners[limit] = solution
    searched_at = perf_counter()
    reporter.stage("refinement", elapsed_seconds=searched_at - started)
    refinement_units = 2 + int(targeted_head_refinement) + int(local_refinement)
    # Irrelevant-slot beam ties can evict the ranged role's ammunition from a
    # melee/magic beam. Revalidate equivalent sharing on the small finalist set,
    # then offer lower-action variants to every compatible curve point.
    refinement = {"evaluated_assignments": 0, "improved_finalists": 0}
    refined: dict[str, dict[str, Any]] = {}

    def refine(solution: dict[str, Any] | None) -> dict[str, Any] | None:
        if solution is None:
            return None
        from tracker.gear.variant_reporting import materialize

        solution = materialize(solution)
        identity = json.dumps(solution["loadouts"], sort_keys=True)
        if identity not in refined:
            equipped = materialize(refine_magic_staves(search, solution, _solution_key))
            shared = materialize(refine_shared_slots(search, equipped, _solution_key))
            refined[identity] = materialize(
                refine_ammunition(search, shared, _solution_key, refinement)
            )
        return refined[identity]

    refined_winners = []
    for index, solution in enumerate(winners):
        reporter.fraction(index / (len(winners) + 1))
        refined_winners.append(refine(solution))
    winners = refined_winners
    unrestricted = refine(unrestricted)
    unit = 1
    for solution in refined.values():
        if unrestricted is None or _solution_key(solution) < _solution_key(unrestricted):
            unrestricted = solution
        for limit in range(solution["maximum_actions"], request.max_swaps + 1):
            previous = winners[limit]
            if previous is None or _solution_key(solution) < _solution_key(previous):
                winners[limit] = solution
    targeted_diagnostics = None
    if targeted_head_refinement:
        reporter.segment(unit, refinement_units)
        unit += 1
        winners, unrestricted, targeted_diagnostics = refine_omitted_heads(
            search, winners, unrestricted, _solution_key
        )
    local_diagnostics = None
    if local_refinement:
        reporter.segment(unit, refinement_units)
        unit += 1
        winners, unrestricted, local_diagnostics = refine_completed(
            search, winners, unrestricted, _solution_key
        )
    reporter.segment(unit, refinement_units)
    from tracker.gear.variant_reporting import materialize

    # Local refinement may introduce new assignments after the initial cleanup.
    winners = [
        materialize(refine_ammunition(search, materialize(row), _solution_key, refinement))
        if row
        else None
        for row in winners
    ]
    if unrestricted is not None:
        unrestricted = materialize(
            refine_ammunition(search, materialize(unrestricted), _solution_key, refinement)
        )
    secondary_frontiers: list[dict[str, Any]] = []
    refined_at = perf_counter()
    reporter.stage("frontiers", elapsed_seconds=refined_at - started)
    run_secondary = request.secondary_priority != "default"
    run_running = _running_frontier or needs_running_cost_frontier(request, search.eligible)
    frontier_units = int(run_secondary) + int(run_running)
    frontier_diagnostics = None
    if run_secondary:
        from tracker.gear.frontier import explore

        reporter.segment(0, frontier_units)
        secondary_frontiers, frontier_diagnostics, winners, unrestricted = explore(
            search, winners, unrestricted, local_refinement
        )
    from tracker.gear.running_frontier import (
        explore_running_costs,
        running_cost_assumptions,
        running_cost_policy,
    )

    running_frontiers: list[dict[str, Any]] = []
    running_diagnostics = None
    if run_running:
        reporter.segment(frontier_units - 1, frontier_units)
        running_frontiers, running_diagnostics = explore_running_costs(
            search, winners, unrestricted, local_refinement
        )
    frontiers_at = perf_counter()
    reporter.finish()
    winners = [materialize(row) if row is not None else None for row in winners]
    unrestricted = materialize(unrestricted) if unrestricted is not None else None
    baseline = unrestricted["score"] if unrestricted else 0
    curve: list[dict[str, Any]] = [
        {
            "swap_limit": limit,
            "status": "best_found" if solution else "no_feasible_solution_found",
            "solution": solution,
            "relative_performance": solution["score"] / baseline if baseline and solution else None,
        }
        for limit, solution in enumerate(winners)
    ]
    from tracker.gear.attack_reach import policy_context

    assumptions = {
        **policy_context(request),
        "elemental_amulet_model_version": ELEMENTAL_AMULET_MODEL_VERSION,
        "slayer_model_version": SLAYER_MODEL_VERSION,
        "leafy_model_version": LEAFY_MODEL_VERSION,
        "slayer_tasks": {role.id: role.on_slayer_task for role in request.roles},
        "tome_model_version": TOME_MODEL_VERSION,
        "fire_tome_pages": request.fire_tome_pages,
        "bolt_model_version": "enchanted-bolts-v1",
        "aquanite_hopper_model_version": HOPPER_MODEL_VERSION,
        "bolt_diary": {
            "boosted": resolve_bolt_context(request.roles[0], snapshot).bolt_diary_boost,
            "known": resolve_bolt_context(request.roles[0], snapshot).bolt_diary_known,
        },
        "prayer_model_version": PRAYER_MODEL_VERSION,
        "prayer_catalog_revision": PRAYER_CATALOG_REVISION,
        "prayers": {role.id: role.prayers.model_dump(mode="json") for role in request.roles},
        **support_context(catalog, request.support_policy),
        "skills": dict(request.skill_overrides),
        "quests": dict(request.quest_overrides),
        "assumed_item_ids": request.assumed_item_ids,
        "include_untradeables": request.include_untradeables,
        **running_cost_assumptions(request, price_records, local_refinement),
        **(
            {
                "potions": request.potions.model_dump(mode="json"),
                "potion_setup": potion_summary(
                    {k: v.level for k, v in projected.skills.items()},
                    request.potions.selected_ids,
                    price_records,
                    now,
                ),
            }
            if request.potions.mode == "fixed"
            else {}
        ),
    }
    alternatives = _slot_alternatives(search, winners[-1])
    referenced = {
        i
        for solution in [*winners, unrestricted]
        if solution
        for role in solution["loadouts"].values()
        for i in role["equipment"].values()
    }
    referenced |= {
        i
        for group in [*secondary_frontiers, *running_frontiers]
        for point in group["points"]
        for loadout in point["solution"]["loadouts"].values()
        for i in loadout["equipment"].values()
    }
    referenced |= {i for role in request.roles for i in role.locks.values() if i is not None}
    referenced |= {i for i in request.locks.values() if i is not None}
    referenced |= {
        row["item_id"]
        for rows in alternatives.values()
        for row in rows
        if row["item_id"] is not None
    }
    for diagnostics in (targeted_diagnostics, local_diagnostics):
        if diagnostics is None:
            continue
        originals = diagnostics["baseline"]
        referenced |= {
            i
            for solution in [*originals["curve_solutions"], originals["unrestricted"]]
            if solution is not None
            for loadout in solution["loadouts"].values()
            for i in loadout["equipment"].values()
        }
    # Purchase identities can differ from the usable equipment after charging.
    referenced |= {
        market_id
        for i in tuple(referenced)
        if i in facts
        for market_id in [(facts[i].get("preparation") or {}).get("market_item_id")]
        if market_id is not None
    }
    total_weight = sum(r.weight for r in request.roles if r.style != "special")
    return {
        "snapshot_id": snapshot.fingerprint,
        **support_context(catalog, request.support_policy),
        "secondary_priority": request.secondary_priority,
        "evaluated_at": now.isoformat(),
        "catalog_version": getattr(catalog, "revision", "unknown"),
        "model_version": MODEL_VERSION,
        "assumptions": assumptions,
        "assumptions_fingerprint": hashlib.sha256(
            json.dumps(assumptions, sort_keys=True).encode()
        ).hexdigest(),
        "items": [facts[i] for i in sorted(referenced) if i in facts],
        "catalog_summary": {
            "total_items": len(facts),
            "eligible_items": len(search.eligible),
            "browse": "get_gear_candidates catalog=optimizer",
        },
        "active_time_shares": {
            r.id: r.weight / total_weight if total_weight else 0
            for r in request.roles
            if r.style != "special"
        },
        "curve": curve,
        "unrestricted": unrestricted,
        "selected_solution": winners[-1],
        "secondary_frontiers": secondary_frontiers,
        "running_cost_frontiers": running_frontiers,
        "running_cost_policy": running_cost_policy(request, local_refinement),
        "alternatives": alternatives,
        "suggested_swap_limit": next(
            (
                p["swap_limit"]
                for p in curve
                if p["relative_performance"] is not None and p["relative_performance"] >= 0.95
            ),
            None,
        ),
        "search": {
            "quality": "best_found",
            **(
                {
                    "timings_seconds": {
                        "preparation": prepared_at - started,
                        "candidate_ranking": candidates_at - prepared_at,
                        "gear_search": searched_at - candidates_at,
                        "refinement": refined_at - searched_at,
                        "frontiers": frontiers_at - refined_at,
                        "publication": perf_counter() - frontiers_at,
                        "total": perf_counter() - started,
                    }
                }
                if request.potions.mode != "disabled"
                else {}
            ),
            **({"secondary_frontier": frontier_diagnostics} if frontier_diagnostics else {}),
            **({"running_cost_frontier": running_diagnostics} if running_diagnostics else {}),
            **({"local_refinement": local_diagnostics} if local_diagnostics is not None else {}),
            **(
                {"targeted_head_refinement": targeted_diagnostics}
                if targeted_diagnostics is not None
                else {}
            ),
            "ammunition_refinement": refinement,
            "explored_nodes": search.nodes,
            "candidate_truncation": search.truncated,
            "beam_width": BEAM_WIDTH,
            "joint_beam_width": 16,
            "termination_reason": "node_limit"
            if search.nodes >= MAX_EXPANSIONS
            else "bounded_search_complete",
            "candidate_pool_sizes": {s: len(v) for s, v in search.pools.items()},
        },
        "limitations": [
            "Best found within bounded candidates and beams; global optimum is not proven.",
            *dict.fromkeys(
                problem for role in request.roles if (problem := discipline_problem(role))
            ),
            *(
                [
                    "No legal combat configuration satisfied the account and option filters "
                    "within this search."
                ]
                if winners[-1] is None and any(r.combat_options is not None for r in request.roles)
                else []
            ),
            "Secondary priorities order DPS ties; secondary frontiers show best-found "
            "tradeoffs, without a global optimality guarantee.",
            "Active-time weighted DPS excludes movement, survival, supply endurance "
            "and special utility.",
            "Budget uses cached quoted acquisition prices, not guaranteed market fills.",
            *(
                ["Unrestricted score is zero; relative normalization is undefined."]
                if unrestricted and not baseline
                else []
            ),
        ],
    }
