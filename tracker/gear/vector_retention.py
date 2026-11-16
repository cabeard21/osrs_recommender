"""Deterministic bounded diversity for heuristic vector equipment beams."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

try:
    from tracker.gear.native._scoring import farthest_indices as _native_farthest_indices
except ImportError:
    _native_farthest_indices = None


def retain[Row](
    rows: Iterable[Row],
    vector: Callable[[Row], tuple[float, ...]],
    identity: Callable[[Row], Any],
    limit: int,
) -> list[Row]:
    """Preserve every axis extreme, then normalized farthest-point diversity.

    Partial equipment values are heuristic projections, not dominance proofs.
    """
    unique = {identity(row): row for row in rows}
    decorated = [(vector(row), key, row) for key, row in sorted(unique.items())]
    if len(decorated) <= limit:
        return [entry[2] for entry in decorated]
    dimensions = len(decorated[0][0])
    if _native_farthest_indices is not None:
        try:
            selected = _native_farthest_indices([entry[0] for entry in decorated], limit)
        except ValueError:
            # Non-finite or unsupported numerical inputs retain the Python path.
            pass
        else:
            return [decorated[index][2] for index in selected]
    anchors = []
    ranges = []
    for dimension in range(dimensions):
        order = sorted(
            range(len(decorated)), key=lambda i: (-decorated[i][0][dimension], decorated[i][1])
        )
        for anchor in (order[0], order[-1]):
            if anchor not in anchors:
                anchors.append(anchor)
        high, low = decorated[order[0]][0][dimension], decorated[order[-1]][0][dimension]
        ranges.append(high - low)
    normalized = [
        tuple(value / span if span else 0.0 for value, span in zip(entry[0], ranges, strict=True))
        for entry in decorated
    ]

    def distance(first: int, second: int) -> float:
        return sum((a - b) ** 2 for a, b in zip(normalized[first], normalized[second], strict=True))

    selected = list(anchors)
    remaining = {index for index in range(len(decorated)) if index not in selected}
    nearest = {index: min(distance(index, anchor) for anchor in selected) for index in remaining}
    while remaining and len(selected) < max(limit, len(anchors)):
        chosen = min(remaining, key=lambda index: (-nearest[index], decorated[index][1]))
        selected.append(chosen)
        remaining.remove(chosen)
        for index in remaining:
            nearest[index] = min(nearest[index], distance(index, chosen))
    return [decorated[index][2] for index in selected]
