"""Whole-trip loss lookup and risk-aware candidate selection for vector search."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from tracker.gear.ammo import CAPE_RECOVERY
from tracker.gear.running_costs import STAFF_RUNES

if TYPE_CHECKING:
    from tracker.gear.vector_options import OptionVariant


def trip_loss_lookup(
    search: Any,
    assignment: Mapping[str, Mapping[str, int]],
) -> Callable[[tuple[OptionVariant, ...]], int | None]:
    """Cache the loss of one gear assignment across equivalent attack and prayer choices."""

    @lru_cache(maxsize=256)
    def measure(attacks: tuple[tuple[str, str | None, str | None] | None, ...]) -> int | None:
        options = {
            role.id: {"attack_type": attack[0], "spell": attack[1], "powered_attack": attack[2]}
            if attack
            else None
            for role, attack in zip(search.request.roles, attacks, strict=True)
        }
        report = search.trip_report(assignment, options)
        if report is None or not search.trip_fits(report):
            return None
        return int(report["loss_gp"])

    def loss(variants: tuple[OptionVariant, ...]) -> int | None:
        return measure(
            tuple(
                (option.attack_type, option.spell, option.powered_attack)
                if (option := variant.option)
                else None
                for variant in variants
            )
        )

    return loss


def supply_saving_lanes(search: Any, slot: str, candidates: list[int]) -> Iterator[list[int]]:
    """Supply-saving equipment can offset its own loss on death."""
    roles = search.request.roles
    if slot == "cape" and any(role.style == "ranged" for role in roles):
        yield sorted(
            (item for item in candidates if item in CAPE_RECOVERY),
            key=lambda item: (-CAPE_RECOVERY[item], search.budget_item_rank(item)),
        )
    if slot in {"weapon", "shield"} and any(role.style == "magic" for role in roles):
        families: dict[frozenset[int], list[int]] = {}
        for item in candidates:
            tome = search.items[item].tome_effect
            runes = frozenset({tome.rune_id}) if tome else STAFF_RUNES.get(item)
            if runes:
                families.setdefault(runes, []).append(item)
        for family in families.values():
            yield sorted(family, key=search.budget_item_rank)
