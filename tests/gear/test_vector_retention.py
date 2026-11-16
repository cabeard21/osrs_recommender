"""Vector diversity retains all extrema and is invariant to physical input order."""

from tracker.gear.vector_retention import retain


def test_every_minimum_and_maximum_survives_a_smaller_requested_width():
    rows = [(10.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 0.0, 10.0), (2.0, 2.0, 2.0)]
    selected = retain(rows, lambda row: row, lambda row: row, 1)
    assert set(rows[:3]) <= set(selected)


def test_normalized_farthest_fill_keeps_interior_and_is_order_independent():
    rows = [(0.0, 1000.0), (100.0, 0.0), (50.0, 500.0), (1.0, 990.0)]
    expected = {(0.0, 1000.0), (100.0, 0.0), (50.0, 500.0)}
    for ordering in (rows, list(reversed(rows))):
        assert set(retain(ordering, lambda row: row, lambda row: row, 3)) == expected


def test_positive_unit_scaling_and_translation_do_not_change_membership():
    rows = [(0.0, 1000.0), (100.0, 0.0), (50.0, 500.0), (1.0, 990.0)]

    def identity(row):
        return row

    original = retain(rows, lambda row: row, identity, 3)
    transformed = retain(rows, lambda row: (row[0] * 70 + 100, row[1] * 0.001 - 17), identity, 3)
    assert transformed == original


def test_constant_dimensions_and_duplicate_candidates_are_safe():
    rows = [(1.0, 0.0), (2.0, 0.0), (3.0, 0.0), (2.0, 0.0)]
    selected = retain(rows, lambda row: row, lambda row: row, 2)
    assert set(selected) == {(1.0, 0.0), (3.0, 0.0)}


def test_equal_distance_fill_uses_stable_physical_identity():
    rows = {"high": (10.0, 10.0), "low": (0.0, 0.0), "a": (5.0, 6.0), "b": (6.0, 5.0)}
    selected = retain(list(reversed(rows)), rows.__getitem__, lambda key: key, 3)
    assert set(selected) == {"high", "low", "a"}
