"""Immutable physical assignments with canonical identity and original sum order.

Insertion order is deliberately distinct from slot identity: floating equipment
bonuses must be summed in the same order as the dictionary implementation.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import ItemsView, Iterator, Mapping, ValuesView
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from operator import itemgetter
from typing import Any, cast, overload

SLOT_NAMES = (
    "weapon",
    "shield",
    "ammunition",
    "head",
    "cape",
    "neck",
    "body",
    "legs",
    "hands",
    "feet",
    "ring",
)
_INDEX = {slot: index for index, slot in enumerate(SLOT_NAMES)}
_SLOT_NAME = itemgetter(0)


class _EquipmentItems(ItemsView[str, int]):
    __slots__ = ()
    _mapping: EquipmentState

    def __iter__(self) -> Iterator[tuple[str, int]]:
        return iter(self._mapping.ordered_identity)


class _EquipmentValues(ValuesView[int]):
    __slots__ = ()
    _mapping: EquipmentState

    def __iter__(self) -> Iterator[int]:
        return iter(self._mapping.ordered_ids)


@dataclass(frozen=True, slots=True, eq=False)
class EquipmentState(Mapping[str, int]):
    """Fixed slots with the historical dictionary insertion order."""

    slots: tuple[int | None, ...]
    order: tuple[int, ...]
    identity: tuple[tuple[str, int], ...] = field(init=False)
    ordered_identity: tuple[tuple[str, int], ...] = field(init=False)
    ordered_ids: tuple[int, ...] = field(init=False)
    physical_ids: frozenset[int] = field(init=False)

    def __post_init__(self) -> None:
        ids = tuple(cast(int, self.slots[index]) for index in self.order)
        ordered = tuple(
            (SLOT_NAMES[index], item) for index, item in zip(self.order, ids, strict=True)
        )
        object.__setattr__(self, "ordered_ids", ids)
        object.__setattr__(self, "physical_ids", frozenset(ids))
        object.__setattr__(self, "ordered_identity", ordered)
        object.__setattr__(self, "identity", tuple(sorted(ordered)))

    @classmethod
    def from_mapping(cls, equipment: Mapping[str, int]) -> EquipmentState:
        if isinstance(equipment, cls):
            return equipment
        slots: list[int | None] = [None] * len(SLOT_NAMES)
        order = []
        for slot, item in equipment.items():
            index = _INDEX[slot]
            slots[index] = item
            order.append(index)
        return _new_equipment(tuple(slots), tuple(order))

    def __getitem__(self, slot: str) -> int:
        value = self.slots[_INDEX[slot]]
        if value is None:
            raise KeyError(slot)
        return value

    @overload
    def get(self, key: str) -> int | None: ...

    @overload
    def get(self, key: str, default: int) -> int: ...

    @overload
    def get[T](self, key: str, default: T) -> int | T: ...

    def get(self, key: str, default: Any = None) -> Any:
        index = _INDEX.get(key)
        value = self.slots[index] if index is not None else None
        return default if value is None else value

    def __contains__(self, key: object) -> bool:
        index = _INDEX.get(cast(str, key))
        return index is not None and self.slots[index] is not None

    def __iter__(self) -> Iterator[str]:
        return (SLOT_NAMES[index] for index in self.order)

    def __len__(self) -> int:
        return len(self.order)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EquipmentState):
            return self.slots == other.slots
        return Mapping.__eq__(self, other)

    def items(self) -> ItemsView[str, int]:
        return _EquipmentItems(self)

    def values(self) -> ValuesView[int]:
        return _EquipmentValues(self)

    def with_slot(self, slot: str, item: int | None) -> EquipmentState:
        index = _INDEX[slot]
        previous = self.slots[index]
        if previous == item:
            return self
        order = (
            tuple(i for i in self.order if i != index)
            if item is None
            else (*self.order, index)
            if previous is None
            else self.order
        )
        # Tuple concatenation avoids unpacking through a temporary list here.
        slots = self.slots[:index] + (item,) + self.slots[index + 1 :]  # noqa: RUF005
        pool = _POOL.get()
        if pool is not None:
            return pool.create(slots, order)
        replacement = () if item is None else ((slot, item),)
        if previous is None:
            # Search prefixes append new slots; retain their prepared pair tuples.
            ordered = self.ordered_identity + replacement
            ids = self.ordered_ids + (cast(int, item),)  # noqa: RUF005
        else:
            position = self.order.index(index)
            end = position + 1
            ordered = (
                *self.ordered_identity[:position],
                *replacement,
                *self.ordered_identity[end:],
            )
            ids = (
                *self.ordered_ids[:position],
                *((item,) if item is not None else ()),
                *self.ordered_ids[end:],
            )
        canonical = bisect_left(self.identity, slot, key=_SLOT_NAME)
        identity = (
            self.identity[:canonical]
            + replacement
            + self.identity[canonical + (previous is not None) :]
        )
        physical = self.physical_ids
        if previous is not None and previous not in ids:
            physical = physical - {previous}
        if item is not None and item not in physical:
            physical = physical | {item}
        result = object.__new__(EquipmentState)
        object.__setattr__(result, "slots", slots)
        object.__setattr__(result, "order", order)
        object.__setattr__(result, "ordered_identity", ordered)
        object.__setattr__(result, "ordered_ids", ids)
        object.__setattr__(result, "identity", identity)
        object.__setattr__(result, "physical_ids", physical)
        return result

    with_item = with_slot

    def without_slot(self, slot: str) -> EquipmentState:
        return self.with_slot(slot, None)

    def to_dict(self) -> dict[str, int]:
        return dict(self.ordered_identity)


@dataclass(frozen=True, slots=True, eq=False)
class AssignmentState(Mapping[str, EquipmentState]):
    """Role-ordered assignments retaining concrete shared physical items."""

    roles: tuple[tuple[str, EquipmentState], ...]
    carried: frozenset[int]
    identity: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identity",
            tuple(sorted((role, equipment.identity) for role, equipment in self.roles)),
        )

    @classmethod
    def from_mapping(cls, loadouts: Mapping[str, Mapping[str, int]]) -> AssignmentState:
        if isinstance(loadouts, cls):
            return loadouts
        roles = tuple(
            (role, EquipmentState.from_mapping(equipment)) for role, equipment in loadouts.items()
        )
        return cls._from_roles(roles)

    @classmethod
    def _from_roles(cls, roles: tuple[tuple[str, EquipmentState], ...]) -> AssignmentState:
        # One physical instance per concrete item is shared across roles.
        return cls(roles, frozenset().union(*(equipment.physical_ids for _, equipment in roles)))

    @property
    def reference_counts(self) -> tuple[tuple[int, int], ...]:
        """Diagnostic view; retained physical role identities determine the union."""
        counts = Counter(item for _, equipment in self.roles for item in equipment.physical_ids)
        return tuple(sorted(counts.items()))

    @classmethod
    def from_roles(cls, roles: tuple[tuple[str, EquipmentState], ...]) -> AssignmentState:
        """Construct one joint state after all role updates, preserving role order."""
        return cls._from_roles(roles)

    def __getitem__(self, role: str) -> EquipmentState:
        for name, equipment in self.roles:
            if name == role:
                return equipment
        raise KeyError(role)

    def __iter__(self) -> Iterator[str]:
        return (role for role, _ in self.roles)

    def __len__(self) -> int:
        return len(self.roles)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AssignmentState):
            return self.identity == other.identity
        return Mapping.__eq__(self, other)

    def with_role(self, role: str, equipment: Mapping[str, int]) -> AssignmentState:
        prepared = EquipmentState.from_mapping(equipment)
        if self.get(role) is prepared:
            return self
        if role in self:
            roles = tuple((name, prepared if name == role else old) for name, old in self.roles)
        else:
            roles = (*self.roles, (role, prepared))
        return self._from_roles(roles)

    def with_slot(self, role: str, slot: str, item: int | None) -> AssignmentState:
        return self.with_role(role, self[role].with_slot(slot, item))

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {role: equipment.to_dict() for role, equipment in self.roles}


JointState = AssignmentState


class EquipmentPool:
    """Bounded strong interning owned solely by one concrete execution leaf."""

    def __init__(self, capacity: int) -> None:
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("equipment pool capacity must be a positive integer")

        @lru_cache(maxsize=capacity)
        def create(slots: tuple[int | None, ...], order: tuple[int, ...]) -> EquipmentState:
            return EquipmentState(slots, order)

        self.create = create

    def cache_info(self) -> Any:
        return self.create.cache_info()

    def clear(self) -> None:
        self.create.cache_clear()


_POOL: ContextVar[EquipmentPool | None] = ContextVar("compact_equipment_pool", default=None)


def _new_equipment(slots: tuple[int | None, ...], order: tuple[int, ...]) -> EquipmentState:
    pool = _POOL.get()
    return EquipmentState(slots, order) if pool is None else pool.create(slots, order)


@contextmanager
def equipment_pool(capacity: int = 1024) -> Iterator[EquipmentPool]:
    """Reset on all exits, including cancellation and nested execution failure."""
    pool = EquipmentPool(capacity)
    token = _POOL.set(pool)
    try:
        yield pool
    finally:
        _POOL.reset(token)
        pool.clear()
