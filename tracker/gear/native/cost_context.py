"""Freeze resource recipes and prices before native candidate expansion."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import Any

from tracker.gear.ammo import cape_recovery_rate
from tracker.gear.ammo_armour import INTERFERING_BODIES
from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.ranged_resources import THROWN_IDS
from tracker.gear.reviewed_attacks import TORAG_USABLE_IDS


@dataclass(frozen=True)
class CostData:
    option_kind: array[int]
    option_cost: array[float]
    ranged_kind: array[int]
    ammo_valid: array[int]
    unit_prices: array[float]
    recovery: array[float]
    interference: array[int]
    torag: array[int]


def pack_costs(search: Any, scoring: Any) -> CostData:
    evaluator = CostEvaluator(search.running_prices, search.running_at)
    option_kind, option_cost = array("i"), array("d")
    for (_, option), weapon_id in zip(scoring.option_records, scoring.option_weapons, strict=True):
        ranged = option.attack_type in {"ranged", "light", "standard", "heavy"}
        option_kind.append(int(ranged))
        weapon = search.items.get(weapon_id)
        recipe = evaluator.prepare({"weapon": weapon} if weapon else {}, option.model_dump())
        option_cost.append(recipe.gp_per_attack if recipe.gp_per_attack is not None else -1)
    ranged_kind, ammo_valid = array("i", [0]), array("i", [0])
    unit_prices, recovery = array("d", [-1]), array("d", [0])
    interference, torag = array("i", [0]), array("i", [0])
    for item_id in scoring.dense_ids[1:]:
        item = search.items[item_id]
        ranged_kind.append(1 if item.ammo_for else 2 if item_id in THROWN_IDS else 0)
        ammo_valid.append(
            int(bool(item.ammo_type and item.ammo_type.startswith(("arrow:", "bolt:"))))
        )
        quote = evaluator.resource(item_id, item.name, 1).unit_price
        unit_prices.append(quote if quote is not None else -1)
        rate, _ = cape_recovery_rate(item_id)
        recovery.append(rate if rate is not None else -1)
        interference.append(int(item.slot == "body" and item_id in INTERFERING_BODIES))
        torag.append(int(item_id in TORAG_USABLE_IDS))
    return CostData(
        option_kind,
        option_cost,
        ranged_kind,
        ammo_valid,
        unit_prices,
        recovery,
        interference,
        torag,
    )
