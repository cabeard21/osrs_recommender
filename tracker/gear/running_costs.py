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
from tracker.gear.ammo import recovery_rate
from tracker.gear.halberd_charging import CrystalChargingPolicy
from tracker.gear.hopper import PROC_CHANCE
from tracker.gear.hopper import active as hopper_active
from tracker.gear.models import EquipmentDefinition
from tracker.gear.powered import STAFFS, review
from tracker.gear.ranged_resources import THROWN_IDS
from tracker.gear.revenant import ETHER_ID
from tracker.gear.revenant import FORMS as REVENANT_FORMS
from tracker.gear.reviewed_attacks import TORAG_USABLE_IDS
from tracker.gear.tomes import ASSUMPTION as TOME_ASSUMPTION
from tracker.gear.tomes import MARKET_FORMS as TOME_MARKET_FORMS
from tracker.gear.void_ranged import BLOOD_MOON_ARMOUR

COST_MODEL_VERSION = "ordinary-resource-cost-v11-vampyres"
UNPRICED_REPAIRS = MappingProxyType(
    {
        **dict.fromkeys(
            TORAG_USABLE_IDS, "Torag's hammers degradation and repair costs have not been reviewed."
        ),
        **dict.fromkeys(
            BLOOD_MOON_ARMOUR,
            "Blood Moon armour degradation and repair costs have not been reviewed.",
        ),
    }
)
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
    564: "Cosmic rune",
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
        "inferior_demonbane": MappingProxyType({554: 3, 562: 1}),
        "superior_demonbane": MappingProxyType({554: 5, 566: 1}),
        "dark_demonbane": MappingProxyType({554: 7, 566: 2}),
        "iban_blast": MappingProxyType({554: 5, 560: 1}),
        "magic_dart": MappingProxyType({560: 1, 558: 4}),
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


def repair_limitations(equipment: Mapping[str, EquipmentDefinition]) -> tuple[str, ...]:
    return tuple(
        sorted({UNPRICED_REPAIRS[i.id] for i in equipment.values() if i.id in UNPRICED_REPAIRS})
    )


def resource_item_ids() -> frozenset[int]:
    """Extra market scope; normal supported ammunition is already equipment-scoped."""
    from tracker.gear.potions import resource_item_ids as potion_item_ids
    from tracker.gear.powered import MARKET_FORMS

    return (
        potion_item_ids()
        | MARKET_FORMS
        | {ETHER_ID, *(form.uncharged_id for form in REVENANT_FORMS.values())}
        | TOME_MARKET_FORMS
        | frozenset({4170, 21257, 4207, 12929, 12934})
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
    if not weapon or not ammo or (not weapon.ammo_for and weapon.id not in THROWN_IDS):
        return [], ["Ranged ammunition consumption has not been reviewed."]
    if weapon.ammo_for and (
        not ammo.ammo_type or not ammo.ammo_type.startswith(("arrow:", "bolt:"))
    ):
        return [], ["Ranged ammunition consumption has not been reviewed."]
    cape, body = equipment.get("cape"), equipment.get("body")
    recovery, notes = recovery_rate(cape.id if cape else None, body.id if body else None)
    if recovery is None:
        return [], notes
    quantity = 1 + PROC_CHANCE if hopper_active(weapon, equipment.get("shield"), ammo) else 1
    return [
        _resource(
            ammo.id,
            ammo.name,
            quantity,
            quantity * recovery,
            cape.name if cape and recovery else None,
            records,
            now,
        )
    ], []


def evaluate_running_cost(
    equipment: Mapping[str, EquipmentDefinition],
    combat_option: Mapping[str, Any],
    performance: Mapping[str, Any],
    price_records: Mapping[int, PriceRecord],
    now: datetime,
    *,
    on_slayer_task: bool = False,
    fight_duration_seconds: int = 60,
    crystal_halberd_charging: CrystalChargingPolicy | None = None,
    mark_of_darkness: bool = False,
    base_magic: int | None = None,
    vampyre_target: bool = False,
) -> dict[str, Any]:
    """Value consumed resources at replacement prices, even when already owned."""
    from tracker.gear.compact_costs import active, evaluator, ring_charge_chance
    from tracker.gear.vampyres import EFARITAYS_AID

    enchanted_dart = (
        on_slayer_task
        and combat_option.get("spell") == "magic_dart"
        and not combat_option.get("powered_attack")
        and bool(getattr(equipment.get("weapon"), "slayer_staff_enchanted", False))
    )
    demonbane_cost = mark_of_darkness or any(i.id in {19675, 732} for i in equipment.values())
    weapon = equipment.get("weapon")
    vampyre_target = vampyre_target or bool(performance.get("vampyre_bonus"))
    ring = equipment.get("ring")
    if (
        active()
        or enchanted_dart
        or demonbane_cost
        or (vampyre_target and ring is not None and ring.id == EFARITAYS_AID)
        or (weapon is not None and weapon.id in REVENANT_FORMS)
        or any(i.id in {23987, 12931} for i in equipment.values())
    ):
        prepared = evaluator(price_records, now).prepare(
            equipment,
            combat_option,
            on_slayer_task=on_slayer_task,
            fight_duration_seconds=fight_duration_seconds,
            crystal_halberd_charging=crystal_halberd_charging,
            mark_of_darkness=mark_of_darkness,
            base_magic=base_magic,
            vampyre_target=vampyre_target,
        )
        accuracy = performance.get("accuracy")
        charge_chance = ring_charge_chance(performance)
        return prepared.report(
            prepared.score(
                performance.get("attack_interval"),
                performance.get("dps"),
                accuracy,
                ring_charge_probability=charge_chance,
            ),
            accuracy,
            interval=performance.get("attack_interval"),
            ring_charge_probability=charge_chance,
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
            shield = equipment.get("shield")
            tome_rune = shield.tome_effect.rune_id if shield and shield.tome_effect else None
            resources = [
                _resource(
                    item_id,
                    _RUNES[item_id],
                    quantity,
                    quantity if item_id in supplied or item_id == tome_rune else 0,
                    weapon.name
                    if weapon and item_id in supplied
                    else shield.name
                    if shield and item_id == tome_rune
                    else None,
                    price_records,
                    now,
                )
                for item_id, quantity in recipe.items()
            ]
    elif style in {"ranged", "light", "standard", "heavy"}:
        resources, reasons = _ranged_resources(equipment, price_records, now)
    elif style not in {"stab", "slash", "crush"}:
        reasons = ["Attack resource consumption has not been reviewed."]
    # Ordinary damage support does not imply reviewed repair costs.
    reasons.extend(repair_limitations(equipment))
    reasons += [
        f"No price available for {r['name']}."
        for r in resources
        if r["consumed_quantity"] and r["unit_price_gp"] is None
    ]
    cost = None if reasons else sum(r["consumed_quantity"] * r["unit_price_gp"] for r in resources)
    interval, dps = performance.get("attack_interval"), performance.get("dps")
    per_second = cost / interval if cost is not None and interval and interval > 0 else None
    assumptions = (
        ["Cheapest priced charging recipe; actual charges unknown."] if alternatives else []
    )
    if any(item.tome_effect for item in equipment.values()):
        assumptions = [*assumptions, TOME_ASSUMPTION]
    return {
        "model_version": COST_MODEL_VERSION,
        "status": "unavailable" if reasons else "known",
        "gp_per_attack": cost,
        "gp_per_second": per_second,
        "gp_per_hour": per_second * 3600 if per_second is not None else None,
        "gp_per_damage": per_second / dps if per_second is not None and dps and dps > 0 else None,
        "resources": resources,
        "charging_alternatives": alternatives,
        "charging_assumption": " ".join(assumptions) or None,
        "reasons": reasons,
    }
