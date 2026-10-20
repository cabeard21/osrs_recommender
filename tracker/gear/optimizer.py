"""Bounded deterministic equipment search over frozen account/price inputs.

Search quality is always reported as best-found: candidate and beam truncation
cannot establish global optimality or prove that a request is infeasible.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from itertools import product
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.content.schema import ItemSlot
from tracker.estimation.prices import PriceRecord
from tracker.gear.combat import evaluate_loadout
from tracker.gear.facts import equipment_fact, hypothetical_snapshot
from tracker.gear.models import CombatTarget, EquipmentDefinition
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
BEAM_WIDTH = 128
CANDIDATES_PER_SLOT = 12
MAX_EXPANSIONS = 1_000_000
ItemId = Annotated[int, Field(strict=True, gt=0)]


class RoleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    style: Literal["stab", "slash", "crush", "ranged", "magic", "special"]
    stance: Literal["accurate", "aggressive", "controlled", "defensive", "rapid", "longrange"] = (
        "accurate"
    )
    spell: str = Field(default="fire_strike", max_length=40)
    weight: float = Field(default=1, ge=0, le=1_000_000, allow_inf_nan=False)
    target: CombatTarget | None = None
    locks: Mapping[ItemSlot, ItemId | None] = Field(default_factory=dict)
    parent_role: str | None = None

    @model_validator(mode="after")
    def freeze_locks(self) -> RoleConfig:
        object.__setattr__(self, "locks", MappingProxyType(dict(self.locks)))
        return self

    @field_serializer("locks")
    def serialize_locks(self, value: Mapping[str, int | None]) -> dict[str, int | None]:
        return dict(value)


class OptimizationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    roles: tuple[RoleConfig, ...] = Field(min_length=1, max_length=4)
    mode: Literal["owned", "usable", "future"] = "usable"
    budget_gp: int = Field(default=0, ge=0, strict=True)
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
        if any(v is not None and v <= 0 for v in self.locks.values()):
            raise ValueError("locked item IDs must be positive")
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


class _Search:
    def __init__(
        self,
        snapshot: AccountSnapshot,
        request: OptimizationRequest,
        items: Mapping[int, EquipmentDefinition],
        facts: Mapping[int, dict[str, Any]],
        cancelled: Callable[[], bool] | None,
    ) -> None:
        self.snapshot, self.request, self.items, self.facts = snapshot, request, items, facts
        self.levels = {k: v.level for k, v in snapshot.skills.items()}
        self.cancelled = cancelled
        self.nodes = 0
        self.truncated = False
        self.edges = required_transitions(request)
        self.performance_cache: dict[tuple[str, tuple[tuple[str, int], ...]], dict[str, Any]] = {}
        self.eligible = {i: item for i, item in items.items() if self.allowed(i)}
        self.marginals: dict[tuple[str, int], float] = {}
        self.pools = self.candidate_pools()

    def tick(self) -> bool:
        if self.cancelled and self.cancelled():
            raise ValueError("optimization_cancelled")
        if self.nodes >= MAX_EXPANSIONS:
            return False
        self.nodes += 1
        return True

    def allowed(self, item_id: int) -> bool:
        fact = self.facts[item_id]
        if fact["wear"]["status"] != "satisfied":
            return False
        if fact["ownership"]["status"] == "owned":
            return True
        if self.request.mode == "owned":
            return False
        if item_id in self.request.assumed_item_ids:
            return True
        return fact["acquisition"] == "tradeable" and fact["price"]["amount_gp"] is not None

    def cost(self, ids: set[int]) -> int:
        return sum(
            self.facts[i]["price"]["amount_gp"] or 0
            for i in ids
            if self.facts[i]["ownership"]["status"] != "owned"
            and i not in self.request.assumed_item_ids
        )

    def performance(self, equipment: Mapping[str, int], role: RoleConfig) -> dict[str, Any]:
        key = (role.id, tuple(sorted(equipment.items())))
        if key not in self.performance_cache:
            if role.style == "special":
                result: dict[str, Any] = {
                    "supported": True,
                    "dps": None,
                    "limitations": [
                        "Special role is unscored; no damage or utility benefit assumed."
                    ],
                }
            else:
                result = evaluate_loadout(
                    {s: self.items[i] for s, i in equipment.items()}, role, self.levels, role.target
                ).model_dump(mode="json")
            self.performance_cache[key] = result
        return self.performance_cache[key]

    def compatible(self, equipment: Mapping[str, int]) -> bool:
        weapon = self.items.get(equipment.get("weapon", -1))
        return not (weapon and weapon.two_handed and "shield" in equipment)

    def candidate_pools(self) -> dict[str, list[int | None]]:
        locked = {v for r in self.request.roles for v in r.locks.values() if v is not None}
        locked |= {v for v in self.request.locks.values() if v is not None}
        pools: dict[str, list[int | None]] = {}
        baselines = {r.id: self.baselines(r) for r in self.request.roles}
        for slot in SLOTS:
            candidates = [i for i, item in self.eligible.items() if item.slot == slot]
            # Compare actual model DPS against legal weapon/ammunition scaffolds;
            # never invent weighted bonus desirability scores.
            by_role: list[list[int]] = []
            for role in self.request.roles:

                def marginal(i: int, role: RoleConfig = role, slot: str = slot) -> float:
                    scores = []
                    for base in baselines[role.id]:
                        equipment = {**base, slot: i}
                        if self.compatible(equipment):
                            performance = self.performance(equipment, role)
                            if performance["supported"]:
                                scores.append(performance.get("dps") or 0)
                    value = max(scores, default=-1)
                    self.marginals[role.id, i] = value
                    return value

                by_role.append(sorted(candidates, key=lambda i: (-marginal(i), i)))
            cheap = sorted(candidates, key=lambda i: (self.cost({i}), i))
            ordered = sorted(locked & set(candidates))
            for row in zip(
                *[lst + [None] * (len(candidates) - len(lst)) for lst in [cheap, *by_role]],
                strict=False,
            ):
                ordered.extend(i for i in row if i is not None and i not in ordered)
            keep = max(CANDIDATES_PER_SLOT - 1, len(locked & set(candidates)))
            self.truncated |= len(ordered) > keep
            pools[slot] = [None, *ordered[:keep]]
        return pools

    def baselines(self, role: RoleConfig) -> list[dict[str, int]]:
        """Legal ordinary-attack scaffolds for model-based candidate selection."""
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
        return [b for b in bases if self.performance(b, role)["supported"]]

    def joint_loadouts(self, limit: int | None) -> list[dict[str, dict[str, int]]]:
        """Assign each slot jointly, retaining shared choices before role beams lose them.

        Actual baseline DPS comparisons select branches; final complete DPS remains
        the only scoring objective. Width/branch caps keep the search bounded.
        """
        roles = self.request.roles
        beam: list[dict[str, dict[str, int]]] = [{r.id: {} for r in roles}]
        for slot in SLOTS:
            candidates = [i for i in self.pools[slot] if i is not None]
            common = sorted(
                candidates,
                key=lambda i: (
                    -sum(self.marginals.get((r.id, i), -1) * r.weight for r in roles),
                    i,
                ),
            )[:1]
            choices = []
            for role in roles:
                locks = {**self.request.locks, **role.locks}
                ranked = sorted(
                    candidates, key=lambda i: (-self.marginals.get((role.id, i), -1), i)
                )
                options = (
                    [locks[slot]]
                    if slot in locks
                    else list(dict.fromkeys([None, *ranked[:2], *common]))
                )
                choices.append(options)
            expanded = []
            for state in beam:
                for assigned in product(*choices):
                    if not self.tick():
                        break
                    candidate = {
                        r.id: {**state[r.id], **({slot: i} if i is not None else {})}
                        for r, i in zip(roles, assigned, strict=True)
                    }
                    carried = {i for equipment in candidate.values() for i in equipment.values()}
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
                        not self.performance(candidate[r.id], r)["supported"] for r in roles
                    ):
                        continue
                    expanded.append(candidate)

            def rank(c: dict[str, dict[str, int]]) -> tuple[Any, ...]:
                # Model-derived branch ordering; full joint solutions below are
                # always compared using their complete calculated encounter score.
                score = sum(
                    self.marginals.get((r.id, i), 0) * r.weight
                    for r in roles
                    for i in c[r.id].values()
                )
                union = {i for e in c.values() for i in e.values()}
                return (-score, len(union), self.cost(union), json.dumps(c, sort_keys=True))

            beam = sorted(expanded, key=rank)[:16]
            if not beam:
                break
        return beam if beam and all(len(e) <= len(SLOTS) for e in beam[0].values()) else []

    def loadouts(self, roles: tuple[RoleConfig, ...]) -> list[dict[str, int]]:
        """Assign common equipment when several roles are passed (zero-action seed)."""
        locks = dict[str, int | None](self.request.locks.items())
        for role in roles:
            for slot, item_id in role.locks.items():
                if slot in locks and locks[slot] != item_id:
                    return []
                locks[slot] = item_id
        states: list[dict[str, int]] = [{}]
        for slot in SLOTS:
            choices = [locks[slot]] if slot in locks else self.pools[slot]
            expanded: list[dict[str, int]] = []
            for state, item_id in product(states, choices):
                if not self.tick():
                    break
                if item_id is not None and (
                    item_id not in self.eligible or self.items[item_id].slot != slot
                ):
                    continue
                addition: dict[str, int] = {slot: item_id} if item_id is not None else {}
                candidate = {**state, **addition}
                if (
                    not self.compatible(candidate)
                    or self.cost(set(candidate.values())) > self.request.budget_gp
                ):
                    continue
                # Weapon/ammo legality can be checked once both slots have been assigned.
                if slot not in ("weapon", "shield") and any(
                    not self.performance(candidate, r)["supported"] for r in roles
                ):
                    continue
                expanded.append(candidate)

            def rank(e: dict[str, int]) -> tuple[Any, ...]:
                score = sum((self.performance(e, r).get("dps") or 0) * r.weight for r in roles)
                # Exact partial-DPS ties can hide a later max-hit breakpoint.
                # Preserve melee strength before arbitrary item IDs; complete DPS
                # remains the first key and the final solution's only damage score.
                strength = (
                    sum(self.items[i].bonuses.melee_strength for i in e.values())
                    if all(r.style in {"stab", "slash", "crush"} for r in roles)
                    else 0
                )
                return (-score, self.cost(set(e.values())), -strength, tuple(sorted(e.items())))

            states = sorted(expanded, key=rank)[:BEAM_WIDTH]
            if not states:
                return []
        return [s for s in states if all(self.performance(s, r)["supported"] for r in roles)]

    def solution(
        self, loadouts: Mapping[str, dict[str, int]], limit: int | None
    ) -> dict[str, Any] | None:
        if any(not self.performance(loadouts[r.id], r)["supported"] for r in self.request.roles):
            return None
        for role in self.request.roles:
            equipment = loadouts[role.id]
            locks = {**self.request.locks, **role.locks}
            if any(equipment.get(slot) != item_id for slot, item_id in locks.items()):
                return None
            if not self.compatible(equipment) or any(
                i not in self.eligible or self.items[i].slot != slot
                for slot, i in equipment.items()
            ):
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
            transition = plan_transition(
                loadouts[a], loadouts[b], self.items, carried=carried, capacity=capacity
            )
            if transition is None or (limit is not None and transition["action_count"] > limit):
                return None
            transitions.append({"from_role": a, "to_role": b, **transition})
        weight = sum(r.weight for r in self.request.roles if r.style != "special")
        score = sum(
            (self.performance(loadouts[r.id], r).get("dps") or 0) * r.weight
            for r in self.request.roles
            if r.style != "special"
        ) / (weight or 1)
        peak = max([*occupancies, *(t["max_gear_inventory_slots"] for t in transitions)], default=0)
        return {
            "score": score,
            "loadouts": {
                r.id: {
                    "equipment": loadouts[r.id],
                    "performance": self.performance(loadouts[r.id], r),
                }
                for r in self.request.roles
            },
            "transitions": transitions,
            "purchase_cost_gp": cost,
            "purchases": [
                {
                    "item_id": i,
                    "cost_gp": self.facts[i]["price"]["amount_gp"],
                    "conditional": self.facts[i]["ownership"]["status"] == "unknown",
                }
                for i in sorted(carried)
                if self.facts[i]["ownership"]["status"] != "owned"
                and i not in self.request.assumed_item_ids
            ],
            "carried_item_ids": sorted(carried),
            "distinct_items": len(carried),
            "gear_inventory_slots": inventory_slots(loadouts[base], carried, self.items),
            "max_gear_inventory_slots": peak,
            "remaining_supply_slots": 28 - peak,
            "remaining_inventory_slots": 28 - peak - self.request.reserved_supply_slots,
            "reserved_supply_slots": self.request.reserved_supply_slots,
            "maximum_actions": max((t["action_count"] for t in transitions), default=0),
        }


def _solution_key(solution: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -solution["score"],
        solution["max_gear_inventory_slots"],
        solution["purchase_cost_gp"],
        sum(t["action_count"] for t in solution["transitions"]),
        json.dumps(solution["loadouts"], sort_keys=True),
    )


def _action_lower_bound(
    source: Mapping[str, int],
    destination: Mapping[str, int],
    items: Mapping[int, EquipmentDefinition],
) -> int:
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
                        "purchase_cost_gp": candidate["purchase_cost_gp"],
                    }
                )
        alternatives[slot] = sorted(
            rows, key=lambda r: (-r["score"], r["purchase_cost_gp"], r["item_id"] or 0)
        )[:5]
    return alternatives


def optimize(
    snapshot: AccountSnapshot,
    request: OptimizationRequest | Mapping[str, Any],
    catalog: Any,
    content: Content,
    price_records: Mapping[int, PriceRecord],
    now: datetime,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Return a complete frozen-context curve; never persist recommendations."""
    request = (
        request
        if isinstance(request, OptimizationRequest)
        else OptimizationRequest.model_validate(request)
    )
    if request.expected_snapshot_id and request.expected_snapshot_id != snapshot.fingerprint:
        raise ValueError("snapshot_changed: retrieve current account facts")
    if any(k not in content.skills for k in request.skill_overrides):
        raise ValueError("unknown skill assumption")
    if any(k not in content.quests for k in request.quest_overrides):
        raise ValueError("unknown quest assumption")
    for role in request.roles:
        for slot, item_id in {**request.locks, **role.locks}.items():
            if item_id is not None and item_id not in catalog.items:
                raise ValueError(f"unknown locked item ID: {item_id}")
            if item_id is not None and catalog.items[item_id].slot != slot:
                raise ValueError(f"locked item {item_id} does not occupy {slot}")
    projected = hypothetical_snapshot(
        snapshot, request.skill_overrides, request.quest_overrides, now
    )
    facts = {
        i: equipment_fact(projected, item, content, price_records, now)
        for i, item in catalog.items.items()
    }
    search = _Search(projected, request, catalog.items, facts, cancelled)
    individual = {role.id: search.loadouts((role,)) for role in request.roles}
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
                individual[role.id].append(seeded)
    # Direct common-equipment search avoids losing the zero-swap setup in independent
    # role beams. More complex disconnected graphs are explored by the joint beam.
    common = search.loadouts(request.roles)
    tuples: list[dict[str, dict[str, int]]] = [
        {role.id: equipment for role in request.roles} for equipment in common
    ]
    if len(request.roles) > 1:
        # Joint per-slot search comes first so independent tuple expansion cannot
        # consume the deterministic node budget before shared gear is explored.
        for swap_limit in [*range(request.max_swaps + 1), None]:
            tuples.extend(search.joint_loadouts(swap_limit))

    def partial_rank(c: dict[str, dict[str, int]]) -> tuple[Any, ...]:
        score = sum(
            (search.performance(c[r.id], r).get("dps") or 0) * r.weight
            for r in request.roles
            if r.id in c
        )
        return (
            -score,
            len({i for e in c.values() for i in e.values()}),
            json.dumps(c, sort_keys=True),
        )

    # Search each constraint separately. A high-scoring unrestricted beam must not
    # evict all feasible low-action tuples before the action limit is considered.
    for swap_limit in [*range(request.max_swaps + 1), None]:
        beam: list[dict[str, dict[str, int]]] = [{}]
        for role in request.roles:
            expanded = []
            for partial, equipment in product(beam, individual[role.id]):
                if not search.tick():
                    break
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
        tuples.extend(beam)
    unrestricted = None
    winners: list[dict[str, Any] | None] = [None] * (request.max_swaps + 1)
    unique_tuples = {json.dumps(e, sort_keys=True): e for e in tuples}
    for loadouts in unique_tuples.values():
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
    assumptions = {
        "skills": dict(request.skill_overrides),
        "quests": dict(request.quest_overrides),
        "assumed_item_ids": request.assumed_item_ids,
    }
    alternatives = _slot_alternatives(search, winners[-1])
    referenced = {
        i
        for solution in [*winners, unrestricted]
        if solution
        for role in solution["loadouts"].values()
        for i in role["equipment"].values()
    }
    referenced |= {i for role in request.roles for i in role.locks.values() if i is not None}
    referenced |= {i for i in request.locks.values() if i is not None}
    referenced |= {
        row["item_id"]
        for rows in alternatives.values()
        for row in rows
        if row["item_id"] is not None
    }
    total_weight = sum(r.weight for r in request.roles if r.style != "special")
    return {
        "snapshot_id": snapshot.fingerprint,
        "evaluated_at": now.isoformat(),
        "catalog_version": getattr(catalog, "revision", "unknown"),
        "model_version": "normal-attacks-v1",
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
