"""Native packing guards also run when the optional extension is not installed."""

from types import SimpleNamespace

import pytest

from tracker.gear.compact_acquisition import AcquisitionFacts
from tracker.gear.native.stage_context import MAX_NATIVE_ITEM_COST, pack_stage, preflight


def search_context(**updates):
    request = SimpleNamespace(
        roles=(SimpleNamespace(id="a", style="slash", weight=1.0),),
        budget_gp=1000,
        reserved_supply_slots=0,
        include_untradeables=False,
    )
    for key, value in updates.items():
        setattr(request, key, value)
    return SimpleNamespace(
        request=request, edges=(), facts={2: {}}, items={2: object()}, marginals={}
    )


@pytest.mark.parametrize("value", [-1, 2**63, True, 1.5])
def test_budget_cannot_overflow_or_change_integer_semantics(value):
    assert "budget" in preflight(search_context(budget_gp=value), AcquisitionFacts({}, frozenset()))


@pytest.mark.parametrize("value", [-1, 29, True])
def test_inventory_capacity_is_bounded(value):
    assert "inventory" in preflight(
        search_context(reserved_supply_slots=value), AcquisitionFacts({}, frozenset())
    )


@pytest.mark.parametrize("weight", [float("inf"), float("nan"), -1.0, 1e13])
def test_weight_cannot_poison_native_sort_order(weight):
    roles = (SimpleNamespace(id="a", weight=weight),)
    assert "weights" in preflight(search_context(roles=roles), AcquisitionFacts({}, frozenset()))


def test_quote_boundary_guarantees_exact_union_rank_costs():
    safe = AcquisitionFacts({2: (999, MAX_NATIVE_ITEM_COST)}, frozenset())
    unsafe = AcquisitionFacts({2: (999, MAX_NATIVE_ITEM_COST + 1)}, frozenset())
    assert preflight(search_context(), safe) is None
    assert "acquisition" in preflight(search_context(), unsafe)


def test_transition_edges_must_refer_to_packed_roles():
    search = search_context()
    search.edges = (("a", "missing"),)
    assert "identities" in preflight(search, AcquisitionFacts({}, frozenset()))


def test_pack_rejects_role_dimension_mismatch_without_loading_extension(monkeypatch):
    acquisition = AcquisitionFacts({2: None}, frozenset())
    monkeypatch.setattr(AcquisitionFacts, "from_facts", lambda *args: acquisition)
    scorer = SimpleNamespace(role_count=2, item_count=2, dense_ids=(0, 2))
    with pytest.raises(ValueError, match="role dimensions"):
        pack_stage(search_context(), scorer)


def test_pack_rejects_item_dimension_mismatch_without_loading_extension(monkeypatch):
    acquisition = AcquisitionFacts({2: None}, frozenset())
    monkeypatch.setattr(AcquisitionFacts, "from_facts", lambda *args: acquisition)
    scorer = SimpleNamespace(role_count=1, item_count=3, dense_ids=(0, 2))
    with pytest.raises(ValueError, match="item dimensions"):
        pack_stage(search_context(), scorer)


def test_pack_emits_bounded_dense_tables_without_loading_extension(monkeypatch):
    acquisition = AcquisitionFacts({2: (100, 25)}, frozenset({2}))
    monkeypatch.setattr(AcquisitionFacts, "from_facts", lambda *args: acquisition)
    scorer = SimpleNamespace(role_count=1, item_count=2, dense_ids=(0, 2))
    packed = pack_stage(search_context(), scorer)
    assert list(packed.markets) == [0, 100]
    assert list(packed.costs) == [0, 25]
    assert list(packed.untradeable) == [0, 1]
    assert packed.role_names == ("a",)
    assert packed.capacity == 28
