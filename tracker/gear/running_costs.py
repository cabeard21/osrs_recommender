"""Pure ordinary-attack resource costs over the request's frozen market snapshot.

Recipes: https://oldschool.runescape.wiki/w/Combat_spells
Coverage: https://oldschool.runescape.wiki/w/Elemental_staff
Recovery: https://oldschool.runescape.wiki/w/Ava%27s_device
No ground collection, special attacks, rune substitutions or combat downtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any

from tracker.estimation.prices import PriceRecord, resolve_price
from tracker.gear.ammo import cape_recovery_rate
from tracker.gear.models import EquipmentDefinition
from tracker.gear.powered import STAFFS, review
from tracker.gear.reviewed_attacks import TORAG_USABLE_IDS

COST_MODEL_VERSION = "ordinary-resource-cost-v3"
_RESOURCE_NAMES = {
    995: "Coins",
    12934: "Zulrah's scales",
    21820: "Revenant ether",
    31111: "Demon tear",
}
_RUNES = {
    556: "Air rune",
    555: "Water rune",
    557: "Earth rune",
    554: "Fire rune",
    558: "Mind rune",
    562: "Chaos rune",
    560: "Death rune",
    565: "Blood rune",
    566: "Soul rune",
    21880: "Wrath rune",
}
# Air quantity for wind/water/earth/fire, then elemental quantity for water/earth/fire.
_TIERS = {
    "strike": (558, (1, 1, 1, 2), (1, 2, 3)),
    "bolt": (562, (2, 2, 2, 3), (2, 3, 4)),
    "blast": (560, (3, 3, 3, 4), (3, 4, 5)),
    "wave": (565, (5, 5, 5, 5), (7, 7, 7)),
    "surge": (21880, (7, 7, 7, 7), (10, 10, 10)),
}
SPELL_RECIPES = MappingProxyType(
    {
        "iban_blast": MappingProxyType({554: 5, 560: 1}),
        # Exact per-cast Ancient combat recipes; splash/AoE outcomes do not
        # change rune consumption. https://oldschool.runescape.wiki/w/Ancient_Magicks
        **{
            spell: MappingProxyType(recipe)
            for spell, recipe in {
                "smoke_rush": {554: 1, 556: 1, 562: 2, 560: 2},
                "shadow_rush": {556: 1, 566: 1, 562: 2, 560: 2},
                "blood_rush": {565: 1, 562: 2, 560: 2},
                "ice_rush": {555: 2, 562: 2, 560: 2},
                "smoke_burst": {554: 2, 556: 2, 562: 4, 560: 2},
                "shadow_burst": {556: 1, 566: 2, 562: 4, 560: 2},
                "blood_burst": {565: 2, 562: 4, 560: 2},
                "ice_burst": {555: 4, 562: 4, 560: 2},
                "smoke_blitz": {554: 2, 556: 2, 565: 2, 560: 2},
                "shadow_blitz": {556: 2, 566: 2, 565: 2, 560: 2},
                "blood_blitz": {565: 4, 560: 2},
                "ice_blitz": {555: 3, 565: 2, 560: 2},
                "smoke_barrage": {554: 4, 556: 4, 565: 2, 560: 4},
                "shadow_barrage": {556: 4, 566: 3, 565: 2, 560: 4},
                "blood_barrage": {565: 4, 560: 4, 566: 1},
                "ice_barrage": {555: 6, 565: 2, 560: 4},
            }.items()
        },
        **{
            f"{element}_{tier}": MappingProxyType(
                {
                    catalyst: 1,
                    556: air[index],
                    **({rune: elements[index - 1]} if index else {}),
                }
            )
            for tier, (catalyst, air, elements) in _TIERS.items()
            for index, (element, rune) in enumerate(
                (("wind", 556), ("water", 555), ("earth", 557), ("fire", 554))
            )
        },
    }
)
STAFF_RUNES = MappingProxyType(
    {
        **{item: frozenset({556}) for item in (1381, 1397, 1405)},
        **{item: frozenset({555}) for item in (1383, 1395, 1403)},
        **{item: frozenset({557}) for item in (1385, 1399, 1407)},
        **{item: frozenset({554}) for item in (1387, 1393, 1401)},
        **{item: frozenset({557, 554}) for item in (3053, 3054)},
        **{item: frozenset({557, 555}) for item in (6562, 6563)},
        **{item: frozenset({555, 554}) for item in (11787, 11789)},
        **{item: frozenset({556, 554}) for item in (11998, 12000)},
        **{item: frozenset({556, 555}) for item in (20730, 20733)},
        **{item: frozenset({556, 557}) for item in (20736, 20739)},
    }
)
# Exact ordinary charged forms only. This metadata does not certify damage support.
# https://oldschool.runescape.wiki/w/Trident_of_the_seas
# https://oldschool.runescape.wiki/w/Trident_of_the_swamp
# https://oldschool.runescape.wiki/w/Warped_sceptre
_CHARGES = MappingProxyType(
    {
        11905: ((554, 5), (562, 1), (560, 1), (995, 10)),
        11907: ((554, 5), (562, 1), (560, 1), (995, 10)),
        12899: ((554, 5), (562, 1), (560, 1), (12934, 1)),
        28583: ((557, 5), (562, 2)),
    }
)
# Ordinary darts, knives, thrownaxes and javelins. Exotic ranged resources need review.
_THROWN = frozenset(
    {
        *range(806, 812),
        *range(863, 870),
        *range(800, 806),
        *range(825, 831),
        11230,
        11233,
        22804,
        22806,
        22808,
        22810,
        22812,
        22814,
        22816,
    }
)


def resource_item_ids() -> frozenset[int]:
    """Extra market scope; normal supported ammunition is already equipment-scoped."""
    from tracker.gear.potions import resource_item_ids as potion_item_ids
    from tracker.gear.powered import MARKET_FORMS

    return (
        potion_item_ids()
        | MARKET_FORMS
        | frozenset(_RUNES)
        | frozenset(
            i for staff in STAFFS for recipe in staff.recipes for i, _ in recipe if i != 995
        )
    )


def _resource(
    item_id: int,
    name: str,
    quantity: float,
    supplied: float,
    supplier: str | None,
    records: Mapping[int, PriceRecord],
    now: datetime,
) -> dict[str, Any]:
    consumed = quantity - supplied
    quote = (
        resolve_price(None, records.get(item_id), now=now) if consumed and item_id != 995 else None
    )
    return {
        "item_id": item_id,
        "name": name,
        "required_quantity": quantity,
        "consumed_quantity": consumed,
        "supplied_quantity": supplied,
        "supplied_by": supplier,
        "unit_price_gp": 1 if item_id == 995 else quote.gp if quote else 0,
        "price_layer": "fixed" if item_id == 995 else quote.layer.value if quote else "free",
        "price_confidence": str(quote.confidence) if quote else None,
        "price_trade_at": quote.trade_at.isoformat() if quote and quote.trade_at else None,
    }


def _ranged_resources(
    equipment: Mapping[str, EquipmentDefinition], records: Mapping[int, PriceRecord], now: datetime
) -> tuple[list[dict[str, Any]], list[str]]:
    weapon = equipment.get("weapon")
    ammo = equipment.get("ammunition") if weapon and weapon.ammo_for else weapon
    if not weapon or not ammo or (not weapon.ammo_for and weapon.id not in _THROWN):
        return [], ["Ranged ammunition consumption has not been reviewed."]
    if weapon.ammo_for and (
        not ammo.ammo_type or not ammo.ammo_type.startswith(("arrow:", "bolt:"))
    ):
        return [], ["Ranged ammunition consumption has not been reviewed."]
    cape, body = equipment.get("cape"), equipment.get("body")
    recovery, notes = cape_recovery_rate(cape.id if cape else None)
    if recovery is None:
        return [], notes
    # Negative-Ranged metal body armour interferes with Ava's device. Applying
    # this restriction conservatively also avoids crediting unknown interference.
    if body and body.bonuses.ranged < 0:
        recovery = 0
    return [
        _resource(
            ammo.id, ammo.name, 1, recovery, cape.name if cape and recovery else None, records, now
        )
    ], []


def evaluate_running_cost(
    equipment: Mapping[str, EquipmentDefinition],
    combat_option: Mapping[str, Any],
    performance: Mapping[str, Any],
    price_records: Mapping[int, PriceRecord],
    now: datetime,
) -> dict[str, Any]:
    """Value consumed resources at replacement prices, even when already owned."""
    from tracker.gear.compact_costs import active, evaluator

    if active():
        prepared = evaluator(price_records, now).prepare(equipment, combat_option)
        return prepared.report(
            prepared.score(performance.get("attack_interval"), performance.get("dps"))
        )
    style = combat_option.get("attack_type")
    resources: list[dict[str, Any]] = []
    reasons: list[str] = []
    alternatives: list[dict[str, Any]] = []
    if combat_option.get("powered_attack"):
        weapon = equipment.get("weapon")
        staff = review(weapon.id) if weapon else None
        recipes = (
            staff.recipes
            if staff
            else ((_CHARGES[weapon.id],) if weapon and weapon.id in _CHARGES else ())
        )
        for charge_recipe in recipes:
            rows = [
                _resource(
                    i,
                    _RUNES.get(i, _RESOURCE_NAMES.get(i, str(i))),
                    quantity,
                    0,
                    None,
                    price_records,
                    now,
                )
                for i, quantity in charge_recipe
            ]
            known = all(r["unit_price_gp"] is not None for r in rows)
            alternatives.append(
                {
                    "resources": rows,
                    "gp_per_attack": sum(r["consumed_quantity"] * r["unit_price_gp"] for r in rows)
                    if known
                    else None,
                }
            )
        priced = [a for a in alternatives if a["gp_per_attack"] is not None]
        if priced:
            resources = min(priced, key=lambda a: a["gp_per_attack"])["resources"]
        elif alternatives:
            resources = alternatives[0]["resources"]
        else:
            reasons = ["Powered attack charge consumption has not been reviewed."]
    elif style == "magic":
        recipe = SPELL_RECIPES.get(combat_option.get("spell") or "")
        if recipe is None:
            reasons = ["Spell rune consumption has not been reviewed."]
        else:
            weapon = equipment.get("weapon")
            supplied = STAFF_RUNES.get(weapon.id, frozenset()) if weapon else frozenset()
            resources = [
                _resource(
                    item_id,
                    _RUNES[item_id],
                    quantity,
                    quantity if item_id in supplied else 0,
                    weapon.name if weapon and item_id in supplied else None,
                    price_records,
                    now,
                )
                for item_id, quantity in recipe.items()
            ]
            # Charged autocasting sceptres consume ether as well as spell runes.
            # Their uncharged (a) forms can autocast without the ether effect.
            if weapon and weapon.id in {27788, 27679}:
                resources = [
                    *resources,
                    _resource(21820, "Revenant ether", 1, 0, None, price_records, now),
                ]
    elif style in {"ranged", "light", "standard", "heavy"}:
        resources, reasons = _ranged_resources(equipment, price_records, now)
    elif style not in {"stab", "slash", "crush"}:
        reasons = ["Attack resource consumption has not been reviewed."]
    # Ordinary damage support does not imply reviewed repair costs.
    if any(item.id in TORAG_USABLE_IDS for item in equipment.values()):
        reasons.append("Torag's hammers degradation and repair costs have not been reviewed.")
    reasons += [
        f"No price available for {r['name']}."
        for r in resources
        if r["consumed_quantity"] and r["unit_price_gp"] is None
    ]
    cost = None if reasons else sum(r["consumed_quantity"] * r["unit_price_gp"] for r in resources)
    interval, dps = performance.get("attack_interval"), performance.get("dps")
    per_second = cost / interval if cost is not None and interval and interval > 0 else None
    return {
        "model_version": COST_MODEL_VERSION,
        "status": "unavailable" if reasons else "known",
        "gp_per_attack": cost,
        "gp_per_second": per_second,
        "gp_per_hour": per_second * 3600 if per_second is not None else None,
        "gp_per_damage": per_second / dps if per_second is not None and dps and dps > 0 else None,
        "resources": resources,
        "charging_alternatives": alternatives,
        "charging_assumption": "Cheapest priced charging recipe; actual charges unknown."
        if alternatives
        else None,
        "reasons": reasons,
    }
