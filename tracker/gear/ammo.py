"""Finite fixed-bow arrow/cape comparisons; prices represent replacement cost."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tracker.gear.ammo_armour import COMPATIBLE_BODIES, INTERFERING_BODIES
from tracker.gear.facts import hypothetical_snapshot

# Reviewed ordinary physical forms, not ownership aliases.
ARROWS = frozenset({882, 884, 886, 888, 890, 892, 21326})
AVA_RECOVERY = {10498: 0.60, 10499: 0.72, 22109: 0.80}


def recovery_rate(cape: int | None, body: int | None) -> tuple[float | None, list[str]]:
    if cape is None:
        return 0.0, []
    if cape not in AVA_RECOVERY:
        return None, ["Ammo recovery for this cape has not been reviewed."]
    if body in INTERFERING_BODIES:
        return 0.0, ["Metal body armour blocks Ava's ammunition recovery."]
    if body is not None and body not in COMPATIBLE_BODIES:
        return None, ["Ava's interference for this body armour has not been reviewed."]
    return AVA_RECOVERY[cape], []


def running_cost(
    interval: float | None, dps: float | None, recovery: float | None, unit_price: int | None
) -> dict[str, float | None]:
    lost = 3600 / interval * (1 - recovery) if interval and recovery is not None else None
    gp = lost * unit_price if lost is not None and unit_price is not None else None
    return {
        "arrows_lost_per_hour": lost,
        "gp_per_hour": gp,
        "gp_per_damage": gp / (dps * 3600) if gp is not None and dps else None,
    }


def mark_frontier(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = [p for p in points if p["dps"] is not None and p["gp_per_hour"] is not None]
    return [
        {
            **p,
            "frontier": p in known
            and not any(
                q["dps"] >= p["dps"]
                and q["gp_per_hour"] <= p["gp_per_hour"]
                and (q["dps"] > p["dps"] or q["gp_per_hour"] < p["gp_per_hour"])
                for q in known
            ),
        }
        for p in points
    ]


def compare_arrows(
    snapshot: Any,
    gear: Any,
    prices: Any,
    scenario: Any,
    loadout: Mapping[str, int],
    option: dict[str, Any],
    now: Any,
    stopped: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    catalog = gear.equipment_catalog()
    weapon = catalog.items.get(loadout.get("weapon"))
    if (
        weapon is None
        or not weapon.ammo_for
        or not any(a.startswith("arrow:") for a in weapon.ammo_for)
    ):
        return [], ["Arrow comparison requires a supported bow using ordinary arrows."]
    arrows = [
        i
        for i in sorted(ARROWS | {loadout.get("ammunition", -1)})
        if i in catalog.items and catalog.items[i].ammo_type in weapon.ammo_for
    ]
    capes = sorted(set(AVA_RECOVERY) | {loadout.get("cape")}, key=lambda x: x or 0)
    if None not in capes:
        capes.insert(0, None)
    points: list[dict[str, Any]] = []
    projected = hypothetical_snapshot(
        snapshot, scenario.skill_overrides, scenario.quest_overrides, now
    )
    for ammo in arrows:
        for cape in capes:
            if stopped.is_set():
                raise ValueError("evaluation_cancelled")
            if cape is not None and cape not in catalog.items:
                continue
            equipment = {k: v for k, v in loadout.items() if k != "cape"}
            equipment = {**equipment, "ammunition": ammo, **({"cape": cape} if cape else {})}
            result = gear.evaluate(
                snapshot,
                scenario,
                loadout,
                equipment,
                price_records=prices,
                now=now,
                cancelled=stopped.is_set,
                baseline_combat_option=option,
                proposed_combat_option=option,
            )["proposed"]
            performance = result.get("performance") or {}
            reasons = [r["message"] for r in result["reasons"]]
            # A non-ranged resolved Auto configuration must not receive arrow costs.
            if result.get("discipline") not in {None, "ranged"}:
                performance = {}
                reasons.append("Selected combat option must be ranged.")
            rate, notes = recovery_rate(cape, loadout.get("body"))
            if ammo not in ARROWS:
                performance = {}
                reasons.append("This arrow is outside reviewed running-cost support.")
            price = gear.physical_item(
                projected,
                ammo,
                price_records=prices,
                now=now,
                support_policy=scenario.support_policy,
            )["price"]
            points.append(
                {
                    "ammo_id": ammo,
                    "ammo_name": catalog.items[ammo].name,
                    "cape_id": cape,
                    "cape_name": catalog.items[cape].name if cape else "No cape",
                    "dps": performance.get("dps"),
                    "attack_interval": performance.get("attack_interval"),
                    "recovery_rate": rate,
                    "price": price,
                    "reasons": reasons + notes,
                    "current": equipment == loadout,
                    **running_cost(
                        performance.get("attack_interval"),
                        performance.get("dps"),
                        rate,
                        price["amount_gp"],
                    ),
                }
            )
    return mark_frontier(points), []
