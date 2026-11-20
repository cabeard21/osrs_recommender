"""Pack immutable constraints once before entering native candidate loops."""

from __future__ import annotations

import json
from array import array
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass
from math import isfinite
from typing import Any

from tracker.gear.compact_acquisition import AcquisitionFacts
from tracker.gear.compact_states import SLOT_NAMES
from tracker.gear.revenant import FORMS as REVENANT_FORMS
from tracker.gear.running_costs import SPELL_RECIPES, STAFF_RUNES
from tracker.gear.wilderness_runes import RUNE_IDS

MAX_NATIVE_ITEM_COST = (2**53 - 1) // (4 * len(SLOT_NAMES))
MAX_NATIVE_RISK = 2**63 - 1
UNKNOWN_COPY_COST = -(2**63)


@dataclass(frozen=True)
class RiskStageData:
    limit: int
    guarded_ammunition: array[int]
    ammunition_users: int
    ammunition_keepers: int
    ammunition_attack_roles: int
    unavoidable: array[int]
    recoverable: array[int]
    priorities: array[int]
    unpriced: array[int]
    kept_slots: int
    feasible: Callable[[Set[int]], bool]


@dataclass(frozen=True)
class RuneStageData:
    suppliers: array[int]
    tome_suppliers: array[int]
    collisions: array[int]
    known_gear: array[int]
    prices: array[int]
    recipes: array[int]
    recipe_masks: array[int]
    quantities: array[int]


@dataclass(frozen=True)
class StageData:
    markets: array[int]
    costs: array[int]
    copy_family_offsets: array[int]
    copy_form_bits: array[int]
    copy_adjustments: array[int]
    untradeable: array[int]
    weights: array[float]
    marginals: array[float]
    edges: array[int]
    melee: array[int]
    scored: array[int]
    role_names: tuple[str, ...]
    role_json: tuple[bytes, ...]
    slot_json: tuple[bytes, ...]
    purchase_budget: int | None
    capacity: int
    acquisition_ties: bool
    risk: RiskStageData | None = None


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
    for label, limit in (
        ("purchase budget", search.request.purchase_budget),
        ("Wilderness risk budget", search.request.wilderness_risk_limit),
    ):
        if limit is not None and (type(limit) is not int or not 0 <= limit <= MAX_NATIVE_RISK):
            return f"Native {label} exceeds the supported range"
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
    if acquisition.revenant_adjustments:
        amounts = [abs(n) for n in acquisition.revenant_adjustments.values() if n is not None]
        highest_quote = max((q[1] for q in acquisition.quotes.values() if q), default=0)
        # At most four weapon families can contribute a signed adjustment.
        if (len(SLOT_NAMES) * highest_quote + max(amounts, default=0)) * len(roles) >= 2**53:
            return "Native acquisition adjustments exceed the supported range"
    return None


def _pack_copy_adjustments(
    ids: tuple[int, ...], adjustments: Mapping[frozenset[int], int | None]
) -> tuple[array[int], array[int], array[int]]:
    """Each weapon family has at most four forms, hence at most sixteen union costs."""
    offsets = array("i", [0]) * len(ids)
    bits = array("i", [0]) * len(ids)
    costs = array("q", [0])
    affected = {REVENANT_FORMS[i].market_id for subset in adjustments for i in subset}
    families: dict[int, list[tuple[int, int]]] = {}
    if affected:
        for index, item in enumerate(ids):
            form = REVENANT_FORMS.get(item)
            if form is not None and form.market_id in affected:
                families.setdefault(form.market_id, []).append((index, item))
    for members in families.values():
        for position, (index, _) in enumerate(members):
            offsets[index] = len(costs)
            bits[index] = 1 << position
        for mask in range(1 << len(members)):
            subset = frozenset(item for pos, (_, item) in enumerate(members) if mask & (1 << pos))
            value = adjustments.get(subset, 0)
            costs.append(UNKNOWN_COPY_COST if value is None else value)
    return offsets, bits, costs


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
    offsets, bits, adjustments = _pack_copy_adjustments(
        scoring.dense_ids, acquisition.revenant_adjustments
    )
    return StageData(
        markets=markets,
        costs=costs,
        copy_family_offsets=offsets,
        copy_form_bits=bits,
        copy_adjustments=adjustments,
        untradeable=untradeable,
        weights=weights,
        marginals=marginals,
        edges=array("i", [role_indices[name] for edge in search.edges for name in edge]),
        melee=array("i", [int(role.style in {"stab", "slash", "crush"}) for role in roles]),
        scored=array("i", [int(role.style != "special") for role in roles]),
        role_names=role_names,
        role_json=tuple(json.dumps(name).encode("ascii") for name in role_names),
        slot_json=tuple(json.dumps(name).encode("ascii") for name in SLOT_NAMES),
        purchase_budget=search.request.purchase_budget,
        capacity=28 - search.request.reserved_supply_slots,
        acquisition_ties=True,
        risk=_risk_data(search, scoring.dense_ids),
    )


def _risk_data(search: Any, dense_ids: tuple[int, ...]) -> RiskStageData | None:
    risk = getattr(search, "wilderness", None)
    if risk is None:
        return None
    limit = search.request.wilderness_risk_limit
    if type(risk.kept_slots) is not int or not 0 <= risk.kept_slots <= 4:
        raise ValueError("Native Wilderness protection requires zero to four kept items")
    priorities = risk.minimum_priorities
    known = sorted({priority for priority in priorities.values() if priority is not None})
    order = {priority: rank for rank, priority in enumerate(known)}
    items = dense_ids[1:]
    guarded = search.guarded_ammunition
    roles = search.request.roles
    # Clamping preserves the lower-bound property. Complete unions are still
    # checked with the exact Python integers and the shared death rules.
    return RiskStageData(
        limit=-1 if limit is None else limit,
        guarded_ammunition=array("i", [0, *(int(i in guarded) for i in items)]),
        ammunition_users=sum(
            1 << r for r, role in enumerate(roles) if role.id in search.ammunition_users
        ),
        ammunition_keepers=sum(
            1 << r for r, role in enumerate(roles) if role.id in search.ammunition_keepers
        ),
        ammunition_attack_roles=sum(
            1 << r for r, role in enumerate(roles) if role.style in {"ranged", "special"}
        ),
        unavoidable=array(
            "q", [0, *(min(risk.minimum_unavoidable.get(i, 0), MAX_NATIVE_RISK) for i in items)]
        ),
        recoverable=array(
            "q", [0, *(min(risk.recoverable_loss.get(i, 0), MAX_NATIVE_RISK) for i in items)]
        ),
        # Negative ranks encode non-participants (-2) and arbitrary priorities (-1).
        priorities=array(
            "i", [-2, *(order.get(priorities[i], -1) if i in priorities else -2 for i in items)]
        ),
        unpriced=array(
            "i",
            [
                0,
                *(
                    2 if i in risk.unpriced_always else int(i in risk.requires_protection)
                    for i in items
                ),
            ],
        ),
        kept_slots=risk.kept_slots,
        # The final loose-rune bundle can shift the protection cutoff. Gear-only
        # checks must remain admissible until the selected spells are known.
        feasible=risk.partial_feasible
        if getattr(search, "rune_limits_active", False)
        or getattr(getattr(risk, "policy", None), "attacks_per_setup", None)
        else risk.feasible,
    )


def pack_runes(search: Any, scoring: Any) -> RuneStageData | None:
    if not getattr(search, "rune_limits_active", False):
        return None
    risk = search.wilderness
    casts = risk.policy.attacks_per_setup or risk.policy.spell_casts
    ids = tuple(sorted(RUNE_IDS))
    bits = {item: 1 << position for position, item in enumerate(ids)}
    spells = tuple(SPELL_RECIPES)
    spell_indices = {spell: index for index, spell in enumerate(spells)}
    recipes = [tuple(SPELL_RECIPES[spell].get(item, 0) * casts for item in ids) for spell in spells]
    greatest_stack = [max(recipe[index] for recipe in recipes) for index in range(len(ids))]
    prices = [
        -2
        if item not in risk.rune_rules
        else (-1 if (price := risk.rune_rules[item].unprotected_loss_gp) is None else price)
        for item in ids
    ]
    # The worst complete role fits a signed accumulator including exposed rune stacks.
    term = 2**55
    if (
        len(ids) >= 63
        or any(
            price * qty >= term or qty >= 2**31
            for price, qty in zip(prices, greatest_stack, strict=True)
        )
        or any(
            value >= term
            for value in (*risk.minimum_unavoidable.values(), *risk.recoverable_loss.values())
        )
    ):
        return None
    tome_runes = {
        item: definition.tome_effect.rune_id
        for item, definition in search.items.items()
        if definition.tome_effect is not None
    }
    return RuneStageData(
        suppliers=array(
            "Q",
            [
                sum(bits.get(rune, 0) for rune in STAFF_RUNES.get(item, ()))
                for item in scoring.dense_ids
            ],
        ),
        tome_suppliers=array(
            "Q", [bits.get(tome_runes.get(item, 0), 0) for item in scoring.dense_ids]
        ),
        collisions=array("Q", [bits.get(item, 0) for item in scoring.dense_ids]),
        known_gear=array("i", [int(item in risk.rules) for item in scoring.dense_ids]),
        prices=array("q", prices),
        recipes=array(
            "i",
            [
                -2 if option.powered_attack else spell_indices.get(option.spell or "", -1)
                for _, option in scoring.option_records
            ],
        ),
        recipe_masks=array(
            "Q",
            [sum(1 << index for index, qty in enumerate(recipe) if qty) for recipe in recipes],
        ),
        quantities=array("i", [qty for recipe in recipes for qty in recipe]),
    )
