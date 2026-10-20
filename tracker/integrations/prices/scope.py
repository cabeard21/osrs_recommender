"""Bound price retention to equipment with reviewed acquisition metadata."""

from __future__ import annotations

from tracker.content.loader import Content


def scoped_item_ids(content: Content) -> frozenset[int]:
    """Known tradeable equipment, independent of style or progression placement."""
    return frozenset(
        item.item_id
        for item in content.items.values()
        if item.item_id is not None and item.slot is not None and item.acquisition == "tradeable"
    )
