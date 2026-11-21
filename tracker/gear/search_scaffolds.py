"""Protect complete vampyre attack combinations and Elite Void ranged equipment."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from tracker.content.schema import ItemSlot
from tracker.gear.vampyre_combat import target_tier
from tracker.gear.vampyres import (
    BLISTERWOOD_STAKE,
    EFARITAYS_AID,
    RODS,
    SILVER_BOLTS,
    SILVER_WEAPONS,
    SPECIALISTS,
)
from tracker.gear.void_ranged import ELITE_ROBES, ELITE_TOPS, RANGER_HELMS, VOID_GLOVES

if TYPE_CHECKING:
    from tracker.gear.optimizer import RoleConfig, _Search


def tier(role: RoleConfig) -> int:
    return target_tier(role.target.traits) if role.target and role.style != "special" else 0


_VOID_SLOTS: dict[ItemSlot, frozenset[int]] = {
    "head": RANGER_HELMS,
    "body": ELITE_TOPS,
    "legs": ELITE_ROBES,
    "hands": VOID_GLOVES,
}


def elite_void_seed(search: _Search, roles: tuple[RoleConfig, ...]) -> dict[str, int]:
    """Equivalent cosmetic pieces can each enter later; start with one affordable set."""
    if not any(r.style == "ranged" for r in roles):
        return {}
    locks = [{**search.request.locks, **r.locks} for r in roles]
    equipment: dict[str, int] = {}
    for slot, forms in _VOID_SLOTS.items():
        available = [
            i for i in forms if i in search.eligible and all(row.get(slot, i) == i for row in locks)
        ]
        if not available:
            return {}
        equipment[slot] = min(available, key=search.budget_item_rank)
    return equipment


def contextual_candidates(search: _Search, slot: ItemSlot, ordered: Sequence[int]) -> list[int]:
    if slot in _VOID_SLOTS and any(r.style == "ranged" for r in search.request.roles):
        return [i for i in ordered if i in _VOID_SLOTS[slot]]
    if slot not in {"weapon", "ring", "ammunition"}:
        return []
    roles = [(r.style, n) for r in search.request.roles if (n := tier(r))]
    if not roles:
        return []
    ranged_silver = any(style == "ranged" and n < 3 for style, n in roles)
    ammo_types = {
        search.eligible[i].ammo_type for i in SILVER_BOLTS if i in search.eligible and ranged_silver
    }
    possible = {EFARITAYS_AID}
    # A very small pool can fill up with the cheapest item before reaching
    # the damage leader. Preserve the weapon/ammo that won on a legal scaffold.
    if ordered and slot in {"weapon", "ammunition"}:
        for role in search.request.roles:
            if tier(role) == 2 and (slot == "weapon" or role.style == "ranged"):
                best = max(ordered, key=lambda i: search.marginals.get((role.id, i), -1))
                if search.marginals.get((role.id, best), -1) >= 0:
                    possible.add(best)
    for style, n in roles:
        if style == "ranged":
            possible.add(BLISTERWOOD_STAKE)
            if n < 3:
                possible.update(SILVER_BOLTS)
        elif style in {"slash", "crush", "stab"}:
            melee_specialists = set(SPECIALISTS) - {BLISTERWOOD_STAKE}
            possible.update(
                melee_specialists - RODS if n == 3 else melee_specialists | SILVER_WEAPONS | RODS
            )
    return [
        i
        for i in ordered
        if i in possible
        or (slot == "weapon" and not ammo_types.isdisjoint(search.eligible[i].ammo_for))
    ]


def vampyre_seeds(search: _Search, roles: tuple[RoleConfig, ...]) -> list[dict[str, int]]:
    """Start with optional attack-enabling slots before the beam visits the weapon."""
    if not any(tier(r) == 2 for r in roles):
        return []
    locks = [{**search.request.locks, **r.locks} for r in roles]
    seeds = []
    if EFARITAYS_AID in search.eligible and all(
        row.get("ring", EFARITAYS_AID) == EFARITAYS_AID for row in locks
    ):
        seeds.append({"ring": EFARITAYS_AID})
    if any(r.style == "ranged" and tier(r) == 2 for r in roles):
        seeds.extend(
            {"ammunition": i}
            for i in sorted(SILVER_BOLTS)
            if i in search.eligible and all(row.get("ammunition", i) == i for row in locks)
        )
    return seeds


def attack_seeds(
    search: _Search, roles: tuple[RoleConfig, ...], *, best_only: bool = False
) -> list[dict[str, int]]:
    seeds = vampyre_seeds(search, roles)
    if best_only and seeds:
        # The joint role beam takes a Cartesian product. A single unlocked ring
        # covers all ordinary weapons; a silver bolt covers the crossbow-only case.
        seeds = seeds[:1]
    elite = elite_void_seed(search, roles)
    if elite:
        return [*seeds, elite, *({**seed, **elite} for seed in seeds)]
    return seeds


def no_solution_hints(roles: tuple[RoleConfig, ...]) -> list[str]:
    hints = []
    for role in roles:
        n = tier(role)
        if n == 2:
            hints.append(
                f"{role.id}: check weapon, ammunition and ring locks. A tier 2 vampyre requires "
                "a silver attack, an Ivandis or stronger vampyrebane attack, or Efaritay's aid."
            )
        elif n == 3:
            hints.append(
                f"{role.id}: check weapon and style locks. For a tier 3 vampyre choose a "
                "qualifying vampyrebane melee weapon or throw blisterwood stakes."
            )
    return hints
