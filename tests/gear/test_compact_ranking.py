"""Partial assignment ties retain the original lexical JSON ordering lazily."""

import json

from tracker.gear.compact_ranking import AssignmentTie
from tracker.gear.compact_states import AssignmentState


def test_lexical_order_matches_json_including_item_and_role_names():
    mappings = [
        {role: {"weapon": item, "head": 3}} for role in ("z", "a", "é") for item in (2, 10, 100)
    ]
    rows = [(AssignmentTie(AssignmentState.from_mapping(row)), row) for row in mappings]
    assert [row for _, row in sorted(rows, key=lambda row: row[0])] == sorted(
        mappings, key=lambda row: json.dumps(row, sort_keys=True)
    )


def test_numeric_rank_difference_never_renders_assignment():
    first = AssignmentTie(AssignmentState.from_mapping({"a": {"weapon": 2}}))
    second = AssignmentTie(AssignmentState.from_mapping({"a": {"weapon": 10}}))
    assert (1, first) < (2, second)
    assert first._text is None and second._text is None


def test_equal_assignments_ignore_insertion_order_and_render_only_once():
    a = AssignmentTie(AssignmentState.from_mapping({"z": {"head": 3, "weapon": 2}, "a": {}}))
    b = AssignmentTie(AssignmentState.from_mapping({"a": {}, "z": {"weapon": 2, "head": 3}}))
    assert a == b and not a < b
    assert a._text is None and b._text is None
    expected = json.dumps({"a": {}, "z": {"weapon": 2, "head": 3}}, sort_keys=True)
    assert a == expected
    assert a.text() == expected and a._assignment is None
    assert a != object()
    assert a < expected + "x"
    assert a.__lt__(object()) is NotImplemented
