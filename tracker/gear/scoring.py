"""Immutable equipment aggregates reused across one frozen optimization request."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import NamedTuple

from tracker.gear.compact_states import EquipmentState
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition

_INTEGER_FIELDS = tuple(field for field in EquipmentBonuses.model_fields if field != "magic_damage")


@dataclass(frozen=True, slots=True)
class PreparedEquipment:
    equipment: tuple[EquipmentDefinition, ...]
    weapon: EquipmentDefinition | None
    ammunition: EquipmentDefinition | None
    bonuses: EquipmentBonuses
    _ammunition_ranged: int
    _ammunition_strength: int
    _magic_terms: tuple[float, ...]

    @property
    def ranged_bonuses(self) -> EquipmentBonuses:
        if self.ammunition is None or (self.weapon is not None and self.weapon.ammo_for):
            return self.bonuses
        # Keep the derived view lazy: melee and magic scoring do not need it.
        # No cached value is mutated when a ranged variant requests this view.
        return self.bonuses.model_copy(
            update={
                "ranged": self.bonuses.ranged - self._ammunition_ranged,
                "ranged_strength": self.bonuses.ranged_strength - self._ammunition_strength,
            }
        )


class ScoringCacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int
    currsize: int


def prepare_equipment(
    items: Mapping[str, EquipmentDefinition] | Sequence[EquipmentDefinition],
) -> PreparedEquipment:
    """Prepare an arbitrary loadout using the original ordered, full bonus sums."""
    equipment = tuple(items.values()) if isinstance(items, Mapping) else tuple(items)
    bonuses = EquipmentBonuses(
        **{
            field: sum(getattr(item.bonuses, field) for item in equipment)
            for field in EquipmentBonuses.model_fields
        }
    )
    return PreparedEquipment(
        equipment,
        next((item for item in equipment if item.slot == "weapon"), None),
        next((item for item in equipment if item.slot == "ammunition"), None),
        bonuses,
        sum(item.bonuses.ranged for item in equipment if item.slot == "ammunition"),
        sum(item.bonuses.ranged_strength for item in equipment if item.slot == "ammunition"),
        tuple(item.bonuses.magic_damage for item in equipment),
    )


class EquipmentScorer:
    """Reuse integer prefix sums with bounded, insertion-order-sensitive caching.

    Callers validate physical slot mappings before preparation. The catalog copy
    fixes item definitions for this instance; there is no cross-request cache.
    """

    def __init__(self, items: Mapping[int, EquipmentDefinition]) -> None:
        catalog = MappingProxyType(dict(items))

        @lru_cache(maxsize=8192)
        def prepare(ids: tuple[int, ...]) -> PreparedEquipment:
            if not ids:
                return PreparedEquipment((), None, None, EquipmentBonuses(magic_damage=0), 0, 0, ())
            parent = prepare(ids[:-1])
            item = catalog[ids[-1]]
            equipment = (*parent.equipment, item)
            magic_terms = (*parent._magic_terms, item.bonuses.magic_damage)
            bonuses = EquipmentBonuses(
                **{
                    field: getattr(parent.bonuses, field) + getattr(item.bonuses, field)
                    for field in _INTEGER_FIELDS
                },
                # Python's floating sum is not associative. In particular, 3.12
                # compensates float sums: adding a child to the parent's rounded
                # total can change max-hit breakpoints. Retain original terms.
                magic_damage=sum(magic_terms),
            )
            is_ammunition = item.slot == "ammunition"
            return PreparedEquipment(
                equipment,
                parent.weapon or (item if item.slot == "weapon" else None),
                parent.ammunition or (item if is_ammunition else None),
                bonuses,
                parent._ammunition_ranged + (item.bonuses.ranged if is_ammunition else 0),
                parent._ammunition_strength
                + (item.bonuses.ranged_strength if is_ammunition else 0),
                magic_terms,
            )

        self._prepare = prepare

    def prepare(self, equipment: Mapping[str, int]) -> PreparedEquipment:
        if isinstance(equipment, EquipmentState):
            return self._prepare(equipment.ordered_ids)
        return self._prepare(tuple(equipment.values()))

    def cache_info(self) -> ScoringCacheInfo:
        info = self._prepare.cache_info()
        return ScoringCacheInfo(info.hits, info.misses, 8192, info.currsize)
