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

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_serializer,
    model_serializer,
    model_validator,
)

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
from tracker.gear.defensive_rolls import raw_player_defence_rolls, required_defensive_skills
from tracker.gear.demonbane import MODEL_VERSION as DEMONBANE_MODEL_VERSION
from tracker.gear.dragonbane import MODEL_VERSION as DRAGONBANE_MODEL_VERSION
from tracker.gear.elemental_amulets import MODEL_VERSION as ELEMENTAL_AMULET_MODEL_VERSION
from tracker.gear.elemental_amulets import applied_spell_bonus
from tracker.gear.evaluation import (
    equipment_problems,
    item_problems,
    loadout_problems,
    purchase_cost,
    purchases,
    resolve_bolt_context,
    resolve_scenario_combat_context,
    unowned_untradeables,
    validate_request_context,
    wilderness_provenance,
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
from tracker.gear.objectives import ObjectiveDescriptor, canonical_objectives, objective_definitions
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
from tracker.gear.ranged_resources import HUNTER_SPEAR
from tracker.gear.refinement import refine_ammunition, refine_magic_staves, refine_shared_slots
from tracker.gear.revenant import FORMS as REVENANT_FORMS
from tracker.gear.revenant_acquisition import (
    copies_available,
    joint_sources,
    loadout_preparations,
    preferred_sources,
)
from tracker.gear.salve import MODEL_VERSION as SALVE_MODEL_VERSION
from tracker.gear.salve import contextual_candidates as salve_candidates
from tracker.gear.scoring import EquipmentScorer, PreparedEquipment
from tracker.gear.slayer import MODEL_VERSION as SLAYER_MODEL_VERSION
from tracker.gear.support import SupportPolicy, project_catalog, support_context
from tracker.gear.targeted_retention import refine_omitted_heads
from tracker.gear.tomes import MODEL_VERSION as TOME_MODEL_VERSION
from tracker.gear.tomes import applied_tome
from tracker.gear.tomes import review as tome_review
from tracker.gear.transitions import inventory_slots, plan_transition
from tracker.gear.vector_archive import own_vector_archives
from tracker.gear.wilderness import WildernessPolicy, WildernessRisk
from tracker.gear.wilderness_ammo import (
    consumes_ammunition,
    idle_ammunition,
    only_ranged_ammunition,
)

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
    _in_wilderness: bool = PrivateAttr(default=False)
    safe_spotting: bool = Field(default=False, strict=True)
    fight_duration_seconds: int = Field(default=60, ge=1, le=3600, strict=True)
    on_slayer_task: bool = Field(default=False, strict=True)
    mark_of_darkness: bool = Field(default=False, strict=True)
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
    wilderness: WildernessPolicy | None = None
    secondary_priority: SecondaryPriority = "default"
    objectives: tuple[ObjectiveDescriptor, ...] | None = None
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
        if self.objectives is not None:
            if self.secondary_priority != "default":
                raise ValueError("objectives cannot be combined with nondefault secondary_priority")
            object.__setattr__(self, "objectives", canonical_objectives(self.objectives))
        if any(goal.kind == "wilderness_loss_gp" for goal in self.objectives or ()):
            if self.wilderness is None:
                raise ValueError("Wilderness loss requires a wilderness policy")
            if self.wilderness.attacks_per_setup is None:
                object.__setattr__(
                    self,
                    "wilderness",
                    self.wilderness.model_copy(
                        update={"attacks_per_setup": self.wilderness.spell_casts or 100}
                    ),
                )
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

    @property
    def purchase_budget(self) -> int | None:
        if (
            self.wilderness is not None
            and self.wilderness.max_loss_gp is None
            and self.wilderness.attacks_per_setup is None
        ):
            return None
        return self.budget_gp

    @property
    def wilderness_risk_limit(self) -> int | None:
        if self.wilderness is None:
            return None
        limit = self.wilderness.max_loss_gp
        return (
            self.budget_gp if limit is None and self.wilderness.attacks_per_setup is None else limit
        )

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
                if source is None or source in REVENANT_FORMS:
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
            if options is not None and staff is not None and source in conversions:
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

    @model_serializer(mode="wrap")
    def serialize_optional_policies(self, handler: Any) -> dict[str, Any]:
        result: dict[str, Any] = handler(self)
        return {
            key: value
            for key, value in result.items()
            if key not in {"objectives", "wilderness"} or value is not None
        }

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
    vector_search: Any
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
        wilderness: WildernessRisk | None = None,
        running_cost_inputs: tuple[Mapping[int, PriceRecord], datetime] | None = None,
    ) -> None:
        # Telemetry only; shared by frontier copies so their work is reported too.
        self.reporter = reporter
        if running_cost_inputs is not None:
            self.running_prices, self.running_at = running_cost_inputs
        request = request.model_copy(
            update={
                "roles": tuple(
                    resolve_scenario_combat_context(resolve_bolt_context(role, snapshot), request)
                    for role in request.roles
                )
            }
        )
        self.snapshot, self.request, self.items, self.facts = snapshot, request, items, facts
        self.wilderness = wilderness
        self.rune_limits_active = (
            wilderness is not None
            and (wilderness.policy.attacks_per_setup or wilderness.policy.spell_casts) is not None
            and any(role.style == "magic" for role in request.roles)
        )
        if self.rune_limits_active:
            from tracker.gear.wilderness_runes import wilderness_spell_runes

            assert wilderness is not None

            @lru_cache(maxsize=2048)
            def rune_bundle(weapon: int, shield: int, spell: str | None) -> dict[int, int] | None:
                return wilderness_spell_runes(
                    {
                        "spell": {
                            slot: item
                            for slot, item in (("weapon", weapon), ("shield", shield))
                            if item
                        }
                    },
                    {"spell": {"attack_type": "magic", "spell": spell}},
                    items,
                    wilderness.policy.attacks_per_setup or wilderness.policy.spell_casts,
                )

            @lru_cache(maxsize=16_384)
            def rune_bound(
                weapon: int, shield: int, spell: str | None, ids: frozenset[int]
            ) -> bool:
                bundle = rune_bundle(weapon, shield, spell)
                return bundle == {} or wilderness.rune_partial_feasible(ids, bundle)

            self._rune_bound = rune_bound
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
            self._ready_copy_check = acquisition_facts.ready_copy_adjustment
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
        # A singleton lower bound can prune before scoring expensive marginals.
        # In the Wilderness the item can be kept, so its purchase price is irrelevant.
        self.eligible = {
            i: item
            for i, item in eligible.items()
            if (wilderness is None or i in wilderness.rules) and self.within_budget({i})
        }
        self.guarded_ammunition = (
            frozenset(i for i, item in self.eligible.items() if only_ranged_ammunition(item))
            if wilderness is not None
            and request.secondary_priority != "ranged_strength_bonus"
            and not any(o.kind == "ranged_strength_bonus" for o in request.objectives or ())
            else frozenset()
        )
        self.ammunition_keepers = frozenset(
            role.id for role in request.roles if "ammunition" in {**request.locks, **role.locks}
        )
        self.ammunition_users = self.ammunition_keepers | {
            role.id for role in request.roles if role.style in {"ranged", "special"}
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

    def within_budget(self, ids: set[int] | frozenset[int], *, complete: bool = False) -> bool:
        if not self.ready_copies_available(ids):
            return False
        purchase_budget = self.request.purchase_budget
        if purchase_budget is not None and self.cost(ids) > purchase_budget:
            return False
        if self.wilderness is None:
            return True
        if complete and not self.rune_limits_active:
            return self.wilderness.feasible(ids)
        return self.wilderness.partial_feasible(ids)

    def feasible_purchase_cost(self, ids: set[int] | frozenset[int]) -> int | None:
        if not self.ready_copies_available(ids):
            return None
        cost = self.cost(ids)
        purchase_budget = self.request.purchase_budget
        if purchase_budget is not None and cost > purchase_budget:
            return None
        if self.wilderness is not None:
            fits = (
                self.wilderness.partial_feasible
                if self.rune_limits_active
                else self.wilderness.feasible
            )
            if not fits(ids):
                return None
        return cost

    def ready_copies_available(self, ids: set[int] | frozenset[int]) -> bool:
        if len(self.request.roles) < 2:
            return True
        if self.compact_states:
            return self._ready_copy_check(frozenset(ids)) is not None
        return copies_available(
            joint_sources(ids, self.facts, self.request), self.facts, self.request
        )

    def slot_budget(
        self,
        rows: tuple[Mapping[str, int], ...],
        ids: set[int] | frozenset[int],
        slot: str,
        *,
        complete: bool,
    ) -> bool:
        if self.wilderness is not None and slot in {"weapon", "shield", "ammunition"}:
            # A synergy seed can contain a head item before its slot is settled.
            ids = {item for row in rows for name, item in row.items() if name != "head"}
        return self.within_budget(ids, complete=complete)

    def budget_item_rank(self, item: int) -> tuple[Any, ...]:
        if self.wilderness is not None:
            return (*self.wilderness.rank_key(item), *self.acquisition_tie({item}), item)
        return (*self.acquisition_tie({item}), item)

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
        """Retain owned or cheaper equipment when combat projections are equal."""
        return self.cost(ids), self.untradeable_acquisitions(ids)

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
                    if option.spell and ancient_spell_problem(
                        weapon,
                        self.snapshot,
                        option.spell,
                        option.stance,
                        self.levels,
                        mark_of_darkness=role.mark_of_darkness,
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
                        weapon,
                        self.snapshot,
                        role.spell,
                        role.stance,
                        self.levels,
                        mark_of_darkness=role.mark_of_darkness,
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
            if "magic" in required_defensive_skills(priority)
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
            role._in_wilderness,
            role.on_slayer_task,
            role.mark_of_darkness,
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
                        option.spell if self.rune_limits_active else None,
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
                    if self.rune_limits_active and not self.rune_option_allowed(
                        equipment, configured, option
                    ):
                        continue
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
            include_defence = self.request.secondary_priority.endswith("_defence_roll")
            native_role = next(
                (
                    index
                    for index, configured in enumerate(self.request.roles)
                    if configured is role
                ),
                None,
            )
            native_score = None
            if self.native_context is not None and native_role is not None:
                try:
                    native_score = self.native_context.score(equipment, native_role)
                except ValueError as exc:
                    # Numeric fixed projections preserve unknown rolls; the
                    # secondary-value consumer raises when it requires them.
                    if not str(exc).startswith("Player defensive roll is unavailable"):
                        raise
                    from tracker.gear.native import NativeSearchUnsupported, required

                    if required():
                        raise NativeSearchUnsupported(
                            "Required defensive levels are missing. Sync the account or enter "
                            "skill overrides."
                        ) from exc
            if self.native_context is not None and native_role is None:
                from tracker.gear.native import NativeSearchUnavailable, required

                if required():
                    raise NativeSearchUnavailable("Native fixed scoring could not bind its role")
            cached = (
                CombatScore(
                    native_score["supported"],
                    native_score["dps"],
                    native_score["accuracy"],
                    prepared.ranged_bonuses if role.style == "ranged" else prepared.bonuses,
                    native_score["player_defence_rolls"]
                    if include_defence and native_score["supported"]
                    else None,
                )
                if native_score is not None
                else evaluate_prepared_score(
                    prepared, role, self.levels, include_defence=include_defence
                )
            )
            if role.style == "magic" and role.powered_attack is None:
                problem = ancient_spell_problem(
                    self.items.get(equipment.get("weapon", -1)),
                    self.snapshot,
                    role.spell,
                    role.stance,
                    self.levels,
                    mark_of_darkness=role.mark_of_darkness,
                )
                if problem:
                    cached = cached._replace(supported=False, dps=None)
            self.compact_cache[key] = cached
        assert isinstance(cached, CombatScore)
        if self.rune_limits_active and not self.rune_option_allowed(equipment, role, None):
            cached = cached._replace(supported=False, dps=None)
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
                        weapon,
                        self.snapshot,
                        role.spell,
                        role.stance,
                        self.levels,
                        mark_of_darkness=role.mark_of_darkness,
                    )
                ):
                    cached = cached._replace(supported=False, dps=None)
                self.compact_cache[score_key] = cached
            assert isinstance(cached, CombatScore)
            score = cached
            if self.rune_limits_active and not self.rune_option_allowed(equipment, role, None):
                score = score._replace(supported=False, dps=None)
            public_option = {
                "attack_type": role.style,
                "stance": role.stance,
                "spell": role.spell if role.style == "magic" else None,
                "powered_attack": role.powered_attack,
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
                        mark_of_darkness=role.mark_of_darkness,
                    )
                    if role.style == "magic" and role.powered_attack is None
                    else None
                )
                if self.rune_limits_active and not self.rune_option_allowed(equipment, role, None):
                    problem = "The configured spell runes cannot fit the Wilderness risk limit."
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
                    "powered_attack": role.powered_attack,
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

    def may_equip_ammunition(
        self, equipment: Mapping[str, int], roles: tuple[RoleConfig, ...]
    ) -> bool:
        if (
            not self.guarded_ammunition
            or equipment.get("ammunition", 0) not in self.guarded_ammunition
        ):
            return True
        if self.ammunition_users.difference(role.id for role in roles):
            return True  # A different loadout may need this stack.
        return any(
            role.id in self.ammunition_keepers
            or consumes_ammunition(equipment, role.style, self.items)
            for role in roles
        )

    def complete_ammunition_allowed(self, loadouts: Mapping[str, Mapping[str, int]]) -> bool:
        if not self.guarded_ammunition:
            return True
        needed: set[int] = set()
        carried: set[int] = set()
        for role in self.request.roles:
            equipment = loadouts[role.id]
            ammo = equipment.get("ammunition", 0)
            if ammo not in self.guarded_ammunition:
                continue
            carried.add(ammo)
            if role.id in self.ammunition_keepers or consumes_ammunition(
                equipment, role.style, self.items
            ):
                needed.add(ammo)
        return needed >= carried

    def trip_report(
        self,
        loadouts: Mapping[str, Mapping[str, int]],
        options: Mapping[str, Mapping[str, Any] | None],
    ) -> dict[str, Any] | None:
        if self.wilderness is None or self.wilderness.policy.attacks_per_setup is None:
            return None
        return self.wilderness.trip_report(
            loadouts, options, self.items, styles={r.id: r.style for r in self.request.roles}
        )

    def trip_fits(self, report: Mapping[str, Any] | None) -> bool:
        if report is None:
            return True
        assert self.wilderness is not None
        return self.wilderness.trip_fits(report)

    def wilderness_report(
        self, loadouts: Mapping[str, Mapping[str, int]], base: str, runes: Mapping[int, int]
    ) -> dict[str, Any]:
        assert self.wilderness is not None
        ordered = {role.id: loadouts[role.id] for role in self.request.roles}
        idle = idle_ammunition(
            ((ordered[role.id], role.style) for role in self.request.roles), self.items
        )
        return self.wilderness.report(ordered, base_role=base, idle_ammunition=idle, runes=runes)

    def rune_option_allowed(
        self, equipment: Mapping[str, int], role: RoleConfig, option: CombatOption | None
    ) -> bool:
        if not self.rune_limits_active or role.style != "magic":
            return True
        powered = option.powered_attack if option is not None else role.powered_attack
        if powered:
            return True
        return self._rune_bound(
            equipment.get("weapon", 0),
            equipment.get("shield", 0),
            option.spell if option is not None else role.spell,
            frozenset(equipment.values()),
        )

    def runes_for_loadouts(
        self,
        loadouts: Mapping[str, Mapping[str, int]],
        options: Mapping[str, Mapping[str, Any] | None],
    ) -> dict[int, int] | None:
        if not self.rune_limits_active:
            return {}
        from tracker.gear.wilderness_runes import wilderness_spell_runes

        assert self.wilderness is not None
        return wilderness_spell_runes(
            loadouts,
            options,
            self.items,
            self.wilderness.policy.attacks_per_setup or self.wilderness.policy.spell_casts,
        )

    def complete_runes_fit(
        self, ids: set[int] | frozenset[int], runes: Mapping[int, int] | None
    ) -> bool:
        return not self.rune_limits_active or (
            self.wilderness is not None and self.wilderness.rune_feasible(ids, runes)
        )

    def rune_alternative_solution(
        self, loadouts: Mapping[str, Mapping[str, int]], limit: int | None
    ) -> dict[str, Any] | None:
        from collections import ChainMap

        if (
            type(self) is not _Search
            or getattr(self, "_rune_options_fixed", False)
            or isinstance(self.option_cache, ChainMap)
        ):
            return None  # A separately scored frontier/refinement must keep its exact attack.
        from tracker.gear.wilderness_spell_selection import wilderness_spell_solution

        return wilderness_spell_solution(self, loadouts, limit)

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
            budget_lanes = [sorted(candidates, key=self.budget_item_rank)]
            if self.wilderness is not None and self.request.purchase_budget is not None:
                budget_lanes.append(
                    sorted(candidates, key=lambda i: (*self.acquisition_tie({i}), i))
                )
            ordered = sorted(locked & set(candidates))
            for row in zip(
                *[lst + [None] * (len(candidates) - len(lst)) for lst in [*budget_lanes, *by_role]],
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
            if slot == "neck":
                retained = list(
                    dict.fromkeys([*retained, *salve_candidates(self.request.roles, self.eligible)])
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
            if slot == "weapon" and any(
                r.target is not None and "demon" in r.target.traits for r in self.request.roles
            ):
                from tracker.gear.demonbane import WEAPON_BONUSES

                retained = list(
                    dict.fromkeys(
                        [*retained, *(i for i in ordered if i in WEAPON_BONUSES or i == 29594)]
                    )
                )
            if slot == "weapon" and any(
                r.target is not None and "dragon" in r.target.traits for r in self.request.roles
            ):
                from tracker.gear.dragonbane import FORMS as DRAGONBANE_FORMS

                retained = list(
                    dict.fromkeys([*retained, *(i for i in ordered if i in DRAGONBANE_FORMS)])
                )
            if slot == "ammunition":
                # Equal-strength dragon bolts have distinct target-dependent procs.
                # Preserve every reviewed effect/form without dropping ordinary candidates.
                retained = list(
                    dict.fromkeys([*retained, *(i for i in ordered if self.items[i].bolt_effect)])
                )
            if slot == "weapon":
                retained = list(
                    dict.fromkeys(
                        [*retained, *(i for i in ordered if self.items[i].size_damage_bonus)]
                    )
                )
            if slot == "shield":
                retained = list(
                    dict.fromkeys([*retained, *(i for i in ordered if self.items[i].tome_effect)])
                )
            if slot == "weapon":
                if self.request.wilderness is not None or any(
                    goal.kind == "gp_per_damage" for goal in self.request.objectives or ()
                ):
                    # Weapon-only rankings can discard the cheaper uncharged attack or
                    # the charged alternative before full gear, cost and risk are scored.
                    revenant_forms = (
                        i
                        for i in ordered
                        if i in REVENANT_FORMS
                        and any(
                            self.marginals[r.id, i] >= 0
                            for r in self.request.roles
                            if r.style != "special"
                        )
                    )
                    retained = list(dict.fromkeys([*retained, *revenant_forms]))
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
            if weapon not in self.eligible or not self.within_budget(
                {weapon} if self.wilderness is not None else set(pair.values())
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
            final_slot = index == len(SLOTS) - 1
            candidates = [i for i in self.pools[slot] if i is not None]
            low_risk = sorted(candidates, key=self.budget_item_rank)[:1] if self.wilderness else []
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
                                *low_risk,
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
                        if not self.slot_budget(
                            equipment_rows, carried_ids, slot, complete=final_slot
                        ):
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
                        candidate = AssignmentState.from_roles(
                            tuple((r.id, e) for r, e in zip(roles, equipment_rows, strict=True))
                        )
                        if slot != "ammunition" or self.complete_ammunition_allowed(candidate):
                            expanded.append(candidate)
                        continue
                    candidate = {
                        r.id: {**state[r.id], **({slot: i} if i is not None else {})}
                        for r, i in zip(roles, assigned, strict=True)
                    }
                    if slot == "ammunition" and not self.complete_ammunition_allowed(candidate):
                        continue
                    carried = (
                        candidate.carried
                        if self.compact_states
                        else {i for equipment in candidate.values() for i in equipment.values()}
                    )
                    if any(i not in self.eligible for i in carried):
                        continue
                    if any(not self.compatible(e) for e in candidate.values()):
                        continue
                    if not self.slot_budget(
                        tuple(candidate.values()), carried, slot, complete=final_slot
                    ):
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

            if index == len(SLOTS) - 1 and hasattr(self, "vector_search"):
                for candidate in expanded:
                    self.vector_search.capture_base(candidate)
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
            complete = index == len(SLOTS) - 1 and len(roles) == len(self.request.roles)
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
                    candidate = state.with_slot(slot, item_id) if item_id is not None else state
                    if self.wilderness is not None:
                        physical_ids = candidate.physical_ids
                    if not self.slot_budget((candidate,), physical_ids, slot, complete=complete):
                        continue
                else:
                    addition: dict[str, int] = {slot: item_id} if item_id is not None else {}
                    candidate = {**state, **addition}
                    if not self.compatible(candidate) or not self.slot_budget(
                        (candidate,), set(candidate.values()), slot, complete=complete
                    ):
                        continue
                # Weapon/ammo legality can be checked once both slots have been assigned.
                if slot == "ammunition" and not self.may_equip_ammunition(candidate, roles):
                    continue
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
                    if all(
                        r.style in {"stab", "slash", "crush"}
                        or (r.style == "ranged" and e.get("weapon") == HUNTER_SPEAR)
                        for r in roles
                    )
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

            if index == len(SLOTS) - 1 and hasattr(self, "vector_search"):
                for candidate in expanded:
                    self.vector_search.capture_base({role.id: candidate for role in roles})
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
        if not self.complete_ammunition_allowed(loadouts):
            return None
        if any(not self.performance(loadouts[r.id], r)["supported"] for r in self.request.roles):
            return None
        for role in self.request.roles:
            equipment = loadouts[role.id]
            if loadout_problems(equipment, self.items, self.facts, self.request, role):
                return None
        carried = {i for equipment in loadouts.values() for i in equipment.values()}
        cost = self.feasible_purchase_cost(carried)
        if cost is None:
            return None
        options = {
            role.id: self.combat_option(loadouts[role.id], role) for role in self.request.roles
        }
        runes = self.runes_for_loadouts(loadouts, options)
        trip = self.trip_report(loadouts, options)
        if not self.trip_fits(trip) or not self.complete_runes_fit(carried, runes):
            return self.rune_alternative_solution(loadouts, limit)
        runes = runes or {}
        reserved = max(self.request.reserved_supply_slots, len(runes))
        capacity = 28 - reserved
        runes_use_extra_slots = reserved > self.request.reserved_supply_slots
        base = self.request.base_role or self.request.roles[0].id
        occupancies = [inventory_slots(e, carried, self.items) for e in loadouts.values()]
        if max(occupancies, default=0) > capacity:
            return (
                self.rune_alternative_solution(loadouts, limit) if runes_use_extra_slots else None
            )
        transitions: list[dict[str, Any]] = []
        for a, b in self.edges:
            transition = self._transition(
                tuple(sorted(loadouts[a].items())),
                tuple(sorted(loadouts[b].items())),
                frozenset(carried),
                capacity,
            )
            if transition is None or (limit is not None and transition["action_count"] > limit):
                return (
                    self.rune_alternative_solution(loadouts, limit)
                    if runes_use_extra_slots
                    else None
                )
            transitions.append({"from_role": a, "to_role": b, **deepcopy(transition)})
        weight = sum(r.weight for r in self.request.roles if r.style != "special")
        score = sum(
            (self.performance(loadouts[r.id], r).get("dps") or 0) * r.weight
            for r in self.request.roles
            if r.style != "special"
        ) / (weight or 1)
        peak = max([*occupancies, *(t["max_gear_inventory_slots"] for t in transitions)], default=0)
        preparations = loadout_preparations(carried, self.facts, self.request)
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
                        preparations[i]
                        for i in sorted(loadouts[r.id].values())
                        if i in preparations
                    ],
                    "discipline": (
                        None
                        if r.style == "special"
                        else "melee"
                        if r.style in {"stab", "slash", "crush"}
                        else r.style
                    ),
                    "performance": self.performance(loadouts[r.id], r),
                    "combat_option": options[r.id],
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
            "remaining_inventory_slots": 28 - peak - reserved,
            "reserved_supply_slots": self.request.reserved_supply_slots,
            "maximum_actions": max((t["action_count"] for t in transitions), default=0),
            "potions": None,
        }
        if self.wilderness is not None:
            result["wilderness_risk"] = trip or self.wilderness_report(loadouts, base, runes)
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


def _objective_winner_key(solution: Mapping[str, Any]) -> tuple[Any, ...]:
    """Rank DPS baselines consistently across vector search and branch merges."""
    values = solution.get("objective_values", {})
    if (
        "wilderness_loss_gp" in values
        or "gp_per_damage" in values
        or any(
            definition["id"] == "gp_per_damage"
            for definition in solution.get("objective_definitions", ())
        )
    ):
        from tracker.gear.vector_archive import resource_tie

        cost = values.get("gp_per_damage")
        remaining = tuple(
            -values[key]
            for key in sorted(values)
            if key not in {"gp_per_damage", "wilderness_loss_gp"}
        )
        return (
            -solution["score"],
            cost is None,
            cost or 0,
            values.get("wilderness_loss_gp", 0),
            remaining,
            resource_tie(solution),
        )
    return _solution_key(solution)


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
    from tracker.gear.variant_reporting import materialize

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
                risk = (
                    {"wilderness_loss_gp": materialize(candidate)["wilderness_risk"]["loss_gp"]}
                    if search.wilderness is not None
                    else {}
                )
                rows.append(
                    {
                        "item_id": item_id,
                        "score": candidate["score"],
                        "score_delta": candidate["score"] - solution["score"],
                        "secondary_value": candidate["secondary_value"],
                        "purchase_cost_gp": candidate["purchase_cost_gp"],
                        **risk,
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
    wilderness: WildernessRisk | None = None


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
            excluded_item_ids=request.excluded_item_ids,
            support_assumptions=getattr(catalog, "community_assumptions", {}).get(i, ()),
        )
        for i, item in catalog.items.items()
    }
    eligible = {
        i: item for i, item in catalog.items.items() if not item_problems(i, facts[i], request)
    }
    risk_limit = request.wilderness_risk_limit
    return PreparedOptimization(
        catalog,
        projected,
        MappingProxyType(facts),
        MappingProxyType(eligible),
        WildernessRisk.build(
            request.wilderness, risk_limit, catalog.items, facts, price_records, now
        )
        if request.wilderness is not None
        else None,
    )


@own_vector_archives
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
    _native_required: bool = False,
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
    if not isinstance(_native_search, bool) or not isinstance(_native_required, bool):
        raise ValueError("Invalid native search option")
    if _native_required and not (
        _native_search and profile == "combined" and _factored_evaluation and _compact_states
    ):
        from tracker.gear.native import NativeSearchUnavailable

        raise NativeSearchUnavailable("Native search requires combined compact execution")
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
    if _native_required:
        execution["_native_required"] = True
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
            native_required=_native_required,
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
        projected,
        request,
        catalog.items,
        facts,
        cancelled,
        prepared.eligible,
        reporter=reporter,
        wilderness=prepared.wilderness,
        running_cost_inputs=(price_records, now),
    )
    request = search.request
    candidates_at = perf_counter()
    reporter.stage("gear_search", elapsed_seconds=candidates_at - started)
    search.complete_frontiers = _complete_frontiers
    vector_search = None
    if request.objectives is not None:
        from tracker.gear.vector_search import VectorSearch

        vector_search = VectorSearch(search, local_refinement)
        search.vector_search = vector_search
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
            complete = role_index == len(request.roles) - 1
            for partial, equipment in product(beam, individual[role.id]):
                if not search.tick():
                    break
                if search.compact_states:
                    carried = partial.carried | equipment.physical_ids
                    if not search.within_budget(carried, complete=complete):
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
                    if not search.within_budget(carried, complete=complete):
                        continue
                    if swap_limit is not None and any(
                        _action_lower_bound(candidate[a], candidate[b], catalog.items) > swap_limit
                        for a, b in search.edges
                        if a in candidate and b in candidate
                    ):
                        continue
                if complete and not search.complete_ammunition_allowed(candidate):
                    continue
                expanded.append(candidate)
            if role_index == len(request.roles) - 1 and vector_search is not None:
                for candidate in expanded:
                    vector_search.capture_base(candidate)
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
    objective_frontiers: list[dict[str, Any]] = []
    objective_diagnostics = None
    refined_at = perf_counter()
    reporter.stage("frontiers", elapsed_seconds=refined_at - started)
    run_secondary = request.secondary_priority != "default"
    from tracker.gear.running_frontier import (
        needs_running_cost_frontier,
        running_cost_assumptions,
        running_cost_policy,
    )

    frontier_units = int(vector_search is not None) + int(run_secondary)
    if vector_search is not None:
        reporter.segment(0, frontier_units)
        vector_result = vector_search.explore([*winners, unrestricted])
        objective_frontiers = vector_result["groups"]
        objective_diagnostics = vector_result["diagnostics"]
        if needs_running_cost_frontier(request):
            winners = [vector_search.baselines[cap] for cap in range(request.max_swaps + 1)]
            unrestricted = vector_search.baselines[None]
        else:
            archive_winners = {
                archive: min(archive.iter_solutions(), key=_objective_winner_key, default=None)
                for archive in dict.fromkeys(vector_search.archives.values())
            }
            winners = [
                archive_winners[vector_search.archives[cap]] for cap in range(request.max_swaps + 1)
            ]
            unrestricted = archive_winners[vector_search.archives[None]]
    secondary_frontiers: list[dict[str, Any]] = []
    frontier_diagnostics = None
    if run_secondary:
        from tracker.gear.frontier import explore

        reporter.segment(int(vector_search is not None), frontier_units)
        secondary_frontiers, frontier_diagnostics, winners, unrestricted = explore(
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
    from tracker.gear.size_damage import MODEL_VERSION as SIZE_DAMAGE_MODEL_VERSION

    assumptions = {
        **policy_context(request),
        **wilderness_provenance(request),
        "elemental_amulet_model_version": ELEMENTAL_AMULET_MODEL_VERSION,
        "slayer_model_version": SLAYER_MODEL_VERSION,
        "salve_model_version": SALVE_MODEL_VERSION,
        "leafy_model_version": LEAFY_MODEL_VERSION,
        "demonbane_model_version": DEMONBANE_MODEL_VERSION,
        "dragonbane_model_version": DRAGONBANE_MODEL_VERSION,
        "size_damage_model_version": SIZE_DAMAGE_MODEL_VERSION,
        "slayer_tasks": {role.id: role.on_slayer_task for role in request.roles},
        "marks_of_darkness": {role.id: role.mark_of_darkness for role in request.roles},
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
        for group in [*secondary_frontiers, *objective_frontiers]
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
        related
        for i in tuple(referenced)
        if i in facts
        for key in ("source_item_id", "market_item_id")
        for related in [(facts[i].get("preparation") or {}).get(key)]
        if related is not None
    }
    # A joint loadout can allocate a different observed copy than the item's
    # stand-alone preparation. Include that sibling's physical metadata.
    referenced.update(
        source
        for i in tuple(referenced)
        if i in REVENANT_FORMS
        for source in preferred_sources(i)
        if source in facts and facts[source]["ownership"]["status"] == "owned"
    )
    total_weight = sum(r.weight for r in request.roles if r.style != "special")
    if request.objectives is not None and not _complete_frontiers:
        from tracker.gear.vector_publish import filter_groups

        objective_frontiers = filter_groups(objective_frontiers, request.max_dps_loss_pct)
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
        **(
            {
                "objective_frontiers": objective_frontiers,
                "objective_definitions": objective_definitions(request.objectives),
            }
            if request.objectives is not None
            else {}
        ),
        "running_cost_frontiers": [],
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
            **({"objective_frontier": objective_diagnostics} if objective_diagnostics else {}),
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
            *(
                ["Budget uses cached quoted acquisition prices, not guaranteed market fills."]
                if request.wilderness is None
                else [
                    "Wilderness risk assumes standard worlds and standard account death rules.",
                    "Extra inventory can increase loss or change which gear is kept.",
                    "Ammo quantities use the more conservative of unit and stack protection.",
                    *(
                        ["Loose spell runes cover the chosen cast count for each Magic setup."]
                        if (request.wilderness.attacks_per_setup or request.wilderness.spell_casts)
                        is not None
                        and any(role.style == "magic" for role in request.roles)
                        else []
                    ),
                    *(
                        [
                            "No feasible setup with a known departure loss was found for this trip."
                            if request.wilderness.attacks_per_setup is not None
                            else "No reviewed loadout was found within the Wilderness risk cap."
                            if request.purchase_budget is None
                            else "No reviewed loadout met the purchase and Wilderness risk caps."
                        ]
                        if winners[-1] is None
                        else []
                    ),
                ]
            ),
            *(
                ["Unrestricted score is zero; relative normalization is undefined."]
                if unrestricted and not baseline
                else []
            ),
        ],
    }
