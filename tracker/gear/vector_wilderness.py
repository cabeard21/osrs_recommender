"""Whole-trip loss lookup and risk-aware candidate selection for vector search."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from tracker.gear.ammo import CAPE_RECOVERY
from tracker.gear.running_costs import STAFF_RUNES
from tracker.gear.wilderness_runes import wilderness_spell_runes
from tracker.gear.wilderness_trip import trip_resources

if TYPE_CHECKING:
    from tracker.gear.vector_options import OptionVariant

type TripOptions = Mapping[str, Mapping[str, Any] | None]


def trip_loss_lookup(
    search: Any,
    assignment: Mapping[str, Mapping[str, int]],
) -> Callable[[tuple[OptionVariant, ...]], int | None]:
    """Cache the loss of one gear assignment across equivalent attack and prayer choices."""

    numeric = _numeric_trip_loss(search, assignment)

    @lru_cache(maxsize=256)
    def measure(attacks: tuple[tuple[str, str | None, str | None] | None, ...]) -> int | None:
        options = {
            role.id: {"attack_type": attack[0], "spell": attack[1], "powered_attack": attack[2]}
            if attack
            else None
            for role, attack in zip(search.request.roles, attacks, strict=True)
        }
        if numeric is not None:
            return numeric(options)
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


def _numeric_trip_loss(
    search: Any, assignment: Mapping[str, Mapping[str, int]]
) -> Callable[[TripOptions], int | None] | None:
    if getattr(search, "native_context", None) is None:
        return None
    risk = search.wilderness
    attacks = risk.policy.attacks_per_setup
    if attacks is None:
        return None
    if not hasattr(search, "_native_trip_loss"):
        from tracker.gear.native import record
        from tracker.gear.native._stages import TripLossContext

        try:
            search._native_trip_loss = TripLossContext({**risk.rules, **risk.rune_rules})
        except OverflowError:
            record("fallback", reason="fixed-trip death rules exceed native range")
            search._native_trip_loss = None
        else:
            record("trip_loss", roles=tuple(role.style for role in search.request.roles))
    context = search._native_trip_loss
    if context is None:
        return None
    styles = {role.id: role.style for role in search.request.roles}
    ordinary = {role: gear for role, gear in assignment.items() if styles[role] != "special"}
    minimum = risk._minimum({item for gear in assignment.values() for item in gear.values()})

    def measure(options: TripOptions) -> int | None:
        runes = wilderness_spell_runes(ordinary, options, search.items, attacks)
        if runes is None:
            return None
        resources = trip_resources(assignment, options, styles, search.items, risk.rules, attacks)
        if resources is None:
            return None
        quantities = minimum | resources | runes
        try:
            loss = context.loss(quantities, risk.kept_slots)
        except OverflowError:
            from tracker.gear.native import record

            if not getattr(search, "_native_trip_overflow", False):
                record("fallback", reason="fixed-trip quantities exceed native range")
                search._native_trip_overflow = True
            loss = risk._worst(quantities, risk.kept_slots).loss_gp
        if loss is None or (risk.budget_gp is not None and loss > risk.budget_gp):
            return None
        return int(loss)

    return measure


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
