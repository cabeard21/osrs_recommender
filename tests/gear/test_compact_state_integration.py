import pytest

from tests.gear.test_factored_multi import multi_case
from tools.benchmark_gear_desktop import without_observations
from tracker.gear.optimizer import optimize


@pytest.mark.parametrize("compact", [False, True])
def test_product_expansion_is_released_before_refinement(monkeypatch, compact):
    """The final expansion can dwarf the retained beam and must not span frontiers."""
    import sys

    from tracker.gear.progress import StageReporter

    observed = []
    original = StageReporter.stage

    def stage(self, phase, **extra):
        if phase == "refinement":
            frame = sys._getframe(1)
            if frame.f_code.co_name == "optimize":
                observed.append(True)
                assert "expanded" not in frame.f_locals
        return original(self, phase, **extra)

    monkeypatch.setattr(StageReporter, "stage", stage)
    optimize(
        *multi_case(),
        _execution_profile="combined",
        _factored_evaluation=True,
        _compact_states=compact,
    )
    assert observed


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("special", [False, True])
@pytest.mark.parametrize("priority", ["default", "balanced_defence", "magic_ranged_defence_roll"])
def test_compact_state_complete_parity(configured, special, priority):
    args = multi_case(configured, special, priority)
    options = {
        "_execution_profile": "combined",
        "_factored_evaluation": True,
        "_fixed_reporting": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
        "local_refinement": True,
    }
    expected = optimize(*args, **options)
    actual = optimize(*args, **options, _compact_states=True)
    assert without_observations(actual) == without_observations(expected)


@pytest.mark.parametrize("configured", [False, True])
def test_beams_use_compact_states_with_identical_logical_work(configured):
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear.compact_states import AssignmentState, EquipmentState
    from tracker.gear.execution_profile import execution_context

    args = multi_case(configured)
    with execution_context("combined", args[1], factored_evaluation=True):
        reference = search(args)
        expected_single = reference.loadouts((args[1].roles[0],))
        expected_joint = reference.joint_loadouts(2)
        nodes = reference.nodes
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        candidate = search(args)
        single = candidate.loadouts((args[1].roles[0],))
        joint = candidate.joint_loadouts(2)
        assert single and all(isinstance(row, EquipmentState) for row in single)
        assert joint and all(isinstance(row, AssignmentState) for row in joint)
        assert single == expected_single
        assert joint == expected_joint
        assert candidate.nodes == nodes


def test_default_priority_publication_materializes_new_cleanup_candidates(monkeypatch):
    import json

    import tracker.gear.optimizer as optimizer
    from tracker.gear.variant_reporting import CompactVariant, materialize

    args = multi_case(priority="default")
    args[1] = args[1].model_copy(update={"roles": (args[1].roles[0],)})
    flags = {
        "_execution_profile": "combined",
        "_factored_evaluation": True,
        "_fixed_reporting": True,
        "local_refinement": True,
    }
    expected = optimize(*args, **flags)
    original = optimizer.refine_ammunition
    created = []

    def deferred(*args, **kwargs):
        full = materialize(original(*args, **kwargs))
        projection = {
            **full,
            "loadouts": {
                rid: {**row, "performance": {"supported": True, "dps": row["performance"]["dps"]}}
                for rid, row in full["loadouts"].items()
            },
        }
        candidate = CompactVariant(projection, lambda: full)
        created.append(candidate)
        return candidate

    monkeypatch.setattr(optimizer, "refine_ammunition", deferred)
    actual = optimize(*args, **flags, _compact_states=True)
    assert created
    json.dumps(actual)
    assert without_observations(actual) == without_observations(expected)


def test_compact_action_bounds_equal_dictionary_bounds():
    from itertools import product
    from types import SimpleNamespace

    from tracker.gear.compact_states import EquipmentState
    from tracker.gear.optimizer import _action_lower_bound

    items = {
        1: SimpleNamespace(two_handed=False),
        2: SimpleNamespace(two_handed=True),
        3: SimpleNamespace(two_handed=False),
        4: SimpleNamespace(two_handed=False),
    }
    gear = [
        {k: v for k, v in zip(("weapon", "shield", "head"), row, strict=True) if v is not None}
        for row in product((None, 1, 2), (None, 3), (None, 4))
    ]
    for source, destination in product(gear, repeat=2):
        assert _action_lower_bound(
            EquipmentState.from_mapping(source), EquipmentState.from_mapping(destination), items
        ) == _action_lower_bound(source, destination, items)


def test_joint_expansion_constructs_one_assignment_per_candidate(monkeypatch):
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear.compact_states import AssignmentState
    from tracker.gear.execution_profile import execution_context

    args = multi_case()
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        original = AssignmentState.__post_init__
        per_candidate = [0]
        original_tick = instance.tick

        def counted(self):
            per_candidate[-1] += 1
            original(self)

        def tick():
            per_candidate.append(0)
            return original_tick()

        monkeypatch.setattr(AssignmentState, "__post_init__", counted)
        monkeypatch.setattr(instance, "tick", tick)
        assert instance.joint_loadouts(2)
        assert max(per_candidate) <= 1


def test_joint_pruning_precedes_assignment_allocation(monkeypatch):
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear.compact_states import AssignmentState
    from tracker.gear.execution_profile import execution_context

    args = multi_case()
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        original_init = AssignmentState.__post_init__
        original_retain = instance.retain
        constructed = []
        accepted = []

        def initialize(self):
            constructed.append(1)
            original_init(self)

        def retain(rows, rank, limit):
            accepted.append(len(rows))
            return original_retain(rows, rank, limit)

        monkeypatch.setattr(AssignmentState, "__post_init__", initialize)
        monkeypatch.setattr(instance, "retain", retain)
        assert not instance.joint_loadouts(0)
        assert len(constructed) == 1 + sum(accepted)


def test_single_budget_rejection_precedes_equipment_allocation(monkeypatch):
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear.compact_states import EquipmentState
    from tracker.gear.execution_profile import execution_context

    args = multi_case()
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        instance.request = instance.request.model_copy(update={"budget_gp": 0})
        monkeypatch.setattr(instance, "cost", lambda ids: int(1 in ids))
        created = []
        original = EquipmentState.with_slot

        def tracked(self, slot, item):
            created.append((slot, item))
            return original(self, slot, item)

        monkeypatch.setattr(EquipmentState, "with_slot", tracked)
        assert instance.loadouts((args[1].roles[0],)) == []
        assert not created


def test_single_hand_constraint_rejection_precedes_equipment_allocation(monkeypatch):
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear.compact_states import EquipmentState
    from tracker.gear.execution_profile import execution_context

    args = multi_case()
    args[2].items = {
        **args[2].items,
        1: args[2].items[1].model_copy(update={"two_handed": True}),
        10: args[2].items[10].model_copy(update={"slot": "shield"}),
    }
    with execution_context("combined", args[1], factored_evaluation=True):
        reference = search(args)
        expected = reference.loadouts((args[1].roles[0],))
        nodes = reference.nodes
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        original = EquipmentState.with_slot
        rejected = []

        def tracked(self, slot, item):
            if slot == "shield" and item is not None:
                rejected.append(item)
            return original(self, slot, item)

        monkeypatch.setattr(EquipmentState, "with_slot", tracked)
        assert instance.loadouts((args[1].roles[0],)) == expected
        assert instance.nodes == nodes
        assert not rejected
