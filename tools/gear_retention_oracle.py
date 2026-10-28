"""Finite-catalog reference enumeration; no optimizer search or pruning is reused.

Combat, access facts and public request types are shared. Enumeration, union cost,
transition graph, locks, capacity and score aggregation are independently checked.
This is a research tool, never an application optimizer backend.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from heapq import heappop, heappush
from itertools import product
from math import isclose
from types import MappingProxyType
from typing import Any

from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.estimation.prices import PriceRecord
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.evaluation import evaluate_equipment, item_problems
from tracker.gear.facts import equipment_fact, hypothetical_snapshot
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig
from tracker.integrations.prices.client import PriceDTO, PriceSource

AT = datetime(2026, 10, 19, 22, 5, 44, tzinfo=UTC)


@dataclass(frozen=True)
class Case:
    name: str
    snapshot: AccountSnapshot
    request: OptimizationRequest
    catalog: EquipmentCatalog
    content: Content
    prices: Mapping[int, PriceRecord]
    at: datetime = AT


def transition_metrics(source, destination, items, carried, capacity):
    """Enumerate all carried equip/unequip actions; shortest path, then lowest peak."""
    start, goal = tuple(sorted(source.items())), tuple(sorted(destination.items()))
    occupancy = len(carried - set(source.values()))
    if occupancy > capacity:
        return None
    queue = [(0, occupancy, start)]
    seen = {start: (0, occupancy)}
    while queue:
        distance, peak, state = heappop(queue)
        if seen[state] != (distance, peak):
            continue
        if state == goal:
            return distance, peak
        equipment = dict(state)
        operations = [(slot, None) for slot in sorted(equipment)]
        operations += [(items[i].slot, i) for i in sorted(carried)]
        for slot, item_id in operations:
            updated = {s: i for s, i in equipment.items() if s != slot}
            if item_id is not None:
                if items[item_id].two_handed and slot == "weapon":
                    updated = {s: i for s, i in updated.items() if s != "shield"}
                if slot == "shield" and "weapon" in updated and items[updated["weapon"]].two_handed:
                    updated = {s: i for s, i in updated.items() if s != "weapon"}
                updated = {**updated, slot: item_id}
            occupied = len(carried - set(updated.values()))
            key = tuple(sorted(updated.items()))
            metric = (distance + 1, max(peak, occupied))
            if occupied <= capacity and (key not in seen or metric < seen[key]):
                seen[key] = metric
                heappush(queue, (*metric, key))
    return None


def _edges(request):
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
            for r in request.roles
            if r.id != base and r.style != "special"
            for a, b in ((base, r.id), (r.id, base))
        ]
    edges += [
        (a, b)
        for r in request.roles
        if r.style == "special" and r.id not in request.ordered_roles
        for a, b in ((r.parent_role, r.id), (r.id, r.parent_role))
    ]
    return tuple(dict.fromkeys((a, b) for a, b in edges if a != b))


def _role_loadouts(case, role, eligible):
    items = case.catalog.items
    locks = {**case.request.locks, **role.locks}
    slots = sorted({i.slot for i in items.values()} | set(locks))
    choices = [
        ([locks[s]] if s in locks else [None, *sorted(i for i in eligible if items[i].slot == s)])
        for s in slots
    ]
    levels = {k: v.level for k, v in case.snapshot.skills.items()}
    loadouts = []
    evaluations = 0
    for assignment in product(*choices):
        equipment = {s: i for s, i in zip(slots, assignment, strict=True) if i is not None}
        if any(i not in eligible or items[i].slot != s for s, i in equipment.items()):
            continue
        weapon = items.get(equipment.get("weapon"))
        if weapon and weapon.two_handed and "shield" in equipment:
            continue
        evaluations += role.style != "special"
        performance = (
            evaluate_equipment(equipment, items, role, levels).model_dump(mode="json")
            if role.style != "special"
            else {"supported": True, "dps": None, "max_hit": None}
        )
        if performance["supported"]:
            loadouts.append((equipment, performance))
    return loadouts, evaluations


def _key(row):
    return (
        -row["score"],
        row["max_gear_inventory_slots"],
        row["purchase_cost_gp"],
        row["total_actions"],
        json.dumps(row["loadouts"], sort_keys=True),
    )


def exhaustive(case: Case) -> dict[str, Any]:
    """Prove fixture optima, not realistic-catalog optimality. No bounded search calls."""
    case = replace(
        case,
        snapshot=hypothetical_snapshot(
            case.snapshot, case.request.skill_overrides, case.request.quest_overrides, case.at
        ),
    )
    request, items = case.request, case.catalog.items
    facts = {
        i: equipment_fact(case.snapshot, item, case.content, case.prices, case.at)
        for i, item in items.items()
    }
    eligible = {i for i, fact in facts.items() if not item_problems(i, fact, request)}
    generated = [_role_loadouts(case, r, eligible) for r in request.roles]
    role_options = [options for options, _ in generated]
    capacity = 28 - request.reserved_supply_slots
    weight = sum(r.weight for r in request.roles if r.style != "special")
    winners: list[dict[str, Any] | None] = [None] * (request.max_swaps + 1)
    unrestricted = None
    assignments = 0
    cache = {}
    for assigned in product(*role_options):
        assignments += 1
        loadouts = {r.id: e for r, (e, _) in zip(request.roles, assigned, strict=True)}
        union = {i for e in loadouts.values() for i in e.values()}
        purchases = (
            union
            - {i for i in union if facts[i]["ownership"]["status"] == "owned"}
            - set(request.assumed_item_ids)
        )
        cost = sum(facts[i]["price"]["amount_gp"] for i in purchases)
        occupancy = max(len(union - set(e.values())) for e in loadouts.values())
        if cost > request.budget_gp or occupancy > capacity:
            continue
        transitions = []
        for a, b in _edges(request):
            key = (
                tuple(sorted(loadouts[a].items())),
                tuple(sorted(loadouts[b].items())),
                tuple(sorted(union)),
                capacity,
            )
            if key not in cache:
                cache[key] = transition_metrics(loadouts[a], loadouts[b], items, union, capacity)
            transitions.append(cache[key])
        if any(t is None for t in transitions):
            continue
        actions = max((t[0] for t in transitions), default=0)
        peak = max([occupancy, *(t[1] for t in transitions)])
        row = {
            "score": sum(
                (p.get("dps") or 0) * r.weight
                for r, (_, p) in zip(request.roles, assigned, strict=True)
                if r.style != "special"
            )
            / weight,
            "loadouts": loadouts,
            "max_hits": {
                r.id: p["max_hit"] for r, (_, p) in zip(request.roles, assigned, strict=True)
            },
            "dps": {r.id: p["dps"] for r, (_, p) in zip(request.roles, assigned, strict=True)},
            "purchase_cost_gp": cost,
            "purchased_item_ids": sorted(purchases),
            "carried_item_ids": sorted(union),
            "maximum_actions": actions,
            "max_gear_inventory_slots": peak,
            "total_actions": sum(t[0] for t in transitions),
        }
        if unrestricted is None or _key(row) < _key(unrestricted):
            unrestricted = row
        for limit in range(actions, request.max_swaps + 1):
            if winners[limit] is None or _key(row) < _key(winners[limit]):
                winners[limit] = row
    return {
        "curve": [{"swap_limit": n, **(row or {"score": None})} for n, row in enumerate(winners)],
        "unrestricted": unrestricted,
        "assignments": assignments,
        "evaluations": sum(count for _, count in generated),
    }


def validate_solution(case: Case, solution: dict[str, Any]) -> dict[str, Any]:
    """Independently check a reported complete solution, without running enumeration.

    Minimum transition metrics are returned separately from reported path metrics.
    A supplied path is replayed so a different valid shortest-path peak is accepted.
    """
    errors: list[str] = []
    case = replace(
        case,
        snapshot=hypothetical_snapshot(
            case.snapshot, case.request.skill_overrides, case.request.quest_overrides, case.at
        ),
    )
    request, items = case.request, case.catalog.items
    levels = {k: v.level for k, v in case.snapshot.skills.items()}
    facts = {
        i: equipment_fact(case.snapshot, item, case.content, case.prices, case.at)
        for i, item in items.items()
    }
    loadouts = {r.id: solution["loadouts"][r.id]["equipment"] for r in request.roles}
    union = {i for e in loadouts.values() for i in e.values()}
    capacity = 28 - request.reserved_supply_slots
    scores = []
    for role in request.roles:
        equipment = loadouts[role.id]
        if any(i not in items or items[i].slot != s for s, i in equipment.items()):
            return {"valid": False, "errors": ["invalid physical slot"], "metrics": {}}
        for s, i in {**request.locks, **role.locks}.items():
            if equipment.get(s) != i:
                errors.append(f"{role.id}: lock violation")
        if any(item_problems(i, facts[i], request) for i in equipment.values()):
            errors.append(f"{role.id}: access violation")
        if role.style == "special":
            continue
        exact = evaluate_equipment(equipment, items, role, levels)
        if not exact.supported:
            errors.append(f"{role.id}: unsupported")
        scores.append((exact.dps or 0) * role.weight)
        for key in ("dps", "max_hit", "accuracy", "attack_interval"):
            reported, actual = (
                solution["loadouts"][role.id]["performance"].get(key),
                getattr(exact, key),
            )
            if reported is None or actual is None or not isclose(reported, actual, abs_tol=1e-12):
                errors.append(f"{role.id}: incorrect {key}")
    purchased = (
        union
        - {i for i in union if facts[i]["ownership"]["status"] == "owned"}
        - set(request.assumed_item_ids)
    )
    if any(facts[i]["price"]["amount_gp"] is None for i in purchased):
        errors.append("unknown purchase cost")
    cost = sum(facts[i]["price"]["amount_gp"] or 0 for i in purchased)
    peak = max(len(union - set(e.values())) for e in loadouts.values())
    metrics = [
        transition_metrics(loadouts[a], loadouts[b], items, union, capacity)
        for a, b in _edges(request)
    ]
    if any(m is None for m in metrics):
        errors.append("transition infeasible")
    actions = max((m[0] for m in metrics if m is not None), default=0)
    peak = max([peak, *(m[1] for m in metrics if m is not None)])
    score = sum(scores) / sum(r.weight for r in request.roles if r.style != "special")
    if cost > request.budget_gp or peak > capacity:
        errors.append("budget or capacity violation")
    if solution["purchase_cost_gp"] != cost:
        errors.append("incorrect purchase union cost")
    if sorted(solution["carried_item_ids"]) != sorted(union):
        errors.append("incorrect carried union")
    if {p["item_id"] for p in solution["purchases"]} != purchased:
        errors.append("incorrect purchase IDs")
    elif sorted(solution["purchases"], key=lambda p: p["item_id"]) != [
        {
            "item_id": i,
            "cost_gp": facts[i]["price"]["amount_gp"],
            "conditional": facts[i]["ownership"]["status"] == "unknown",
        }
        for i in sorted(purchased)
    ]:
        errors.append("incorrect purchase facts")
    if not isclose(solution["score"], score, abs_tol=1e-12):
        errors.append("incorrect weighted score")
    reported_edges = {(t["from_role"], t["to_role"]) for t in solution["transitions"]}
    if reported_edges != set(_edges(request)):
        errors.append("incorrect transition edges")
    reported_peak = max(len(union - set(e.values())) for e in loadouts.values())
    reported_actions = 0
    for t in solution["transitions"]:
        equipment = dict(loadouts[t["from_role"]])
        path_peak = len(union - set(equipment.values()))
        for action in t["actions"]:
            slot, i = action["slot"], action["item_id"]
            if action["operation"] == "unequip":
                if equipment.get(slot) != i:
                    errors.append("invalid unequip")
                equipment = {s: v for s, v in equipment.items() if s != slot}
            elif action["operation"] == "equip" and i in union and items[i].slot == slot:
                if slot == "weapon" and items[i].two_handed:
                    equipment = {s: v for s, v in equipment.items() if s != "shield"}
                if (
                    slot == "shield"
                    and "weapon" in equipment
                    and items[equipment["weapon"]].two_handed
                ):
                    equipment = {s: v for s, v in equipment.items() if s != "weapon"}
                equipment = {**equipment, slot: i}
            else:
                errors.append("invalid equip")
            path_peak = max(path_peak, len(union - set(equipment.values())))
        if equipment != loadouts[t["to_role"]] or path_peak > capacity:
            errors.append("invalid transition endpoint or transient capacity")
        if len(t["actions"]) != t["action_count"] or path_peak != t["max_gear_inventory_slots"]:
            errors.append("incorrect transition path metrics")
        reported_peak = max(reported_peak, path_peak)
        reported_actions = max(reported_actions, len(t["actions"]))
    base = request.base_role or request.roles[0].id
    expected_facts = {
        "maximum_actions": reported_actions,
        "max_gear_inventory_slots": reported_peak,
        "gear_inventory_slots": len(union - set(loadouts[base].values())),
        "remaining_supply_slots": 28 - reported_peak,
        "remaining_inventory_slots": 28 - reported_peak - request.reserved_supply_slots,
        "reserved_supply_slots": request.reserved_supply_slots,
        "distinct_items": len(union),
    }
    for key, expected in expected_facts.items():
        if solution[key] != expected:
            errors.append(f"incorrect {key}")
    return {
        "valid": not errors,
        "errors": errors,
        "metrics": {
            "score": score,
            "purchase_cost_gp": cost,
            "maximum_actions": actions,
            "max_gear_inventory_slots": peak,
        },
    }


def _item(i, slot="head", **kwargs):
    return EquipmentDefinition(id=i, name=str(i), slot=slot, requirements_complete=True, **kwargs)


def _case(name, items, roles, *, owned=None, costs=None, **request_options):
    ids = {i.id for i in items} if owned is None else set(owned)
    snapshot = AccountSnapshot(
        1,
        "fixture",
        skills={
            k: SkillState(70, None, Source.MANUAL, AT)
            for k in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "fixture", AT) for i in ids
        },
        container_scans={c: ContainerScanFact(c, AT, "fixture") for c in Container},
    )
    prices = {
        i: PriceDTO(i, gp, AT, gp, AT, "fixture", AT, PriceSource.CACHED)
        for i, gp in (costs or {}).items()
    }
    return Case(
        name,
        snapshot,
        OptimizationRequest(roles=roles, mode="usable" if costs else "owned", **request_options),
        EquipmentCatalog({i.id: i for i in items}),
        Content(),
        MappingProxyType(prices),
    )


def tiny_cases() -> list[Case]:
    """Named fixtures are deliberately small enough for complete joint enumeration."""
    melee = _item(100, "weapon", attack_styles=("slash",))
    ranged = _item(101, "weapon", attack_styles=("ranged",))
    heads = [
        _item(10, tradeable=True, bonuses=EquipmentBonuses(melee_strength=20, ranged_strength=20)),
        _item(11, tradeable=True, bonuses=EquipmentBonuses(melee_strength=30)),
        _item(12, tradeable=True, bonuses=EquipmentBonuses(ranged_strength=30)),
    ]
    roles = (
        RoleConfig(id="m", style="slash", locks={"weapon": 100}),
        RoleConfig(id="r", style="ranged", locks={"weapon": 101}),
    )
    cases = [
        _case(
            "breakpoint",
            [
                melee,
                *[
                    _item(i, bonuses=EquipmentBonuses(melee_strength=3 if i == 12 else 0))
                    for i in range(1, 13)
                ],
                _item(20, "cape", bonuses=EquipmentBonuses(melee_strength=3)),
            ],
            (RoleConfig(id="slash", style="slash", locks={"weapon": 100}),),
            max_swaps=0,
        )
    ]
    cases += [
        _case("joint_shared", [melee, ranged, *heads], roles, max_swaps=2),
        _case(
            "budget_union",
            [melee, ranged, *heads],
            roles,
            max_swaps=2,
            owned=(100, 101),
            costs={10: 100, 11: 80, 12: 80},
            budget_gp=100,
        ),
        _case(
            "identity_lock",
            [melee, ranged, *heads],
            (roles[0].model_copy(update={"locks": {"weapon": 100, "head": 10}}), roles[1]),
            max_swaps=1,
        ),
        _case(
            "exclusion_empty",
            [melee, ranged, *heads],
            roles,
            max_swaps=2,
            locks={"head": None},
            excluded_item_ids=(12,),
        ),
    ]
    hand_roles = (
        RoleConfig(id="a", style="slash", locks={"weapon": 100, "shield": None}),
        RoleConfig(id="b", style="slash", locks={"weapon": 101, "shield": 30}),
    )
    hand_items = [
        melee.model_copy(update={"two_handed": True}),
        _item(101, "weapon", attack_styles=("slash",)),
        _item(30, "shield"),
    ]
    cases += [
        _case("hands", hand_items, hand_roles, max_swaps=3, reserved_supply_slots=26),
        _case("hands_capacity", hand_items, hand_roles, max_swaps=3, reserved_supply_slots=27),
    ]
    mixed_heads = [
        _item(10, bonuses=EquipmentBonuses(ranged=30, magic=-10)),
        _item(11, bonuses=EquipmentBonuses(ranged_strength=8, magic_damage=10)),
        _item(12, bonuses=EquipmentBonuses(magic=30, defence_magic=10)),
    ]
    cases += [
        _case(
            "ranged_magic",
            [ranged, *mixed_heads],
            (roles[1], RoleConfig(id="mage", style="magic", weight=2, locks={"weapon": None})),
            max_swaps=3,
        )
    ]
    for count in (3, 4):
        group = tuple(
            RoleConfig(
                id=f"r{n}", style="slash", weight=0 if n == 1 else n + 1, locks={"weapon": 100}
            )
            for n in range(count)
        )
        cases.append(
            _case(
                f"roles_{count}",
                [melee, *heads],
                group,
                max_swaps=1,
                ordered_roles=tuple(r.id for r in group),
                loop=True,
            )
        )
    cases.append(
        _case(
            "special",
            [melee, _item(101, "weapon", attack_styles=("slash",)), *heads],
            (
                RoleConfig(id="m", style="slash", locks={"weapon": 100}),
                RoleConfig(id="utility", style="special", parent_role="m", locks={"weapon": 101}),
            ),
            max_swaps=2,
        )
    )
    cases.append(
        _case(
            "identity_equal",
            [melee, ranged, heads[0], heads[0].model_copy(update={"id": 13, "name": "13"})],
            (
                roles[0].model_copy(update={"locks": {"weapon": 100, "head": 10}}),
                roles[1].model_copy(update={"locks": {"weapon": 101, "head": 13}}),
            ),
            owned=(100, 101),
            costs={10: 100, 13: 100},
            budget_gp=200,
            max_swaps=2,
        )
    )
    cases.append(
        _case(
            "ammunition",
            [
                ranged.model_copy(update={"ammo_for": ("arrow",), "two_handed": True}),
                _item(
                    40,
                    "ammunition",
                    ammo_type="arrow",
                    bonuses=EquipmentBonuses(ranged_strength=10),
                ),
                _item(
                    41, "ammunition", ammo_type="bolt", bonuses=EquipmentBonuses(ranged_strength=30)
                ),
            ],
            (roles[1], RoleConfig(id="mage", style="magic", locks={"weapon": None})),
            max_swaps=2,
            reserved_supply_slots=26,
        )
    )
    cases.append(
        _case(
            "double_breakpoint",
            [
                melee,
                *[
                    _item(i, bonuses=EquipmentBonuses(melee_strength=3 if i == 12 else 0))
                    for i in range(1, 13)
                ],
                *[
                    _item(i, "cape", bonuses=EquipmentBonuses(melee_strength=3 if i == 32 else 0))
                    for i in range(21, 33)
                ],
            ],
            (RoleConfig(id="slash", style="slash", locks={"weapon": 100}),),
            max_swaps=0,
        )
    )
    return cases
