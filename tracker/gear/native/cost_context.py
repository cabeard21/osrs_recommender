"""Freeze resource recipes and prices before native candidate expansion."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import Any

from tracker.gear.ammo import cape_recovery_rate
from tracker.gear.ammo_armour import COMPATIBLE_BODIES, INTERFERING_BODIES
from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.halberd_charging import cost_context
from tracker.gear.ranged_resources import THROWN_IDS
from tracker.gear.revenant import CHARGED_BOWS
from tracker.gear.running_costs import UNPRICED_REPAIRS


@dataclass(frozen=True)
class CostData:
    option_kind: array[int]
    option_cost: array[float]
    option_on_hit_cost: array[float]
    option_per_second_cost: array[float]
    ranged_kind: array[int]
    ammo_valid: array[int]
    unit_prices: array[float]
    recovery: array[float]
    body_recovery: array[int]
    unpriced_repair: array[int]
    supply_class: array[int]
    supply_count: int
    serp_head: array[int]
    serp_cost: array[float]


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
    serp_cost = array("d")
    scale_price = evaluator.resource(12934, "Zulrah's scales", 1).unit_price
    option_kind, option_cost, option_on_hit_cost = array("i"), array("d"), array("d")
    option_per_second_cost = array("d")
    for (configured, option), weapon_id in zip(
        scoring.option_records, scoring.option_weapons, strict=True
    ):
        duration = getattr(configured, "fight_duration_seconds", 60)
        batches = 1 + (duration * 5 - 1) // 270
        ranged = option.attack_type in {"ranged", "light", "standard", "heavy"}
        # Internally supplied bows use their pre-priced ether recipe for every shot.
        option_kind.append(int(ranged and weapon_id not in CHARGED_BOWS))
        weapon = search.items.get(weapon_id)
        base_interval = weapon.attack_speed * 0.6 if weapon else 2.4
        serp_cost.append(
            (10 * batches * base_interval / duration) * scale_price
            if scale_price is not None
            else -1
        )
        for rune in supply_ids:
            equipment = {
                **({"weapon": weapon} if weapon else {}),
                **({"shield": suppliers[rune]} if rune else {}),
            }
            recipe = evaluator.prepare(
                equipment,
                option.model_dump(),
                on_slayer_task=getattr(configured, "on_slayer_task", False),
                mark_of_darkness=getattr(configured, "mark_of_darkness", False),
                base_magic=search.snapshot.skills["magic"].level
                if getattr(configured, "mark_of_darkness", False)
                and "magic" in search.snapshot.skills
                else None,
                **cost_context(getattr(search, "request", None), configured),
            )
            option_cost.append(recipe.gp_per_attack if recipe.gp_per_attack is not None else -1)
            option_on_hit_cost.append(recipe.on_hit_cost if recipe.on_hit_cost is not None else -1)
            option_per_second_cost.append(
                recipe.per_second_cost if recipe.per_second_cost is not None else -1
            )
    ranged_kind, ammo_valid = array("i", [0]), array("i", [0])
    unit_prices, recovery = array("d", [-1]), array("d", [0])
    body_recovery, unpriced_repair = array("i", [0]), array("i", [0])
    for item_id in scoring.dense_ids[1:]:
        item = search.items[item_id]
        ranged_kind.append(
            3 if item_id == 732 else 1 if item.ammo_for else 2 if item_id in THROWN_IDS else 0
        )
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
        unpriced_repair.append(int(item_id in UNPRICED_REPAIRS))
    return CostData(
        option_kind,
        option_cost,
        option_on_hit_cost,
        option_per_second_cost,
        ranged_kind,
        ammo_valid,
        unit_prices,
        recovery,
        body_recovery,
        unpriced_repair,
        supply_class,
        len(supply_ids),
        array("i", [0, *(int(i == 12931) for i in scoring.dense_ids[1:])]),
        serp_cost,
    )
