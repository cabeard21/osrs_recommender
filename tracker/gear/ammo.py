"""Finite fixed-bow arrow/cape comparisons; prices represent replacement cost."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tracker.gear.ammo_armour import COMPATIBLE_BODIES, INTERFERING_BODIES
from tracker.gear.facts import hypothetical_snapshot

# Reviewed ordinary physical forms, not ownership aliases.
ARROWS = frozenset({882, 884, 886, 888, 890, 892, 21326, 4160, 33601})
AVA_RECOVERY = {10498: 0.60, 10499: 0.72, 22109: 0.80}
# Recovery-capable cape exceptions, including physical cosmetic/locked variants.
# https://oldschool.runescape.wiki/w/Ava%27s_device
# https://oldschool.runescape.wiki/w/Ranging_cape
# https://oldschool.runescape.wiki/w/Dizana%27s_quiver
# Reviewed against the bundled cape catalog 2026-11-02. Other capes have no recovery.
CAPE_RECOVERY = {
    **AVA_RECOVERY,
    13337: 0.72,  # Accumulator max cape
    **dict.fromkeys(
        (21914, 24222, 21916, 24135, 21898, 27359, 27376, 27374, 27361, 27365, 27363),
        0.80,
    ),
}
UPGRADE_DEPENDENT_CAPES = frozenset(
    {9756, 9757, 13342, 28828, 28957, 28955, 28830, 28906, 28902, 28951, 28947}
)


def cape_recovery_rate(cape: int | None) -> tuple[float | None, list[str]]:
    if cape is None:
        return 0.0, []
    if cape in UPGRADE_DEPENDENT_CAPES:
        return None, ["Ammo recovery depends on an unobserved cape upgrade."]
    return CAPE_RECOVERY.get(cape, 0.0), []


def recovery_rate(cape: int | None, body: int | None) -> tuple[float | None, list[str]]:
    rate, notes = cape_recovery_rate(cape)
    if rate is None or rate == 0:
        return rate, notes
    if body in INTERFERING_BODIES:
        return 0.0, ["Metal body armour blocks Ava's ammunition recovery."]
    if body is not None and body not in COMPATIBLE_BODIES:
        return None, ["Ava's interference for this body armour has not been reviewed."]
    return rate, notes


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


def _within_dps_limit(
    points: list[dict[str, Any]], cap: float
) -> tuple[list[dict[str, Any]], list[str]]:
    valid = [p for p in points if p["dps"] is not None]
    best = max((p["dps"] for p in valid), default=0)
    measured = [{**p, "dps_loss_pct": 100 * (best - p["dps"]) / best if best else 0} for p in valid]
    visible = [p for p in measured if p["dps_loss_pct"] <= cap]
    notes = [f"Showing setups within {cap:g}% DPS loss of the highest valid arrow comparison."]
    invalid = [p for p in points if p["dps"] is None]
    if invalid:
        reasons = list(dict.fromkeys(r for p in invalid for r in p["reasons"]))
        notes.append(f"Excluded {len(invalid)} invalid or unsupported setups. " + " ".join(reasons))
    if not valid:
        notes.append("No valid arrow setups are available for this scenario.")
    return mark_frontier(visible), notes


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
            if price["amount_gp"] is None:
                reasons.append(f"No price available for {catalog.items[ammo].name}.")
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
    return _within_dps_limit(points, scenario.max_dps_loss_pct)
