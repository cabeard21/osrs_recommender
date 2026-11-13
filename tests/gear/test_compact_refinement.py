"""Compact refinement preserves exact substitution order and work."""

from types import SimpleNamespace

import pytest

from tools.benchmark_gear_desktop import without_observations
from tools.gear_retention_oracle import tiny_cases
from tracker.gear.compact_states import AssignmentState, EquipmentState
from tracker.gear.local_refinement import _group
from tracker.gear.optimizer import optimize
from tracker.gear.refinement import _role_options, refine_magic_staves, refine_shared_slots


@pytest.mark.parametrize("case", tiny_cases(), ids=lambda case: case.name)
def test_compact_refinement_complete_tiny_case_parity(case):
    args = (case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    flags = {
        "_execution_profile": "combined",
        "_factored_evaluation": True,
        "_fixed_reporting": True,
        "local_refinement": True,
    }
    expected = optimize(*args, **flags)
    actual = optimize(*args, **flags, _compact_states=True)
    assert without_observations(actual) == without_observations(expected)


@pytest.mark.parametrize("slots", [("head",), ("head", "weapon")])
def test_compact_refinement_group_preserves_dictionary_trial_order(slots):
    original = {"a": {"head": 2, "weapon": 10, "cape": 30}, "b": {"weapon": 10}}
    options = {"head": (None, 2, 3), "weapon": (None, 10, 11)}
    expected = list(_group(original, "a", slots, options))
    actual = list(_group(AssignmentState.from_mapping(original), "a", slots, options))
    assert actual == expected
    assert actual and all(isinstance(row, AssignmentState) for row in actual)
    assert [list(row["a"].items()) for row in actual] == [
        list(row["a"].items()) for row in expected
    ]


def test_ammunition_trial_equipment_stays_compact_and_reappends():
    role = SimpleNamespace(id="a", style="slash", locks={})
    performance = {"supported": True}
    search = SimpleNamespace(
        compact_states=True,
        request=SimpleNamespace(roles=(role,), locks={}),
        performance=lambda equipment, role: performance,
    )
    solution = {
        "loadouts": {"a": {"equipment": {"ammunition": 2, "weapon": 1}, "performance": performance}}
    }
    trials = _role_options(search, solution, [None, 2, 3])[0]
    assert all(isinstance(row, EquipmentState) for row in trials)
    assert [list(row.items()) for row in trials] == [
        [("ammunition", 2), ("weapon", 1)],
        [("weapon", 1)],
        [("weapon", 1), ("ammunition", 3)],
    ]


@pytest.mark.parametrize("magic", [False, True])
def test_shared_and_staff_substitutions_reach_validator_as_compact_assignments(magic):
    role = SimpleNamespace(id="a", style="magic", locks={})
    rows = []

    def validate(assignment, limit):
        rows.append(assignment)
        return None

    item = SimpleNamespace(
        slot="weapon" if magic else "head",
        attack_styles=("magic",),
        bonuses=SimpleNamespace(model_dump=lambda: {"magic": 1}),
    )
    search = SimpleNamespace(
        compact_states=True,
        request=SimpleNamespace(roles=(role,), locks={}),
        cancelled=None,
        eligible={3: item},
        pools={"head": [None, 3]},
        solution=validate,
    )
    solution = {"maximum_actions": 0, "loadouts": {"a": {"equipment": {"weapon": 1}}}}
    function = refine_magic_staves if magic else refine_shared_slots
    assert function(search, solution, lambda row: ()) is solution
    assert len(rows) == 1 and isinstance(rows[0], AssignmentState)
    assert rows[0]["a"] == ({"weapon": 3} if magic else {"weapon": 1, "head": 3})
