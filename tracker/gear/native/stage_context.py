"""Pack immutable constraints once before entering native candidate loops."""

from __future__ import annotations

import json
from array import array
from dataclasses import dataclass
from math import isfinite
from typing import Any

from tracker.gear.compact_acquisition import AcquisitionFacts
from tracker.gear.compact_states import SLOT_NAMES

MAX_NATIVE_ITEM_COST = (2**53 - 1) // (4 * len(SLOT_NAMES))


@dataclass(frozen=True)
class StageData:
    markets: array[int]
    costs: array[int]
    untradeable: array[int]
    weights: array[float]
    marginals: array[float]
    edges: array[int]
    melee: array[int]
    scored: array[int]
    cost_data: Any
    role_names: tuple[str, ...]
    role_json: tuple[bytes, ...]
    slot_json: tuple[bytes, ...]
    budget: int
    capacity: int
    acquisition_ties: bool


def preflight(search: Any, acquisition: AcquisitionFacts | None = None) -> str | None:
    """Reject unsupported dimensions and numeric ranges before native work begins."""
    roles = search.request.roles
    if not 1 <= len(roles) <= 4:
        return "Native stages require one to four roles"
    role_names = {role.id for role in roles}
    if len(role_names) != len(roles) or any(
        name not in role_names for edge in search.edges for name in edge
    ):
        return "Native role identities and transition edges must match"
    if any(
        not isinstance(role.weight, (int, float))
        or not isfinite(role.weight)
        or not 0 <= role.weight <= 1e12
        for role in roles
    ):
        return "Native role weights exceed the finite supported range"
    budget = search.request.budget_gp
    if type(budget) is not int or not 0 <= budget < 2**63:
        return "Native budget exceeds the supported range"
    reserved = search.request.reserved_supply_slots
    if type(reserved) is not int or not 0 <= reserved <= 28:
        return "Native supply reservation exceeds inventory capacity"
    acquisition = acquisition or AcquisitionFacts.from_facts(search.facts, search.request)
    for quote in acquisition.quotes.values():
        if quote is None:
            continue
        market, amount = quote
        if (
            type(market) is not int
            or not 0 <= market < 2**63
            or type(amount) is not int
            # Rank keys use doubles; every possible 44-item union stays exact.
            or not 0 <= amount <= MAX_NATIVE_ITEM_COST
        ):
            return "Native acquisition integers exceed the supported range"
    return None


def pack_stage(search: Any, scoring: Any) -> StageData:
    acquisition = AcquisitionFacts.from_facts(search.facts, search.request)
    reason = preflight(search, acquisition)
    if reason is not None:
        raise ValueError(reason)
    if len(search.request.roles) != scoring.role_count:
        raise ValueError("Native stage and scoring role dimensions differ")
    if len(scoring.dense_ids) != scoring.item_count or any(
        item not in search.items or item not in acquisition.quotes for item in scoring.dense_ids[1:]
    ):
        raise ValueError("Native stage and scoring item dimensions differ")
    markets = array("q", [0])
    costs = array("q", [0])
    untradeable = array("i", [0])
    for item in scoring.dense_ids[1:]:
        quote = acquisition.quotes[item]
        market, amount = quote if quote else (0, 0)
        markets.append(market)
        costs.append(amount)
        untradeable.append(int(item in acquisition.untradeables))
    roles = search.request.roles
    role_names = tuple(role.id for role in roles)
    role_indices = {name: index for index, name in enumerate(role_names)}
    weights = array("d", [role.weight for role in roles])
    marginals = array(
        "d",
        [
            search.marginals.get((role.id, item), 0.0)
            for role in roles
            for item in scoring.dense_ids
        ],
    )
    if not all(isfinite(value) and abs(value) <= 1e100 for value in marginals):
        raise ValueError("Native stage ranking requires finite values")
    return StageData(
        markets=markets,
        costs=costs,
        untradeable=untradeable,
        weights=weights,
        marginals=marginals,
        edges=array("i", [role_indices[name] for edge in search.edges for name in edge]),
        melee=array("i", [int(role.style in {"stab", "slash", "crush"}) for role in roles]),
        scored=array("i", [int(role.style != "special") for role in roles]),
        cost_data=_cost_data(search, scoring),
        role_names=role_names,
        role_json=tuple(json.dumps(name).encode("ascii") for name in role_names),
        slot_json=tuple(json.dumps(name).encode("ascii") for name in SLOT_NAMES),
        budget=search.request.budget_gp,
        capacity=28 - search.request.reserved_supply_slots,
        acquisition_ties=True,
    )


def _cost_data(search: Any, scoring: Any) -> Any:
    if not getattr(search, "native_cost_objective", False):
        return None
    from tracker.gear.native.cost_context import pack_costs

    return pack_costs(search, scoring)
