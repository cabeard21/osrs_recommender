"""Bound price fetches to authored tradeable Gear ladder primary IDs."""

from __future__ import annotations

from tracker.content.loader import Content


def scoped_item_ids(content: Content) -> frozenset[int]:
    """Items eligible for market fetches in the current factual Gear product."""
    return frozenset(
        item.item_id
        for item in content.items.values()
        if item.item_id is not None
        and item.style is not None
        and item.slot is not None
        and item.tier is not None
        and item.acquisition == "tradeable"
    )
