"""Bounded vector beams prefer the affordable physical form on equal projections."""

from types import SimpleNamespace

import pytest

from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.optimizer import SLOTS, RoleConfig
from tracker.gear.vector_search import VectorSearch


@pytest.mark.parametrize("anchor", [None, 1])
@pytest.mark.parametrize("variant_cost", [0, 100, 1000])
def test_equivalent_cape_beam_prefers_owned_or_cheaper_form(monkeypatch, anchor, variant_cost):
    catalog = load_catalog(load_content())
    assert catalog.items[6568].bonuses == catalog.items[20050].bonuses
    costs = {6568: 1000, 20050: variant_cost}
    role = RoleConfig(id="one", style="slash")
    search = SimpleNamespace(
        request=SimpleNamespace(locks={}, budget_gp=10000, roles=(role,)),
        eligible={item: catalog.items[item] for item in costs},
        cost=lambda ids: sum(costs[item] for item in ids),
        untradeable_acquisitions=lambda ids: 0,
        compatible=lambda equipment: True,
        may_equip_ammunition=lambda equipment, roles: True,
        slot_budget=lambda *args, **kwargs: True,
        cancelled=None,
        reporter=SimpleNamespace(fraction=lambda value: None),
    )
    engine = object.__new__(VectorSearch)
    engine.search = search
    engine.options = SimpleNamespace(
        risk_index=None,
        projection=lambda equipment, roles, **kwargs: (1.0, 9.0) if equipment else (0.0, 0.0),
    )
    engine.limit = 10000
    engine.nodes = 0
    engine.pools = {slot: [None] for slot in SLOTS}
    engine.pools["cape"] = [None, 6568, 20050]
    engine.capture = lambda assignment: None
    monkeypatch.setattr("tracker.gear.optimizer.BEAM_WIDTH", 2 if anchor is None else 1)

    retained = engine.equipment((role,), allowance=10000, anchor=anchor)

    preferred = 20050 if variant_cost < 1000 else 6568
    assert {"cape": preferred} in retained
    if variant_cost < 1000:
        assert {"cape": 6568} not in retained
