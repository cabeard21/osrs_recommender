from array import array
from random import Random

import pytest

from tracker.gear.vector_archive import dominates


@pytest.fixture
def kernel():
    return pytest.importorskip("tracker.gear.native._frontier")


@pytest.mark.parametrize("dimensions", [1, 4, 65])
def test_frontier_matches_reference(kernel, dimensions):
    random = Random(29)
    rows = [tuple(random.randrange(-5, 6) for _ in range(dimensions)) for _ in range(120)]
    rows.extend(rows[:20])
    expected = [i for i, row in enumerate(rows) if not any(dominates(other, row) for other in rows)]
    packed = array("d", (value for row in rows for value in row))
    assert kernel.pareto_indices(packed, dimensions) == expected


def test_frontier_validates_and_cancels(kernel):
    with pytest.raises(ValueError, match="dimensions"):
        kernel.pareto_indices(array("d", [1]), 2)
    with pytest.raises(ValueError, match="finite"):
        kernel.pareto_indices(array("d", [float("inf")]), 1)
    with pytest.raises(ValueError, match="optimization_cancelled"):
        kernel.pareto_indices(array("d", [1]), 1, lambda: True)


def test_archive_index_tracks_updates(kernel):
    index = kernel.ArchiveIndex(2)
    index.insert("one", (2, 3))
    index.insert("two", (3, 1))
    assert index.strictly_dominated((2, 2))
    assert not index.strictly_dominated((2, 3))
    index.insert("one", (1, 1))
    assert not index.strictly_dominated((2, 2))
    index.discard("two")
    index.discard("absent")
    assert not index.strictly_dominated((3, 0))
    assert index.strictly_dominated((0, 1))


def test_archive_index_removes_only_strictly_dominated_rows(kernel):
    index = kernel.ArchiveIndex(2)
    index.insert("first", (1, 2))
    index.insert("second", (2, 1))
    index.insert("equal", (2, 2))
    index.insert("tradeoff", (3, 0))
    index.remove_dominated((2, 2))
    assert len(index) == 2
    index.discard("equal")
    assert not index.strictly_dominated((1, 1))
    assert index.strictly_dominated((2, 0))


def test_multi_cap_admission_keeps_unresolved_ties_and_missing_indexes(kernel):
    first, second = kernel.ArchiveIndex(2), kernel.ArchiveIndex(2)
    first.insert("cheap", (2, 3), (1, 100))
    second.insert("expensive", (2, 3), (2, 100))
    indices = (first, second, None)
    assert kernel.admission_mask(indices, (1, 2), (0, 0)) == 0b100
    assert kernel.admission_mask(indices, (2, 3), (2, 100)) == 0b110
    assert kernel.admission_mask(indices, (2, 3), (0, 100)) == 0b111
    assert kernel.admission_mask(indices, (3, 2), (9, 100)) == 0b111
    first.discard("cheap")
    assert kernel.admission_mask(indices, (2, 3), (9, 100)) == 0b101
    with pytest.raises(ValueError, match="dimensions"):
        kernel.admission_mask((first,), (1,), ())
