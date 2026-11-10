"""Compact membership must preserve the historical mapping-equality selections."""

import pytest

from tracker.gear.compact_states import AssignmentState, EquipmentState
from tracker.gear.frontier import diverse


@pytest.mark.parametrize("kind", ["equipment", "assignment", "mixed"])
@pytest.mark.parametrize("limit", [0, 1, 2, 8, 32, 200])
@pytest.mark.parametrize("equal_scores", [False, True])
def test_compact_diversity_keeps_exact_representatives_and_rank_calls(kind, limit, equal_scores):
    raw = [
        dict(reversed(list({"weapon": i % 19 + 1, "head": i % 7 + 30}.items())))
        if i % 2
        else {"weapon": i % 19 + 1, "head": i % 7 + 30}
        for i in range(160)
    ]
    if kind == "assignment":
        raw = [{"b": row, "a": {"head": 99}} for row in raw]
        compact = [AssignmentState.from_mapping(row) for row in raw]
    else:
        compact = [EquipmentState.from_mapping(row) for row in raw]
        if kind == "mixed":
            compact[::3] = raw[::3]
    keys = [(0 if equal_scores else -(i % 13), -(i % 11), i % 5) for i in range(160)]
    reference_indexes = {id(row): i for i, row in enumerate(raw)}
    compact_indexes = {id(row): i for i, row in enumerate(compact)}
    reference_calls, compact_calls = [], []

    def reference_rank(row):
        i = reference_indexes[id(row)]
        reference_calls.append(i)
        return keys[i]

    def compact_rank(row):
        i = compact_indexes[id(row)]
        compact_calls.append(i)
        return keys[i]

    expected = diverse(raw, reference_rank, limit)
    actual = diverse(iter(compact), compact_rank, limit)
    assert [compact_indexes[id(row)] for row in actual] == [
        reference_indexes[id(row)] for row in expected
    ]
    assert compact_calls == reference_calls == list(range(160))


@pytest.mark.parametrize("state_type", [EquipmentState, AssignmentState])
def test_compact_diversity_uses_cached_identity_instead_of_pairwise_equality(
    monkeypatch, state_type
):
    rows = [
        state_type.from_mapping(
            {"weapon": i % 50 + 1}
            if state_type is EquipmentState
            else {"a": {"weapon": i % 50 + 1}}
        )
        for i in range(200)
    ]
    calls = []
    original = state_type.__eq__

    def equals(self, other):
        calls.append(1)
        return original(self, other)

    monkeypatch.setattr(state_type, "__eq__", equals)
    assert len(diverse(rows, lambda row: (0, 0), 32)) == 32
    assert not calls
