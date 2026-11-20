"""Frozen numeric acquisition facts preserving market-alias overwrite order."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import combinations
from types import MappingProxyType
from typing import Any

from tracker.gear.evaluation import purchases, unowned_untradeables
from tracker.gear.revenant import FORMS
from tracker.gear.revenant_acquisition import copies_available, joint_sources, preferred_sources

_FAMILIES = tuple(
    frozenset(preferred_sources(base))
    for base in sorted({form.market_id for form in FORMS.values()})
)


@dataclass(frozen=True, slots=True)
class AcquisitionFacts:
    quotes: Mapping[int, tuple[int, int] | None]
    untradeables: frozenset[int]
    revenant_adjustments: Mapping[frozenset[int], int | None] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def from_facts(cls, facts: Mapping[int, dict[str, Any]], request: Any) -> "AcquisitionFacts":
        quotes = {}
        for item in facts:
            rows = purchases({item}, facts, request)
            quotes[item] = (rows[0]["item_id"], rows[0]["cost_gp"] or 0) if rows else None
        adjustments = {}
        if len(getattr(request, "roles", (1, 2))) > 1:
            for family in _FAMILIES:
                forms = family.intersection(facts)
                for count in range(2, len(forms) + 1):
                    for selected in combinations(forms, count):
                        ids = frozenset(selected)
                        sources = joint_sources(ids, facts, request)
                        additional = None
                        if copies_available(sources, facts, request):
                            totals = sum(
                                p["cost_gp"] or 0 for p in purchases(set(ids), facts, request)
                            )
                            baseline = dict(q for i in sorted(ids) if (q := quotes[i]) is not None)
                            additional = totals - sum(baseline.values())
                        if additional != 0:
                            adjustments[ids] = additional
        return cls(
            MappingProxyType(quotes),
            frozenset(unowned_untradeables(set(facts), facts, request)),
            MappingProxyType(adjustments),
        )

    def ready_copy_adjustment(self, ids: frozenset[int]) -> int | None:
        if not self.revenant_adjustments or len(FORMS.keys() & ids) < 2:
            return 0
        total = 0
        for family in _FAMILIES:
            adjustment = self.revenant_adjustments.get(ids.intersection(family), 0)
            if adjustment is None:
                return None
            total += adjustment
        return total

    def totals(self, ids: frozenset[int]) -> tuple[int, int]:
        markets = {}
        for item in sorted(ids):
            quote = self.quotes[item]
            if quote is not None:
                market, amount = quote
                markets[market] = amount
        return sum(markets.values()) + (self.ready_copy_adjustment(ids) or 0), len(
            ids & self.untradeables
        )
