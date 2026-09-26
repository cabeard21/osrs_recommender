"""Group curated Gear items by style and slot in authored order."""

from __future__ import annotations

from dataclasses import dataclass

from tracker.content.loader import Content
from tracker.content.schema import Item


@dataclass(frozen=True, slots=True)
class Ladder:
    """One authored style/slot ladder with its rungs in stable order."""

    style: str
    slot: str
    rungs: tuple[Item, ...]

    @property
    def size(self) -> int:
        return len(self.rungs)


def build_ladders(content: Content) -> tuple[Ladder, ...]:
    """Group equipment items without ranking them by price or combat value."""
    grouped: dict[tuple[str, str], list[Item]] = {}
    for item in content.items.values():
        if item.tier is None or item.slot is None or item.style is None:
            continue
        grouped.setdefault((item.style, item.slot), []).append(item)

    return tuple(
        Ladder(
            style=style,
            slot=slot,
            rungs=tuple(sorted(items, key=lambda item: (item.tier or 0, item.id))),
        )
        for (style, slot), items in sorted(grouped.items())
    )
