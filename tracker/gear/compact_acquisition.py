"""Frozen numeric acquisition facts preserving market-alias overwrite order."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from tracker.gear.evaluation import purchases, unowned_untradeables


@dataclass(frozen=True, slots=True)
class AcquisitionFacts:
    quotes: Mapping[int, tuple[int, int] | None]
    untradeables: frozenset[int]

    @classmethod
    def from_facts(cls, facts: Mapping[int, dict[str, Any]], request: Any) -> "AcquisitionFacts":
        quotes = {}
        for item in facts:
            rows = purchases({item}, facts, request)
            quotes[item] = (rows[0]["item_id"], rows[0]["cost_gp"] or 0) if rows else None
        return cls(
            MappingProxyType(quotes), frozenset(unowned_untradeables(set(facts), facts, request))
        )

    def totals(self, ids: frozenset[int]) -> tuple[int, int]:
        markets = {}
        for item in sorted(ids):
            quote = self.quotes[item]
            if quote is not None:
                market, amount = quote
                markets[market] = amount
        return sum(markets.values()), len(ids & self.untradeables)
