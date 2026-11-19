"""Standard-world Wilderness PvP death risk over physical equipment IDs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache, lru_cache
from heapq import nlargest
from itertools import pairwise
from math import inf
from types import MappingProxyType
from typing import Any, Literal

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from tracker.estimation.prices import PriceRecord, resolve_price
from tracker.gear.models import EquipmentDefinition, GearModel
from tracker.gear.wilderness_data import (
    ALWAYS_KEPT,
    CHARGED_ETHER,
    CHARGED_RECIPES,
    DEPTH_LOSSES,
    GE_GUIDE,
    NPC_REPLACEMENTS,
    ORNAMENTED_DEFENDERS,
    UNREVIEWED_TRADEABLE,
)
from tracker.gear.wilderness_data import (
    RULES_REVISION as RULES_REVISION,
)
from tracker.gear.wilderness_runes import RUNE_IDS

Outcome = Literal["kept", "dropped", "broken", "mangled", "destroyed", "converted", "unknown"]
MAX_STACK = 2**31 - 1
NO_RUNES: Mapping[int, int] = MappingProxyType({})


class WildernessPolicy(GearModel):
    depth: Literal["level_1_20", "level_21_plus"] = "level_21_plus"
    skulled: bool = Field(default=False, strict=True)
    protect_item: bool = Field(default=False, strict=True)
    max_loss_gp: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    spell_casts: int | None = Field(default=None, ge=1, le=10_000, strict=True)

    @model_serializer(mode="wrap")
    def serialize_optional_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        serialized: dict[str, Any] = handler(self)
        return {
            key: value
            for key, value in serialized.items()
            if key not in {"max_loss_gp", "spell_casts"} or value is not None
        }

    @property
    def kept_slots(self) -> int:
        return (0 if self.skulled else 3) + int(self.protect_item)


@dataclass(frozen=True, slots=True)
class Charge:
    recipe: tuple[tuple[int, int, int | None], ...]
    minimum: int
    maximum: int
    always_lost: bool = True

    unit_gp: int | None = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "unit_gp",
            _optional_sum([None if gp is None else units * gp for _, units, gp in self.recipe]),
        )


@dataclass(frozen=True, slots=True)
class DeathItem:
    priority: int | None
    unprotected_loss_gp: int | None
    unprotected_outcome: Outcome = "dropped"
    protected_loss_gp: int | None = 0
    protected_outcome: Outcome = "kept"
    protection_slot: bool = True
    ammo: bool = False
    charge: Charge | None = None

    @property
    def minimum_quantity(self) -> int:
        return self.charge.minimum if self.charge else 1

    @property
    def maximum_quantity(self) -> int:
        return self.charge.maximum if self.charge else MAX_STACK if self.ammo else 1

    def loss(self, quantity: int, kept: bool) -> int | None:
        base = self.protected_loss_gp if kept else self.unprotected_loss_gp
        if base is None:
            return None
        charge = self.charge
        if charge and (charge.always_lost or not kept):
            return None if charge.unit_gp is None else base + quantity * charge.unit_gp
        return base * quantity if self.ammo else base


UNKNOWN = DeathItem(None, None, "unknown", None, "unknown")


@dataclass(frozen=True, slots=True)
class _Entry:
    item_id: int
    item: DeathItem
    priority: int | None
    quantity: int = 1

    @property
    def saving(self) -> float | int:
        exposed = self.item.loss(self.quantity, False)
        protected = self.item.loss(self.quantity, True)
        return inf if exposed is None else exposed - protected if protected is not None else -inf


@dataclass(frozen=True, slots=True)
class _Loss:
    loss_gp: int | None
    rows: tuple[tuple[_Entry, bool], ...]
    displaces_durable_gear: bool


def _loss_order(loss_gp: int | None) -> float | int:
    return inf if loss_gp is None else loss_gp


def _optional_sum(values: list[int | None]) -> int | None:
    return None if None in values else sum(value for value in values if value is not None)


def _price(
    fact: Mapping[str, Any], resource: int, prices: Mapping[int, PriceRecord], now: datetime
) -> int | None:
    if resource == 995:
        return 1
    scoped = fact.get("price", {}).get("amount_gp")
    return (
        scoped
        if type(scoped) is int and scoped > 0
        else resolve_price(None, prices.get(resource), now=now).gp
    )


def _physical_death_rule(
    item: EquipmentDefinition,
    fact: Mapping[str, Any],
    policy: WildernessPolicy,
    prices: Mapping[int, PriceRecord],
    now: datetime,
) -> DeathItem | None:
    item_id = item.id
    if item_id in ALWAYS_KEPT:
        return DeathItem(None, 0, "kept", protection_slot=False)
    depth_rule = DEPTH_LOSSES.get(item_id)
    if depth_rule:
        priority, shallow_fee, deep_fee, deep_outcome = depth_rule
        shallow = policy.depth == "level_1_20"
        return DeathItem(
            priority,
            shallow_fee if shallow else deep_fee,
            "broken" if shallow else deep_outcome,
        )
    if item_id in NPC_REPLACEMENTS:
        priority, replacement = NPC_REPLACEMENTS[item_id]
        return DeathItem(priority, replacement, "converted")
    if item_id in ORNAMENTED_DEFENDERS:
        priority, repair, ornament = ORNAMENTED_DEFENDERS[item_id]
        quote = _price({}, ornament, prices, now)
        return DeathItem(priority, repair + quote if quote is not None else None, "broken")
    if item_id in CHARGED_ETHER:
        base = CHARGED_ETHER[item_id]
        unit = _price({}, 21820, prices, now)
        return DeathItem(
            None,
            _price(fact, base, prices, now),
            "converted",
            charge=Charge(((21820, 1, unit),), 1_001, 17_000),
        )
    if charged := CHARGED_RECIPES.get(item_id):
        base, maximum, recipe = charged
        return DeathItem(
            None,
            _price(fact, base, prices, now),
            "converted",
            charge=Charge(
                tuple(
                    (resource, units, _price({}, resource, prices, now))
                    for resource, units in recipe
                ),
                1,
                maximum,
                always_lost=False,
            ),
        )
    priority = GE_GUIDE.get(item_id)
    if priority is None or item_id in UNREVIEWED_TRADEABLE or not item.tradeable:
        return None
    ammo = item.stackable and item.slot in {"ammunition", "weapon"}
    if item.stackable and not ammo:
        return None
    return DeathItem(
        priority,
        _price(fact, item_id, prices, now),
        ammo=ammo,
    )


@dataclass(frozen=True, eq=False, slots=True)
class WildernessRisk:
    policy: WildernessPolicy
    budget_gp: int
    rules: Mapping[int, DeathItem]
    rune_rules: Mapping[int, DeathItem] = field(default_factory=dict)
    minimum_unavoidable: Mapping[int, int] = field(init=False)
    recoverable_loss: Mapping[int, int] = field(init=False)
    minimum_priorities: Mapping[int, int | None] = field(init=False)
    requires_protection: frozenset[int] = field(init=False)
    unpriced_always: frozenset[int] = field(init=False)
    _death_rules: Mapping[int, DeathItem] = field(init=False, repr=False)
    _minimum_feasible: Callable[[frozenset[int]], bool] = field(init=False, repr=False)
    _minimum_runes_feasible: Callable[[frozenset[int], tuple[tuple[int, int], ...]], bool] = field(
        init=False, repr=False
    )

    def __post_init__(self) -> None:
        unavoidable = {}
        recoverable = {}
        requires_protection: set[int] = set()
        unpriced_always: set[int] = set()
        for item_id, rule in self.rules.items():
            unprotected = rule.loss(rule.minimum_quantity, False)
            protected = (
                rule.loss(rule.minimum_quantity, True) if rule.protection_slot else unprotected
            )
            lower = min(protected if protected is not None else 0, unprotected or 0)
            unavoidable[item_id] = lower
            recoverable[item_id] = (unprotected or 0) - lower
            if unprotected is None:
                (unpriced_always if protected is None else requires_protection).add(item_id)
        object.__setattr__(self, "rules", MappingProxyType(dict(self.rules)))
        object.__setattr__(self, "rune_rules", MappingProxyType(dict(self.rune_rules)))
        object.__setattr__(
            self,
            "_death_rules",
            MappingProxyType(dict(self.rules) | dict(self.rune_rules))
            if self.rune_rules
            else self.rules,
        )
        object.__setattr__(self, "minimum_unavoidable", MappingProxyType(unavoidable))
        object.__setattr__(self, "recoverable_loss", MappingProxyType(recoverable))
        object.__setattr__(
            self,
            "minimum_priorities",
            MappingProxyType(
                {
                    item_id: rule.priority
                    for item_id, rule in self.rules.items()
                    if rule.protection_slot
                }
            ),
        )
        object.__setattr__(self, "requires_protection", frozenset(requires_protection))
        object.__setattr__(self, "unpriced_always", frozenset(unpriced_always))
        object.__setattr__(
            self, "_minimum_feasible", lru_cache(maxsize=16_384)(self._check_minimum)
        )
        object.__setattr__(
            self, "_minimum_runes_feasible", lru_cache(maxsize=16_384)(self._check_minimum_runes)
        )

    @classmethod
    def build(
        cls,
        policy: WildernessPolicy,
        budget_gp: int,
        items: Mapping[int, EquipmentDefinition],
        facts: Mapping[int, Mapping[str, Any]],
        prices: Mapping[int, PriceRecord],
        now: datetime,
    ) -> WildernessRisk:
        return cls(
            policy,
            budget_gp,
            {
                item_id: rule
                for item_id, item in items.items()
                if (rule := _physical_death_rule(item, facts.get(item_id, {}), policy, prices, now))
                is not None
            },
            rune_rules={
                item_id: DeathItem(GE_GUIDE[item_id], _price({}, item_id, prices, now), ammo=True)
                for item_id in RUNE_IDS
                if policy.spell_casts is not None and item_id in GE_GUIDE
            },
        )

    @property
    def kept_slots(self) -> int:
        return self.policy.kept_slots

    def rank_key(self, item_id: int) -> tuple[bool, int]:
        rule = self.rules.get(item_id, UNKNOWN)
        loss = rule.loss(rule.minimum_quantity, False)
        return (loss is None, loss or 0)

    def lower_bound(self, ids: Set[int]) -> int:
        savings = [self.recoverable_loss.get(item_id, 0) for item_id in ids]
        fixed = sum(self.minimum_unavoidable.get(item_id, 0) for item_id in ids)
        return fixed + sum(savings) - sum(nlargest(self.kept_slots, savings))

    def feasible(self, ids: Set[int]) -> bool:
        return self._minimum_feasible(frozenset(ids))

    def rune_partial_feasible(self, ids: Set[int], runes: Mapping[int, int] | None) -> bool:
        """Bound exposed loss in the per-unit interpretation without deciding protection order."""
        if runes is None or not self.partial_feasible(ids):
            return False
        if not runes:
            return True
        if not self.rune_rules.keys() >= runes.keys() or not ids.isdisjoint(runes):
            return False
        gear_savings = [self.recoverable_loss.get(item_id, 0) for item_id in ids]
        fixed = sum(self.minimum_unavoidable.get(item_id, 0) for item_id in ids)
        rune_savings = []
        rune_exposed = 0
        for item_id, qty in runes.items():
            unit_gp = self.rune_rules[item_id].unprotected_loss_gp
            if unit_gp is None and qty > self.kept_slots:
                return False
            rune_exposed += (unit_gp or 0) * qty
            rune_savings.extend([unit_gp or 0] * min(qty, self.kept_slots))
        exposed = fixed + sum(gear_savings) + rune_exposed
        savings = sum(nlargest(self.kept_slots, (*gear_savings, *rune_savings)))
        return exposed - savings <= self.budget_gp

    def rune_feasible(self, ids: Set[int], runes: Mapping[int, int] | None) -> bool:
        if runes is None:
            return False
        if not runes:
            return self.feasible(ids)
        return self._minimum_runes_feasible(frozenset(ids), tuple(sorted(runes.items())))

    def _check_minimum_runes(
        self, ids: frozenset[int], packed_runes: tuple[tuple[int, int], ...]
    ) -> bool:
        runes = dict(packed_runes)
        return self.rune_partial_feasible(ids, runes) and self._fits(
            self._worst(self._minimum(ids) | runes, self.kept_slots)
        )

    def partial_feasible(self, ids: Set[int]) -> bool:
        if not self.rules.keys() >= ids or not self.unpriced_always.isdisjoint(ids):
            return False
        if self.lower_bound(ids) > self.budget_gp:
            return False
        requiring_protection = self.requires_protection & ids
        if not requiring_protection:
            return True
        if not self.kept_slots:
            return False
        priorities = [
            (item_id, self.minimum_priorities[item_id])
            for item_id in ids
            if item_id in self.minimum_priorities
        ]
        for item_id in requiring_protection:
            priority = self.minimum_priorities[item_id]
            competitors = sum(
                other != item_id and (priority is None or rank is None or rank >= priority)
                for other, rank in priorities
            )
            if competitors >= self.kept_slots:
                return False
        return True

    def _check_minimum(self, ids: frozenset[int]) -> bool:
        if not self.partial_feasible(ids):
            return False
        loss = self._worst(self._minimum(ids), self.kept_slots)
        return self._fits(loss)

    def _fits(self, result: _Loss) -> bool:
        return (
            result.loss_gp is not None
            and result.loss_gp <= self.budget_gp
            and not result.displaces_durable_gear
        )

    def _minimum(self, ids: Set[int]) -> dict[int, int]:
        return {item_id: self.rules.get(item_id, UNKNOWN).minimum_quantity for item_id in ids}

    def _loss(self, quantities: Mapping[int, int], keep: int, *, whole_stack: bool) -> _Loss:
        eligible: list[_Entry] = []
        unprotected: list[tuple[_Entry, bool]] = []
        for item_id, qty in quantities.items():
            rule = self._death_rules.get(item_id, UNKNOWN)
            # Units beyond the number of protection slots may be aggregated.
            copies = min(keep, qty) if not whole_stack and rule.ammo and rule.protection_slot else 1
            priority = rule.priority
            if rule.ammo and whole_stack and priority is not None:
                priority *= qty
            if rule.protection_slot:
                eligible.extend(
                    _Entry(item_id, rule, priority, qty if whole_stack or not rule.ammo else 1)
                    for _ in range(copies)
                )
            if not rule.protection_slot or (rule.ammo and not whole_stack and qty > copies):
                remainder = qty if not rule.protection_slot else qty - copies
                unprotected.append((_Entry(item_id, rule, priority, remainder), False))
        # Fixed rune stacks are part of the ordinary carried setup. Automatic
        # ammo can spend unused protection slots without changing that baseline.
        baseline = []
        adjustable_ammo = []
        for entry in eligible:
            if entry.item.ammo and entry.item_id not in self.rune_rules:
                adjustable_ammo.append(entry.priority or 0)
            else:
                baseline.append(entry.priority or 0)
        baseline.sort(reverse=True)
        protected_baseline = min(len(baseline), keep)
        displaces = bool(
            protected_baseline
            and sum(priority >= baseline[protected_baseline - 1] for priority in adjustable_ammo)
            > keep - protected_baseline
        )
        known = sorted(
            (entry for entry in eligible if entry.priority is not None),
            key=lambda entry: (-(entry.priority or 0), entry.saving, entry.item_id),
        )
        uncertain = sorted(
            (entry for entry in eligible if entry.priority is None),
            key=lambda entry: (entry.saving, entry.item_id),
        )
        kept = min(keep, len(eligible))
        results = []
        for count in range(max(0, kept - len(known)), min(kept, len(uncertain)) + 1):
            other_count = kept - count
            rows = (
                *((entry, True) for entry in known[:other_count]),
                *((entry, True) for entry in uncertain[:count]),
                *((entry, False) for entry in known[other_count:]),
                *((entry, False) for entry in uncertain[count:]),
                *unprotected,
            )
            results.append(
                _Loss(
                    _optional_sum([entry.item.loss(entry.quantity, kept) for entry, kept in rows]),
                    rows,
                    displaces,
                )
            )
        return max(results, key=lambda loss: _loss_order(loss.loss_gp))

    def _worst(self, quantities: Mapping[int, int], keep: int) -> _Loss:
        whole = self._loss(quantities, keep, whole_stack=True)
        if not keep or not any(
            qty > 1 and self._death_rules.get(item_id, UNKNOWN).ammo
            for item_id, qty in quantities.items()
        ):
            return whole
        # Reserve enough budget and protection under both stack interpretations
        # until the live game rules can be confirmed for the relevant stacks.
        units = self._loss(quantities, keep, whole_stack=False)
        worst = max((whole, units), key=lambda loss: _loss_order(loss.loss_gp))
        return _Loss(
            worst.loss_gp, worst.rows, whole.displaces_durable_gear or units.displaces_durable_gear
        )

    def _maximize(self, item_id: int, quantities: dict[int, int]) -> int:
        rule = self.rules[item_id]
        minimum = quantities[item_id]
        maximum = rule.maximum_quantity
        # With fixed keep ordering, loss is linear and nondecreasing. Isolate
        # quantity thresholds where a stack can change the keep ordering.
        boundaries = {minimum, maximum + 1}
        if self.kept_slots and rule.ammo and rule.priority:
            boundaries.update(range(1, self.kept_slots + 2))
            for other, qty in quantities.items():
                peer = self._death_rules.get(other, UNKNOWN)
                if other != item_id and peer.priority is not None and peer.protection_slot:
                    crossover = peer.priority * (qty if peer.ammo else 1) // rule.priority
                    boundaries.update((crossover, crossover + 1))
        points = sorted(value for value in boundaries if minimum <= value <= maximum + 1)

        @cache
        def fits(qty: int) -> bool:
            return self._fits(self._worst(quantities | {item_id: qty}, self.kept_slots))

        for start, end in reversed(tuple(pairwise(points))):
            if not fits(start):
                continue
            last = end - 1
            if fits(last):
                return last
            while start + 1 < last:
                mid = (start + last) // 2
                if fits(mid):
                    start = mid
                else:
                    last = mid
            return start
        return minimum

    def report(
        self,
        loadouts: Mapping[str, Mapping[str, int]],
        *,
        base_role: str | None = None,
        idle_ammunition: Set[int] = frozenset(),
        runes: Mapping[int, int] | None = NO_RUNES,
    ) -> dict[str, Any]:
        roles = tuple(loadouts)
        if base_role is not None and base_role in loadouts:
            roles = (base_role, *(role for role in roles if role != base_role))
        ids = dict.fromkeys(item for role in roles for item in sorted(loadouts[role].values()))
        quantities = self._minimum(ids.keys())
        if runes:
            quantities = quantities | dict(runes)
        resources = [
            item_id
            for item_id in ids
            if item_id not in idle_ammunition
            and self.rules.get(item_id, UNKNOWN).maximum_quantity > 1
        ]
        result = self._worst(quantities, self.kept_slots)
        if runes is not None and resources and self._fits(result):
            for item_id in resources:
                quantities[item_id] = self._maximize(item_id, quantities)
            result = self._worst(quantities, self.kept_slots)
        return {
            "loss_gp": result.loss_gp if runes is not None else None,
            "without_protect_item_gp": (
                self._worst(quantities, self.kept_slots - 1).loss_gp
                if runes is not None and self.policy.protect_item
                else None
            ),
            "items": _report_rows(result),
            "quantities": [
                *(
                    {"item_id": item_id, "resource_id": item_id, "kind": "rune", "quantity": qty}
                    for item_id, qty in sorted((runes or NO_RUNES).items())
                ),
                *(
                    row
                    for item_id in resources
                    for row in _recommended_quantities(
                        item_id, self.rules[item_id], quantities[item_id]
                    )
                ),
            ],
            "rules_revision": RULES_REVISION,
        }


def _recommended_quantities(item_id: int, item: DeathItem, quantity: int) -> list[dict[str, Any]]:
    if charge := item.charge:
        return [
            {
                "item_id": item_id,
                "resource_id": resource,
                "kind": "charge",
                "quantity": units * quantity,
            }
            for resource, units, _ in charge.recipe
        ]
    return [{"item_id": item_id, "resource_id": item_id, "kind": "ammo", "quantity": quantity}]


def _report_rows(result: _Loss) -> list[dict[str, Any]]:
    quantities: Counter[tuple[int, Outcome, int | None]] = Counter()
    for entry, kept in result.rows:
        item = entry.item
        outcome = item.protected_outcome if kept else item.unprotected_outcome
        base_loss = item.protected_loss_gp if kept else item.unprotected_loss_gp
        base_qty = entry.quantity if item.ammo else 1
        quantities[entry.item_id, outcome, base_loss] += base_qty
        if charge := item.charge:
            lost = charge.always_lost or not kept
            for resource, units, gp in charge.recipe:
                quantities[resource, "dropped" if lost else "kept", gp if lost else 0] += (
                    units * entry.quantity
                )
    return [
        {
            "item_id": item_id,
            "outcome": outcome,
            "loss_gp": None if unit_gp is None else unit_gp * qty,
            "quantity": qty,
        }
        for (item_id, outcome, unit_gp), qty in sorted(
            quantities.items(), key=lambda row: (row[0][0], row[0][1])
        )
    ]
