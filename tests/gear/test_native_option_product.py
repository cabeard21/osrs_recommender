from dataclasses import replace
from itertools import product
from math import inf, nextafter
from types import SimpleNamespace

import pytest

from tracker.gear.compact_costs import NumericCost
from tracker.gear.vector_options import OptionVariant
from tracker.gear.vector_search import VectorSearch


@pytest.fixture
def kernel():
    return pytest.importorskip("tracker.gear.native._frontier")


def variant(values, hourly=None):
    cost = None if hourly is None else NumericCost("known", None, None, hourly, None)
    return OptionVariant(None, None, {}, tuple(values), cost)


def packed_product(kernel, pools, roles, cost, risk=-1):
    width = len(pools[0][0].values)
    return kernel.OptionProduct(
        tuple(
            kernel.PackedRole(pool, weight, special, width, cost)
            for pool, (weight, special) in zip(pools, roles, strict=True)
        ),
        cost,
        risk,
    )


def index_with(kernel, row):
    result = kernel.ArchiveIndex(len(row))
    result.insert("row", row)
    return result


@pytest.mark.parametrize(
    ("roles", "scores", "hours", "cost", "width"),
    [
        ([(1, False)], [1.25], [0.0], 1, 2),
        ([(1, False)], [1.25], [None], -1, 3),
        ([(1, False), (1, False)], [1.0000000000000002, 2.55], [9.17, 8.83], 1, 3),
        ([(1, False), (1, False)], [7, 2], [None, 2], 2, 3),
        ([(2.3, False), (1.7, False)], [0.141, 0.274], [None, 1.1], 2, 4),
        ([(1, False)] * 3, [1e16, 1, -1e16], [None] * 3, -1, 65),
        (
            [(2, False), (0, False), (1, True), (0.5, False)],
            [1, 9, 100, 12],
            [0, -1, -1, 3601.9],
            1,
            4,
        ),
        ([(1, True), (0, True)], [1, 9], [None, None], -1, 3),
        ([(0, False), (0, False)], [1, 9], [None, None], -1, 3),
    ],
)
def test_arithmetic_matches_python_oracle_at_one_ulp(kernel, roles, scores, hours, cost, width):
    pools = tuple(
        (variant((score, *(score / (n + 1) for n in range(width - 1))), hourly),)
        for score, hourly in zip(scores, hours, strict=True)
    )
    scanner = packed_product(kernel, pools, roles, cost)
    selected = tuple(p[0] for p in pools)
    configs = tuple(
        SimpleNamespace(weight=float(w), style="special" if special else "melee")
        for w, special in roles
    )
    search = SimpleNamespace(
        options=SimpleNamespace(cost_index=cost if cost >= 0 else None),
        weighted_values=VectorSearch.weighted_values,
    )
    row = VectorSearch.weighted(search, selected, configs)
    assert row is not None
    for axis in range(width):
        for target in (row[axis], nextafter(row[axis], inf), nextafter(row[axis], -inf)):
            archive_row = (*row[:axis], target, *row[axis + 1 :])
            index = index_with(kernel, archive_row)
            assert scanner.scan(0, 1, (index,), -inf, None, None) == (
                1,
                None if index.strictly_dominated(row) else selected,
                None,
            )


def test_resume_mixed_radix_all_caps_and_equal_rows(kernel):
    pools = tuple(tuple(variant((score, 1)) for score in values) for values in ((1, 4), (2, 3, 6)))
    scanner = packed_product(kernel, pools, [(1, False)] * 2, -1)
    selections = list(product(*pools))
    indexes = index_with(kernel, (9, 1)), index_with(kernel, (3.5, 1))
    assert scanner.size == 6
    assert scanner.scan(0, 2, indexes, -inf, None, None) == (2, None, None)
    assert scanner.scan(2, 20, indexes, -inf, None, None) == (1, selections[2], None)
    assert scanner.scan(3, 20, indexes, -inf, None, None) == (2, selections[4], None)
    assert scanner.scan(6, 2, indexes, -inf, None, None) == (0, None, None)


@pytest.mark.parametrize("hourly", [None, -1.0, float("nan"), float("inf")])
def test_unpriced_baseline_ties_require_feasible_trip(kernel, hourly):
    pool = (variant((1, 0, 0), hourly), variant((2, 0, 0), hourly), variant((2, 0, 0), hourly))
    scanner = packed_product(kernel, (pool,), [(1, False)], 1, risk=2)
    visited = []

    def loss(selected):
        visited.append(selected[0])
        return None if selected[0] is pool[1] else 0

    assert scanner.scan(0, 3, (kernel.ArchiveIndex(3),), 2, loss, None) == (3, (pool[2],), None)
    assert [id(x) for x in visited] == [id(x) for x in pool]


def test_zero_cost_zero_damage_and_whole_trip_risk(kernel):
    pool = (variant((0, 7, 0), 0), variant((3, 7, 0), 0))
    scanner = packed_product(kernel, (pool,), [(1, False)], 1, risk=2)
    index = index_with(kernel, (3, 0, -1))
    assert scanner.scan(0, 2, (index,), 1, lambda _: 2, None) == (2, None, None)
    assert scanner.scan(0, 2, (index,), 1, lambda _: 0, None) == (2, (pool[1],), None)


@pytest.mark.parametrize("specialized", [False, True])
def test_absent_and_unavailable_costs_have_different_denominators(kernel, specialized):
    # The costless role's DPS is included in the score but excluded from GP/damage.
    left = variant((10, -99, 3), 3600)
    absent = variant((20, -99, 3))
    unavailable = replace(absent, cost=NumericCost("unavailable", None, None, 3600, None))
    pools = (left,), (absent, unavailable)
    weight = 1 if specialized else 2
    scanner = packed_product(kernel, pools, [(weight, False), (weight, False)], 1)
    # Exact GP/damage with costless second role is 1/10. Including its damage would
    # make the candidate affordable enough to survive this archive row.
    indexes = (index_with(kernel, (15, -0.09, 3)),)
    assert scanner.scan(0, 2, indexes, 15, None, None) == (2, (left, unavailable), None)
    assert scanner.scan(0, 2, indexes, 16, None, None) == (2, None, None)


@pytest.mark.parametrize("loss", [2**53 + 1, 2**1024, inf, float("nan"), "invalid"])
def test_unrepresentable_risk_stops_before_consuming_current_option(kernel, loss):
    pool = (variant((1, 0)), variant((2, 0)))
    scanner = packed_product(kernel, (pool,), [(1, False)], -1, risk=1)
    indexes = (index_with(kernel, (3, 1)),)
    assert scanner.scan(
        0, 2, indexes, -inf, lambda selected: 1 if selected[0] is pool[0] else loss, None
    ) == (1, None, "reference")


def test_partial_scan_cancellation_and_nonfinite_reference(kernel):
    pool = tuple(variant((value, 1)) for value in (1, 2, inf, 4))
    scanner = packed_product(kernel, (pool,), [(1, False)], -1)
    indexes = (index_with(kernel, (99, 2)),)
    checks = iter([False, True])
    assert scanner.scan(0, 4, indexes, -inf, None, lambda: next(checks)) == (1, None, "cancelled")
    assert scanner.scan(1, 3, indexes, -inf, None, None) == (1, None, "reference")
    assert scanner.scan(2, 1, indexes, -inf, None, None) == (0, None, "reference")


def test_large_product_uses_python_integer_cursor(kernel):
    first, last = variant((1,)), variant((2,))
    packed = kernel.PackedRole((first,) * 65535 + (last,), 1, False, 1, -1)
    scanner = kernel.OptionProduct((packed,) * 4, -1, -1)
    assert scanner.size == 2**64
    assert scanner.scan(2**64 - 1, 5, (kernel.ArchiveIndex(1),), -inf, None, None) == (
        1,
        (last,) * 4,
        None,
    )


def test_native_boundary_validates_dimensions_and_indices(kernel):
    class CustomOrdinal(int):
        pass

    item = variant((2, 3))
    with pytest.raises(ValueError):
        kernel.PackedRole((item,), 1, False, 66, -1)
    with pytest.raises(ValueError):
        kernel.PackedRole((item,), 1, False, 1, -1)
    packed = kernel.PackedRole((item,), 1, False, 2, -1)
    for roles in ((), (packed,) * 5):
        with pytest.raises(ValueError):
            kernel.OptionProduct(roles, -1, -1)
    scanner = kernel.OptionProduct((packed,), -1, -1)
    with pytest.raises(ValueError):
        scanner.scan(0, 1, (kernel.ArchiveIndex(3),), -inf, None, None)
    with pytest.raises(ValueError):
        scanner.scan(2, 1, (), -inf, None, None)
    for bad_call in (
        (-1, 1, (), -inf, None, None),
        (0, -1, (), -inf, None, None),
        (0.5, 1, (), -inf, None, None),
        (CustomOrdinal(0), 1, (), -inf, None, None),
        (0, CustomOrdinal(1), (), -inf, None, None),
        (0, 1, (None,) * 33, -inf, None, None),
        (0, 1, (), float("nan"), None, None),
        (0, 1, (), -inf, lambda _: 0, None),
        (0, 1, (), -inf, None, 42),
    ):
        with pytest.raises(ValueError):
            scanner.scan(*bad_call)
    with pytest.raises(TypeError):
        scanner.scan(0, 1, (42,), -inf, None, None)
    assert scanner.scan(0, 1, (None,), -inf, None, None) == (0, None, "reference")


def test_unscannable_products_and_incompatible_roles(kernel):
    pool = (variant((1, 2)),)
    packed = kernel.PackedRole(pool, 1, False, 2, 1)
    empty = kernel.OptionProduct((kernel.PackedRole((), 1, False, 2, 1), packed), 1, -1)
    assert empty.size == 0
    assert empty.scan(0, 100, (), -inf, None, None) == (0, None, None)
    with pytest.raises(ValueError):
        kernel.PackedRole(pool, -1, False, 2, 1)
    with pytest.raises(ValueError):
        kernel.OptionProduct((packed,), -1, -1)
    with pytest.raises(ValueError):
        kernel.OptionProduct((packed,), 1, 1)
    with pytest.raises(ValueError):
        kernel.OptionProduct((None,), 1, -1)
