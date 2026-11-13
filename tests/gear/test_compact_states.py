import pickle
import random
from dataclasses import FrozenInstanceError

import pytest

from tracker.gear.compact_states import AssignmentState, EquipmentState


def test_equipment_mapping_order_and_replacement():
    source = {"head": 10, "weapon": 2}
    state = EquipmentState.from_mapping(source)
    assert state == source and source == state
    assert list(state.items()) == list(source.items())
    assert state.with_slot("head", 11).to_dict() == {"head": 11, "weapon": 2}
    assert list(state.without_slot("head").with_slot("head", 11)) == ["weapon", "head"]
    assert state.identity == (("head", 10), ("weapon", 2))
    assert state == EquipmentState.from_mapping(dict(reversed(list(source.items()))))
    assert state.to_dict() is not source
    with pytest.raises(FrozenInstanceError):
        state.order = ()


def test_empty_and_invalid_slots():
    state = EquipmentState.from_mapping({})
    assert len(state) == 0 and not state
    assert state.with_slot("head", None) is state
    with pytest.raises(KeyError):
        _ = state["head"]
    with pytest.raises(KeyError):
        state.with_slot("invalid", 1)


def test_assignment_preserves_roles_and_shared_physical_items():
    source = {"z": {"weapon": 2, "head": 10}, "a": {"weapon": 2, "head": 11}}
    state = AssignmentState.from_mapping(source)
    assert state == source and source == state
    assert list(state) == ["z", "a"]
    assert state.reference_counts == ((2, 2), (10, 1), (11, 1))
    assert state.carried == frozenset((2, 10, 11))
    changed = state.with_slot("a", "head", 10)
    assert changed.reference_counts == ((2, 2), (10, 2))
    assert changed.to_dict() == {"z": source["z"], "a": {"weapon": 2, "head": 10}}
    assert state.to_dict() == source
    assert list(changed.with_role("b", {})) == ["z", "a", "b"]
    with pytest.raises(KeyError):
        _ = state["missing"]


def test_aggregation_order_survives_roundtrip_and_updates():
    terms = {1: 0.1, 2: 0.3, 3: -0.2}
    original = {"head": 1, "weapon": 2, "cape": 3}
    state = EquipmentState.from_mapping(original)
    assert tuple(state.values()) == tuple(original.values())
    assert sum(terms[i] for i in state.values()) == sum(terms[i] for i in original.values())
    assert EquipmentState.from_mapping(state) is state
    joint = AssignmentState.from_mapping({"a": state})
    assert AssignmentState.from_mapping(joint) is joint


def test_operation_sequences_match_dictionary_and_pickle():
    from tracker.gear.compact_states import SLOT_NAMES

    rng = random.Random(81)
    expected = {}
    state = EquipmentState.from_mapping(expected)
    for _ in range(200):
        slot = rng.choice(SLOT_NAMES)
        item = rng.choice((None, 2, 10, 15))
        if item is None:
            expected.pop(slot, None)
        else:
            expected[slot] = item
        state = state.with_slot(slot, item)
        assert list(state.items()) == list(expected.items())
        assert state == expected
        assert state.ordered_ids == tuple(expected.values())
        assert state.ordered_identity == tuple(expected.items())
        assert state.identity == tuple(sorted(expected.items()))
        assert state.physical_ids == frozenset(expected.values())
        assert pickle.loads(pickle.dumps(state)).to_dict() == expected
    assignment = AssignmentState.from_mapping({"z": state, "a": {}})
    assert assignment.identity == (("a", ()), ("z", state.identity))
    assert pickle.loads(pickle.dumps(assignment)) == assignment


def test_scoring_uses_stored_ordered_ids_without_mapping_iteration(monkeypatch):
    from tests.gear.test_incremental_scoring import item
    from tracker.gear.scoring import EquipmentScorer

    items = {1: item(1, "head", magic_damage=0.1), 2: item(2, "body", magic_damage=0.2)}
    mapping = {"body": 2, "head": 1}
    state = EquipmentState.from_mapping(mapping)
    assert state.ordered_ids == (2, 1)
    assert state.physical_ids == frozenset((1, 2))
    scorer = EquipmentScorer(items)
    expected = scorer.prepare(mapping)

    def fail(*args):
        pytest.fail("Compact scoring must use stored ordered IDs")

    monkeypatch.setattr(EquipmentState, "values", fail)
    assert scorer.prepare(state) is expected


def test_same_type_equality_avoids_mapping_iteration(monkeypatch):
    left = EquipmentState.from_mapping({"head": 1, "weapon": 2})
    right = EquipmentState.from_mapping({"weapon": 2, "head": 1})
    joint_left = AssignmentState.from_mapping({"a": left, "b": right})
    joint_right = AssignmentState.from_mapping({"b": left, "a": right})

    def fail(*args):
        pytest.fail("Same-type equality must use cached physical identities")

    monkeypatch.setattr(EquipmentState, "items", fail)
    monkeypatch.setattr(AssignmentState, "items", fail)
    assert left == right
    assert joint_left == joint_right
    assert joint_left.with_role("a", left) is joint_left


def test_equipment_pool_reuses_only_exact_order_and_releases_on_error():
    from tracker.gear.compact_states import equipment_pool

    with pytest.raises(RuntimeError), equipment_pool(2) as pool:
        first = EquipmentState.from_mapping({"head": 1, "weapon": 2})
        assert EquipmentState.from_mapping({"head": 1, "weapon": 2}) is first
        reverse = EquipmentState.from_mapping({"weapon": 2, "head": 1})
        assert reverse == first and reverse is not first
        assert pool.cache_info().hits == 1
        EquipmentState.from_mapping({"head": 3})
        assert pool.cache_info().currsize == 2
        raise RuntimeError("cancelled")
    assert pool.cache_info().currsize == 0
    assert EquipmentState.from_mapping({"head": 1, "weapon": 2}) is not first
    with equipment_pool() as later:
        assert later.cache_info().currsize == 0
        assert EquipmentState.from_mapping({"head": 1, "weapon": 2}) is not first


def test_pool_with_slot_and_nested_contexts_restore_outer_pool():
    from tracker.gear.compact_states import equipment_pool

    with equipment_pool():
        first = EquipmentState.from_mapping({"head": 1})
        empty = EquipmentState.from_mapping({})
        assert empty.with_slot("head", 1) is first
        with equipment_pool():
            assert EquipmentState.from_mapping({"head": 1}) is not first
        assert EquipmentState.from_mapping({"head": 1}) is first


@pytest.mark.parametrize("joint", [False, True])
def test_execution_context_owns_pool_only_when_p3_enabled(joint):
    from tests.gear.test_auto_disciplines import context
    from tracker.gear.execution_profile import execution_context

    request = context()[1]
    if joint:
        request = request.model_copy(
            update={"roles": (request.roles[0], request.roles[0].model_copy(update={"id": "b"}))}
        )
    for enabled in (False, True):
        with execution_context(
            "combined", request, factored_evaluation=True, compact_states=enabled
        ):
            first = EquipmentState.from_mapping({"head": 1})
            second = EquipmentState.from_mapping({"head": 1})
            assert (first is second) is (enabled and joint)
        assert EquipmentState.from_mapping({"head": 1}) is not first


def test_assignment_union_does_not_compute_unused_reference_counts(monkeypatch):
    import tracker.gear.compact_states as module

    def fail(*args):
        pytest.fail("Physical union construction must not build diagnostic refcounts")

    monkeypatch.setattr(module, "Counter", fail)
    state = AssignmentState.from_mapping({"a": {"weapon": 2}, "b": {"weapon": 2}})
    assert state.carried == frozenset((2,))
    assert state.with_role("a", {}).carried == frozenset((2,))
    assert state.with_role("a", {}).with_role("b", {}).carried == frozenset()


def test_unpooled_slot_updates_reuse_unchanged_pairs_without_full_preparation(monkeypatch):
    original = EquipmentState.from_mapping({"head": 1, "weapon": 2, "body": 3})
    expected = EquipmentState.from_mapping({"head": 1, "weapon": 4, "body": 3})

    def fail(*args):
        pytest.fail("Single-slot update must reuse the immutable parent's metadata")

    monkeypatch.setattr(EquipmentState, "__post_init__", fail)
    actual = original.with_slot("weapon", 4)
    assert actual == expected
    assert actual.ordered_identity == expected.ordered_identity
    assert actual.identity == expected.identity
    assert actual.physical_ids == expected.physical_ids
    assert actual.ordered_identity[0] is original.ordered_identity[0]
    assert actual.ordered_identity[2] is original.ordered_identity[2]
    removed = actual.without_slot("head")
    assert removed.ordered_ids == (4, 3)
    assert removed.physical_ids == frozenset((3, 4))
    appended = removed.with_slot("head", 1)
    assert appended.order == (0, 6, 3)
    assert appended.ordered_ids == (4, 3, 1)
    repeated = appended.with_slot("body", 1).without_slot("head")
    assert repeated.physical_ids == frozenset((1, 4))


def test_direct_get_and_contains_keep_mapping_defaults_and_key_errors(monkeypatch):
    state = EquipmentState.from_mapping({"head": 1})
    sentinel = object()

    def fail(*args):
        pytest.fail("Cached fixed slots must bypass Mapping __getitem__")

    monkeypatch.setattr(EquipmentState, "__getitem__", fail)
    assert state.get("head") == 1
    assert state.get(key="head") == 1
    assert state.get(key="weapon", default=0) == 0
    assert state.get("weapon") is None
    assert state.get("unknown", sentinel) is sentinel
    assert "head" in state
    assert "weapon" not in state
    assert "unknown" not in state
    assert 0 not in state
    with pytest.raises(TypeError):
        state.get([])
    with pytest.raises(TypeError):
        _ = [] in state


def test_equipment_views_are_compact_mapping_views():
    state = EquipmentState.from_mapping({"ring": 9, "head": 2})
    items, values = state.items(), state.values()
    assert not hasattr(items, "__dict__")
    assert not hasattr(values, "__dict__")
    assert list(items) == [("ring", 9), ("head", 2)]
    assert list(values) == [9, 2]
    assert len(items) == len(values) == 2
    assert items & {("head", 2), ("head", 3)} == {("head", 2)}
    assert 9 in values


@pytest.mark.parametrize("slot,item", [("ammunition", 3), ("ring", 2), ("weapon", 0)])
def test_append_metadata_matches_full_constructor_and_keeps_parent_pairs(slot, item):
    original = EquipmentState.from_mapping({"head": 2, "body": 3})
    expected = EquipmentState.from_mapping({"head": 2, "body": 3, slot: item})
    actual = original.with_slot(slot, item)
    assert actual == expected
    for attribute in (
        "slots",
        "order",
        "identity",
        "ordered_identity",
        "ordered_ids",
        "physical_ids",
    ):
        assert getattr(actual, attribute) == getattr(expected, attribute)
    assert actual.ordered_identity[0] is original.ordered_identity[0]
    assert actual.ordered_identity[1] is original.ordered_identity[1]
    assert original.to_dict() == {"head": 2, "body": 3}


def test_compact_validation_uses_ordered_pairs_and_preserves_errors(monkeypatch):
    from tests.gear.test_incremental_scoring import item
    from tracker.gear.evaluation import equipment_problems

    catalog = {
        1: item(1, "weapon").model_copy(update={"two_handed": True}),
        2: item(2, "head"),
        3: item(3, "shield"),
    }
    assignment = {"feet": 99, "head": 3, "weapon": 1, "shield": 2}
    state = EquipmentState.from_mapping(assignment)
    expected = equipment_problems(assignment, catalog)

    def fail(*args):
        pytest.fail("Compact validation must iterate existing ordered pairs")

    monkeypatch.setattr(EquipmentState, "items", fail)
    assert equipment_problems(state, catalog) == expected
