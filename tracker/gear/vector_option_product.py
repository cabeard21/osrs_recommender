"""Packed role alternatives and direct resumption of the reference option product."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, Sequence
from functools import cached_property
from itertools import product
from typing import Any

from tracker.gear.native import record
from tracker.gear.vector_options import OptionVariant


def remaining_product[T](
    alternatives: Sequence[Sequence[T]], start: int
) -> Iterator[tuple[T, ...]]:
    """Yield itertools.product order, seeking to start without visiting its prefix."""
    if start == 0:
        yield from product(*alternatives)
        return
    digits = [0] * len(alternatives)
    for role in reversed(range(len(alternatives))):
        if not alternatives[role]:
            return
        start, digits[role] = divmod(start, len(alternatives[role]))
    if start:
        return
    while True:
        yield tuple(options[digit] for options, digit in zip(alternatives, digits, strict=True))
        for role in reversed(range(len(alternatives))):
            digits[role] += 1
            if digits[role] < len(alternatives[role]):
                break
            digits[role] = 0
        else:
            return


class PackedOptionsCache:
    """Reuse packed alternatives across assignments within one VectorSearch."""

    def __init__(self) -> None:
        self._roles: OrderedDict[tuple[int, int], Any] = OrderedDict()

    @cached_property
    def _native_types(self) -> tuple[Any, Any] | None:
        try:
            from tracker.gear.native._frontier import OptionProduct, PackedRole
        except ImportError:
            record("fallback", reason="native_option_product_unavailable")
            return None
        return PackedRole, OptionProduct

    def product(
        self,
        alternatives: tuple[tuple[OptionVariant, ...], ...],
        roles: tuple[Any, ...],
        width: int,
        cost_index: int | None,
        risk_index: int | None,
    ) -> Any:
        if self._native_types is None:
            return None
        pack_role, make_product = self._native_types
        cost = -1 if cost_index is None else cost_index
        packed = []
        try:
            for index, (variants, role) in enumerate(zip(alternatives, roles, strict=True)):
                # PackedRole owns this exact tuple, preventing reuse of its id while cached.
                key = index, id(variants)
                if key in self._roles:
                    self._roles.move_to_end(key)
                else:
                    self._roles[key] = pack_role(
                        variants, role.weight, role.style == "special", width, cost
                    )
                    if len(self._roles) > 512:
                        self._roles.popitem(last=False)
                packed.append(self._roles[key])
            return make_product(tuple(packed), cost, -1 if risk_index is None else risk_index)
        except (ValueError, OverflowError, TypeError):
            # Unsupported pack inputs keep the reference calculation and its error behavior.
            return None
