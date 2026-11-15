"""Prepared immutable resource costs; descriptions are expanded only for reports."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime
from math import isfinite
from typing import Any, Literal

from tracker.estimation.prices import PriceRecord, ResolvedPrice, resolve_price
from tracker.gear.ammo import recovery_rate
from tracker.gear.halberd_charging import CrystalChargingPolicy
from tracker.gear.hopper import PROC_CHANCE
from tracker.gear.hopper import active as hopper_active
from tracker.gear.models import EquipmentDefinition
from tracker.gear.powered import review
from tracker.gear.ranged_resources import THROWN_IDS
from tracker.gear.reviewed_attacks import TORAG_USABLE_IDS
from tracker.gear.running_costs import (
    _CHARGES,
    _RESOURCE_NAMES,
    _RUNES,
    COST_MODEL_VERSION,
    SPELL_RECIPES,
    STAFF_RUNES,
)
from tracker.gear.tomes import ASSUMPTION as TOME_ASSUMPTION


@dataclass(frozen=True, slots=True)
class Resource:
    item_id: int
    name: str
    quantity: float
    supplied: float
    supplier: str | None
    quote: ResolvedPrice | None
    assumed_price: float | None = None

    @property
    def consumed(self) -> float:
        return self.quantity - self.supplied

    @property
    def unit_price(self) -> float | None:
        if self.assumed_price is not None:
            return self.assumed_price
        return 1 if self.item_id == 995 else self.quote.gp if self.quote else 0

    def report(self) -> dict[str, Any]:
        quote = self.quote
        return {
            "item_id": self.item_id,
            "name": self.name,
            "required_quantity": self.quantity,
            "consumed_quantity": self.consumed,
            "supplied_quantity": self.supplied,
            "supplied_by": self.supplier,
            "unit_price_gp": self.unit_price,
            "price_layer": "assumed"
            if self.assumed_price is not None
            else "fixed"
            if self.item_id == 995
            else quote.layer.value
            if quote
            else "free",
            "price_confidence": str(quote.confidence) if quote else None,
            "price_trade_at": quote.trade_at.isoformat() if quote and quote.trade_at else None,
        }


@dataclass(frozen=True, slots=True)
class NumericCost:
    status: Literal["known", "unavailable"]
    gp_per_attack: float | None
    gp_per_second: float | None
    gp_per_hour: float | None
    gp_per_damage: float | None


@dataclass(frozen=True, slots=True)
class ChargeAlternative:
    resources: tuple[Resource, ...]
    gp_per_attack: float | None


@dataclass(frozen=True, slots=True)
class PreparedCost:
    resources: tuple[Resource, ...]
    alternatives: tuple[ChargeAlternative, ...]
    limitations: tuple[str, ...]
    missing_prices: tuple[str, ...]
    gp_per_attack: float | None
    tome_assumption: bool = False
    on_hit_resources: tuple[Resource, ...] = ()
    on_hit_cost: float | None = 0
    extra_assumptions: tuple[str, ...] = ()

    def score(
        self, interval: float | None, dps: float | None, accuracy: float | None = None
    ) -> NumericCost:
        cost = self.gp_per_attack
        valid_accuracy = accuracy is not None and isfinite(accuracy) and 0 <= accuracy <= 1
        if self.on_hit_resources:
            cost = (
                cost + accuracy * self.on_hit_cost
                if cost is not None
                and self.on_hit_cost is not None
                and valid_accuracy
                and accuracy is not None
                else None
            )
        rate = cost / interval if cost is not None and interval and interval > 0 else None
        return NumericCost(
            "unavailable" if self.limitations or self.missing_prices or cost is None else "known",
            cost,
            rate,
            rate * 3600 if rate is not None else None,
            rate / dps if rate is not None and dps and dps > 0 else None,
        )

    def report(self, numeric: NumericCost, accuracy: float | None = None) -> dict[str, Any]:
        assumptions = (
            ("Cheapest priced charging recipe; actual charges unknown.",)
            if self.alternatives
            else ()
        )
        if self.on_hit_resources:
            assumptions = (
                *assumptions,
                "Slayer enchantment consumption is expected successful "
                "on-task Magic Dart hits / 2,500; actual charges unknown.",
            )
        valid_accuracy = accuracy is not None and isfinite(accuracy) and 0 <= accuracy <= 1
        conditional = tuple(
            replace(r, quantity=r.quantity * (accuracy if valid_accuracy and accuracy else 0))
            for r in self.on_hit_resources
        )
        if self.tome_assumption:
            assumptions = (*assumptions, TOME_ASSUMPTION)
        assumptions = (*assumptions, *self.extra_assumptions)
        return {
            "model_version": COST_MODEL_VERSION,
            "status": numeric.status,
            "gp_per_attack": numeric.gp_per_attack,
            "gp_per_second": numeric.gp_per_second,
            "gp_per_hour": numeric.gp_per_hour,
            "gp_per_damage": numeric.gp_per_damage,
            "resources": [r.report() for r in (*self.resources, *conditional)],
            "charging_alternatives": [
                {"resources": [r.report() for r in a.resources], "gp_per_attack": a.gp_per_attack}
                for a in self.alternatives
            ],
            "charging_assumption": " ".join(assumptions) or None,
            "reasons": [
                *self.limitations,
                *(f"No price available for {n}." for n in self.missing_prices),
                *(
                    ("Accuracy is unavailable for expected enchantment consumption.",)
                    if self.on_hit_resources and not valid_accuracy
                    else ()
                ),
            ],
        }


def _resource_sum(resources: tuple[Resource, ...]) -> float | None:
    if any(r.unit_price is None for r in resources):
        return None
    return sum(r.consumed * r.unit_price for r in resources if r.unit_price is not None)


class CostEvaluator:
    """Bounded recipe reuse over one frozen price/time context, independent of DPS."""

    def __init__(
        self, prices: Mapping[int, PriceRecord], now: datetime, *, capacity: int = 4096
    ) -> None:
        if capacity < 0:
            raise ValueError("capacity must be nonnegative")
        self.prices = dict(prices)
        self.now = now
        self.capacity = capacity
        self._recipes: OrderedDict[tuple[Any, ...], PreparedCost] = OrderedDict()
        self._quotes: dict[int, ResolvedPrice] = {}

    def resource(
        self,
        item_id: int,
        name: str,
        quantity: float,
        supplied: float = 0,
        supplier: str | None = None,
    ) -> Resource:
        quote = None
        if quantity - supplied and item_id != 995:
            if item_id not in self._quotes:
                self._quotes[item_id] = resolve_price(None, self.prices.get(item_id), now=self.now)
            quote = self._quotes[item_id]
        return Resource(item_id, name, quantity, supplied, supplier, quote)

    def prepare(
        self,
        equipment: Mapping[str, EquipmentDefinition],
        option: Mapping[str, Any],
        *,
        on_slayer_task: bool = False,
        fight_duration_seconds: int = 60,
        crystal_halberd_charging: CrystalChargingPolicy | None = None,
    ) -> PreparedCost:
        weapon, ammo, cape = (equipment.get(s) for s in ("weapon", "ammunition", "cape"))
        body, shield = equipment.get("body"), equipment.get("shield")
        head = equipment.get("head")
        charging = crystal_halberd_charging or CrystalChargingPolicy()
        torag = any(i.id in TORAG_USABLE_IDS for i in equipment.values())
        tome_assumption = any(i.tome_effect for i in equipment.values())
        key = (
            (weapon.id, weapon.name, weapon.ammo_for) if weapon else None,
            (ammo.id, ammo.name, ammo.ammo_type) if ammo else None,
            (cape.id, cape.name) if cape else None,
            body.id if body else None,
            head.id if head else None,
            fight_duration_seconds,
            charging.method,
            charging.coin_recharge_cost_gp,
            charging.shard_value_gp,
            (shield.id, shield.name, shield.slot, shield.tome_effect) if shield else None,
            torag,
            tome_assumption,
            option.get("attack_type"),
            option.get("spell"),
            bool(option.get("powered_attack")),
            on_slayer_task,
            bool(getattr(weapon, "slayer_staff_enchanted", False)),
        )
        if key in self._recipes:
            self._recipes.move_to_end(key)
            return self._recipes[key]
        result = self._prepare(
            equipment,
            option,
            torag,
            tome_assumption,
            on_slayer_task,
            fight_duration_seconds,
            charging,
        )
        if self.capacity:
            self._recipes[key] = result
            if len(self._recipes) > self.capacity:
                self._recipes.popitem(last=False)
        return result

    def _prepare(
        self,
        equipment: Mapping[str, EquipmentDefinition],
        option: Mapping[str, Any],
        torag: bool,
        tome_assumption: bool,
        on_slayer_task: bool,
        fight_duration_seconds: int,
        charging: CrystalChargingPolicy,
    ) -> PreparedCost:
        weapon = equipment.get("weapon")
        style = option.get("attack_type")
        resources: tuple[Resource, ...] = ()
        limitations: tuple[str, ...] = ()
        alternatives: tuple[ChargeAlternative, ...] = ()
        extra_assumptions: tuple[str, ...] = ()
        if option.get("powered_attack"):
            staff = review(weapon.id) if weapon else None
            recipes = (
                staff.recipes
                if staff
                else ((_CHARGES[weapon.id],) if weapon and weapon.id in _CHARGES else ())
            )
            alternatives = tuple(self._alternative(recipe) for recipe in recipes)
            priced = tuple(a for a in alternatives if a.gp_per_attack is not None)
            if priced:
                resources = min(priced, key=lambda a: a.gp_per_attack or 0).resources
            elif alternatives:
                resources = alternatives[0].resources
            else:
                limitations = ("Powered attack charge consumption has not been reviewed.",)
        elif style == "magic":
            recipe = SPELL_RECIPES.get(option.get("spell") or "")
            if recipe is None:
                limitations = ("Spell rune consumption has not been reviewed.",)
            else:
                supplied = STAFF_RUNES.get(weapon.id, frozenset()) if weapon else frozenset()
                shield = equipment.get("shield")
                tome_rune = shield.tome_effect.rune_id if shield and shield.tome_effect else None
                resources = tuple(
                    self.resource(
                        i,
                        _RUNES[i],
                        q,
                        q if i in supplied or i == tome_rune else 0,
                        weapon.name
                        if weapon and i in supplied
                        else shield.name
                        if shield and i == tome_rune
                        else None,
                    )
                    for i, q in recipe.items()
                )
                if weapon and weapon.id in {27788, 27679}:
                    resources += (self.resource(21820, "Revenant ether", 1),)
        elif style in {"ranged", "light", "standard", "heavy"}:
            resources, limitations = self._ranged(equipment)
        elif style not in {"stab", "slash", "crush"}:
            limitations = ("Attack resource consumption has not been reviewed.",)
        if weapon and weapon.id == 23987 and style in {"stab", "slash", "crush"}:
            routes: list[ChargeAlternative] = []
            if charging.method != "shards":
                coin = self.resource(995, "Coins", charging.coin_recharge_cost_gp / 2500)
                routes.append(ChargeAlternative((coin,), coin.consumed))
            if charging.method != "coins" and charging.shard_value_gp is not None:
                shard = Resource(
                    23962, "Crystal shard", 0.01, 0, None, None, charging.shard_value_gp
                )
                routes.append(ChargeAlternative((shard,), charging.shard_value_gp / 100))
            alternatives = tuple(routes)
            if alternatives:
                resources += min(alternatives, key=lambda a: a.gp_per_attack or 0).resources
            else:
                limitations += ("Crystal shard valuation is unavailable.",)
        head = equipment.get("head")
        if head and head.id == 12931:
            # Fresh continuous combat window: charge at entry and every 90 ticks.
            batches = 1 + (fight_duration_seconds * 5 - 1) // 270
            interval = weapon.attack_speed * 0.6 if weapon else 2.4
            resources += (
                self.resource(
                    12934, "Zulrah's scales", 10 * batches * interval / fight_duration_seconds
                ),
            )
            extra_assumptions = (
                f"Fresh {fight_duration_seconds}s continuous combat window: "
                "10 scales at entry and every 54 seconds; actual remaining scales unknown.",
            )
        if torag:
            limitations += ("Torag's hammers degradation and repair costs have not been reviewed.",)
        on_hit_resources = (
            (self.resource(21257, "Slayer's enchantment", 1 / 2500),)
            if on_slayer_task
            and option.get("spell") == "magic_dart"
            and not option.get("powered_attack")
            and bool(getattr(weapon, "slayer_staff_enchanted", False))
            else ()
        )
        missing = tuple(
            r.name for r in (*resources, *on_hit_resources) if r.consumed and r.unit_price is None
        )
        cost = None if limitations or missing else _resource_sum(resources)
        return PreparedCost(
            resources,
            alternatives,
            limitations,
            missing,
            cost,
            tome_assumption,
            on_hit_resources,
            _resource_sum(on_hit_resources),
            extra_assumptions,
        )

    def _alternative(self, recipe: tuple[tuple[int, int], ...]) -> ChargeAlternative:
        resources = tuple(
            self.resource(i, _RUNES.get(i, _RESOURCE_NAMES.get(i, str(i))), q) for i, q in recipe
        )
        return ChargeAlternative(resources, _resource_sum(resources))

    def _ranged(
        self, equipment: Mapping[str, EquipmentDefinition]
    ) -> tuple[tuple[Resource, ...], tuple[str, ...]]:
        weapon = equipment.get("weapon")
        ammo = equipment.get("ammunition") if weapon and weapon.ammo_for else weapon
        if (
            not weapon
            or not ammo
            or (not weapon.ammo_for and weapon.id not in THROWN_IDS)
            or (
                weapon.ammo_for
                and (not ammo.ammo_type or not ammo.ammo_type.startswith(("arrow:", "bolt:")))
            )
        ):
            return (), ("Ranged ammunition consumption has not been reviewed.",)
        cape, body = equipment.get("cape"), equipment.get("body")
        recovery, notes = recovery_rate(cape.id if cape else None, body.id if body else None)
        if recovery is None:
            return (), tuple(notes)
        quantity = 1 + PROC_CHANCE if hopper_active(weapon, equipment.get("shield"), ammo) else 1
        return (
            self.resource(
                ammo.id,
                ammo.name,
                quantity,
                quantity * recovery,
                cape.name if cape and recovery else None,
            ),
        ), ()


def aggregate_numeric_cost(roles: Sequence[tuple[float, NumericCost, float]]) -> NumericCost:
    """Retain the rich aggregator's operation order, including hour round trips."""
    active_roles = [(w, c, d) for w, c, d in roles if w > 0]
    known = bool(active_roles) and all(
        c.status == "known"
        and c.gp_per_hour is not None
        and isfinite(c.gp_per_hour)
        and c.gp_per_hour >= 0
        for _, c, _ in active_roles
    )
    weight = sum(w for w, _, _ in active_roles)
    spend = (
        sum(w * c.gp_per_hour / 3600 for w, c, _ in active_roles if c.gp_per_hour is not None)
        if known
        else None
    )
    damage = sum(w * d for w, _, d in active_roles)
    return NumericCost(
        "known" if known and damage > 0 else "unavailable",
        active_roles[0][1].gp_per_attack if len(active_roles) == 1 else None,
        spend / weight if spend is not None else None,
        spend * 3600 / weight if spend is not None else None,
        spend / damage if spend is not None and damage > 0 else None,
    )


@dataclass
class _CostScope:
    evaluators: dict[tuple[int, datetime], CostEvaluator] = field(default_factory=dict)
    # Keep the source objects alive so an identity cannot be recycled in this scope.
    sources: list[Mapping[int, PriceRecord]] = field(default_factory=list)


_ACTIVE: ContextVar[_CostScope | None] = ContextVar("compact_running_costs", default=None)


def active() -> bool:
    return _ACTIVE.get() is not None


@contextmanager
def compact_running_costs() -> Iterator[None]:
    token = _ACTIVE.set(_CostScope())
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def evaluator(prices: Mapping[int, PriceRecord], now: datetime) -> CostEvaluator:
    scope = _ACTIVE.get()
    if scope is None:
        return CostEvaluator(prices, now)
    key = (id(prices), now)
    if key not in scope.evaluators:
        scope.evaluators[key] = CostEvaluator(prices, now)
        scope.sources.append(prices)
    return scope.evaluators[key]
