"""Compiled farthest-point retention exactly preserves Python order and ties."""

import random

import pytest

import tracker.gear.vector_retention as retention


@pytest.mark.parametrize("dimensions", [1, 2, 5, 12, 63])
@pytest.mark.parametrize("seed", [1, 17, 91])
def test_native_retention_matches_python_order(monkeypatch, dimensions, seed):
    native = pytest.importorskip("tracker.gear.native._scoring")
    rng = random.Random(seed)
    rows = {
        index: tuple(
            rng.uniform(-1e7, 1e7) if axis % 3 else rng.randrange(10) for axis in range(dimensions)
        )
        for index in range(170)
    }
    inputs = list(rows)
    rng.shuffle(inputs)
    monkeypatch.setattr(retention, "_native_farthest_indices", None)
    expected = retention.retain(inputs, rows.__getitem__, lambda key: key, 40)
    monkeypatch.setattr(retention, "_native_farthest_indices", native.farthest_indices)
    actual = retention.retain(inputs, rows.__getitem__, lambda key: key, 40)
    assert actual == expected
    assert retention.retain(reversed(inputs), rows.__getitem__, lambda key: key, 40) == expected


@pytest.mark.parametrize(
    "vectors,limit",
    [
        ([(1.0, 0.0)] * 30, 8),
        ([(10.0, 10.0), (0.0, 0.0), (5.0, 6.0), (6.0, 5.0)], 3),
        ([(10.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 0.0, 10.0), (2.0, 2.0, 2.0)], 1),
        ([(float(index), 7.0, 0.0) for index in range(35)], 10),
    ],
)
def test_native_retention_preserves_constant_tied_and_oversized_anchors(
    monkeypatch, vectors, limit
):
    native = pytest.importorskip("tracker.gear.native._scoring")
    rows = list(enumerate(vectors))
    monkeypatch.setattr(retention, "_native_farthest_indices", None)
    expected = retention.retain(rows, lambda row: row[1], lambda row: row[0], limit)
    monkeypatch.setattr(retention, "_native_farthest_indices", native.farthest_indices)
    assert retention.retain(rows, lambda row: row[1], lambda row: row[0], limit) == expected
