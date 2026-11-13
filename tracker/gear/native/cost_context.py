"""Freeze resource recipes and prices before native candidate expansion."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import Any

from tracker.gear.ammo import cape_recovery_rate
from tracker.gear.ammo_armour import COMPATIBLE_BODIES, INTERFERING_BODIES
from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.ranged_resources import THROWN_IDS
from tracker.gear.reviewed_attacks import TORAG_USABLE_IDS


@dataclass(frozen=True)
class CostData:
    option_kind: array[int]
    option_cost: array[float]
    option_on_hit_cost: array[float]
    ranged_kind: array[int]
    ammo_valid: array[int]
    unit_prices: array[float]
    recovery: array[float]
    body_recovery: array[int]
    torag: array[int]
    supply_class: array[int]
    supply_count: int


def pack_costs(search: Any, scoring: Any) -> CostData:
    evaluator = CostEvaluator(search.running_prices, search.running_at)
    # Rune supply depends on the physical shield, independently of whether its
    # damage effect matches the spell. Deduplicate by rune identity, not element.
    suppliers = {
        item.tome_effect.rune_id: item
        for item_id in scoring.dense_ids[1:]
        if (item := search.items[item_id]).slot == "shield" and item.tome_effect
    }
    supply_ids = (0, *sorted(suppliers))
    supply_indices = {rune: index for index, rune in enumerate(supply_ids)}
    supply_class = array("i", [0])
    for item_id in scoring.dense_ids[1:]:
        item = search.items[item_id]
        supply_class.append(
            supply_indices[item.tome_effect.rune_id]
            if item.slot == "shield" and item.tome_effect
            else 0
        )
    option_kind, option_cost, option_on_hit_cost = array("i"), array("d"), array("d")
    for (configured, option), weapon_id in zip(
        scoring.option_records, scoring.option_weapons, strict=True
    ):
        ranged = option.attack_type in {"ranged", "light", "standard", "heavy"}
        option_kind.append(int(ranged))
        weapon = search.items.get(weapon_id)
        for rune in supply_ids:
            equipment = {
                **({"weapon": weapon} if weapon else {}),
                **({"shield": suppliers[rune]} if rune else {}),
            }
            recipe = evaluator.prepare(
                equipment,
                option.model_dump(),
                on_slayer_task=getattr(configured, "on_slayer_task", False),
            )
            option_cost.append(recipe.gp_per_attack if recipe.gp_per_attack is not None else -1)
            option_on_hit_cost.append(recipe.on_hit_cost if recipe.on_hit_cost is not None else -1)
    ranged_kind, ammo_valid = array("i", [0]), array("i", [0])
    unit_prices, recovery = array("d", [-1]), array("d", [0])
    body_recovery, torag = array("i", [0]), array("i", [0])
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
        # Only positive, known cape recovery consults this body classification.
        # 0 = absent/non-body, 1 = compatible, 2 = interfering, 3 = unreviewed.
        body_recovery.append(
            0
            if item.slot != "body"
            else 2
            if item_id in INTERFERING_BODIES
            else 1
            if item_id in COMPATIBLE_BODIES
            else 3
        )
        torag.append(int(item_id in TORAG_USABLE_IDS))
    return CostData(
        option_kind,
        option_cost,
        option_on_hit_cost,
        ranged_kind,
        ammo_valid,
        unit_prices,
        recovery,
        body_recovery,
        torag,
        supply_class,
        len(supply_ids),
    )
